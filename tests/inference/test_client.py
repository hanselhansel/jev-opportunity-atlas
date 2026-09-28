import asyncio
import json
import secrets
from pathlib import Path

import pytest

from atlas.inference.client import (
    JevClient,
    ModelMismatch,
    RetryPolicy,
    UnsafeEndpoint,
    validate_answers,
)
from tests.inference.mock_jev import make_transport

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64
Q = {"q": {"type": "noul", "instructions": "Is `comment` a problem?"}}
Q_CHOICE = {
    "c": {"type": "choice", "instructions": "?", "criteria": {"a": "A", "b": "B"}}
}


def run(script, **kw):
    seen = []
    client = JevClient(api_key=CANARY, base="http://mock", transport=make_transport(script, seen),
                       policy=RetryPolicy(max_attempts=4, backoff_initial=0, backoff_max=0), **kw)
    result = asyncio.run(client.evaluate({"comment": "x"}, Q, model="jev-1.13.0"))
    return result, seen


def evaluate(script, questions=Q, max_attempts=4, on_attempt=None):
    seen = []
    client = JevClient(
        api_key=CANARY,
        base="http://mock",
        transport=make_transport(script, seen),
        policy=RetryPolicy(
            max_attempts=max_attempts, backoff_initial=0, backoff_max=0
        ),
    )
    result = asyncio.run(
        client.evaluate(
            {"comment": "x"}, questions, model="jev-1.13.0", on_attempt=on_attempt
        )
    )
    return result, seen


def test_success_records_one_attempt_with_request_id_and_usage():
    res, seen = run(["ok"])
    assert res.ok and len(res.attempts) == 1
    a = res.attempts[0]
    assert (a.http_status, a.request_id, a.input_tokens, a.model_returned) == (200, "req_0001", 300, "jev-1.13.0")
    assert seen[0].headers["authorization"] == f"Bearer {CANARY}"


def test_retries_are_visible_as_separate_attempts():
    res, _ = run(["429", "529", "ok"])
    assert res.ok and [a.http_status for a in res.attempts] == [429, 529, 200]
    assert [a.error_type for a in res.attempts] == ["rate_limited", "overloaded", None]


def test_timeout_is_an_unknown_charge_not_free():
    res, _ = run(["timeout", "ok"])
    assert res.attempts[0].error_type == "timeout" and res.attempts[0].charge_known is False
    assert res.attempts[1].charge_known is True


def test_null_usage_marks_charge_unknown_but_keeps_answers():
    res, _ = run(["null_usage"])
    assert res.ok and res.attempts[0].input_tokens is None and res.attempts[0].charge_known is False


def test_non_retryable_422_stops():
    res, _ = run(["422"])
    assert not res.ok and len(res.attempts) == 1
    assert res.attempts[0].error_type == "invalid_request" and res.attempts[0].charge_known is True


def test_bad_json_is_validation_failure():
    res, _ = run(["bad_json", "bad_json", "bad_json", "bad_json"])
    assert not res.ok and all(a.validation == "invalid_json" for a in res.attempts)


def test_key_never_in_reprs_or_errors():
    res, _ = run(["500", "500", "500", "500"])
    blob = repr(res) + "".join(repr(a) for a in res.attempts)
    assert CANARY not in blob and not res.ok


def test_real_response_shape_fixture_parses():
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "response_shape.json").read_text()
    )
    assert validate_answers(fixture["request"]["questions"], fixture["body"])


def test_choice_outside_options_is_schema_error():
    res, _ = evaluate(["bad_choice"], questions=Q_CHOICE)
    assert res.ok  # one schema retry, second attempt answers "ok"
    assert res.attempts[0].validation == "schema"
    assert res.attempts[0].error_type == "schema"


def test_schema_error_retried_once():
    res, seen = evaluate(["bad_choice", "bad_choice", "ok"], questions=Q_CHOICE)
    assert not res.ok and len(res.attempts) == 2 and len(seen) == 2
    assert all(a.validation == "schema" for a in res.attempts)


def test_missing_question_is_schema_error():
    res, _ = evaluate(["missing_question"], questions={**Q, "q2": Q["q"]})
    assert res.attempts[0].validation == "schema" and res.attempts[0].error_type == "schema"


def test_model_mismatch_aborts():
    seen = []
    client = JevClient(
        api_key=CANARY,
        base="http://mock",
        transport=make_transport(["wrong_model"], seen),
        policy=RetryPolicy(max_attempts=4, backoff_initial=0, backoff_max=0),
    )
    with pytest.raises(ModelMismatch):
        asyncio.run(client.evaluate({"comment": "x"}, Q, model="jev-1.13.0"))
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("outcome", "charge_known", "tokens"),
    [
        ("ok", True, 300),
        ("null_usage", False, None),
        ("429", True, 0),
        ("401", True, 0),
        ("422", True, 0),
        ("500", False, None),
        ("529", False, None),
        ("timeout", False, None),
        ("read_error", False, None),
        ("connect_error", True, 0),
    ],
)
def test_charge_classes(outcome, charge_known, tokens):
    res, _ = evaluate([outcome], max_attempts=1)
    assert len(res.attempts) == 1
    a = res.attempts[0]
    assert a.charge_known is charge_known and a.input_tokens == tokens


def test_on_attempt_phases():
    events = []

    async def cb(event):
        events.append((event.phase, event.attempt_no))

    res, _ = evaluate(["500", "ok"], on_attempt=cb)
    assert res.ok
    assert events == [
        ("before_send", 1),
        ("after_response", 1),
        ("before_send", 2),
        ("after_response", 2),
    ]


def test_unexpanded_sentence_marker_rejected():
    questions = {
        "s": {"type": "choice", "instructions": "?", "criteria": "SENTENCE_IDS"}
    }
    client = JevClient(
        api_key=CANARY,
        base="http://mock",
        transport=make_transport(["ok"]),
        policy=RetryPolicy(max_attempts=1, backoff_initial=0, backoff_max=0),
    )
    with pytest.raises(AssertionError):
        asyncio.run(client.evaluate({"comment": "x"}, questions, model="jev-1.13.0"))


def test_real_shaped_key_refuses_other_host():
    key = "apikey_" + secrets.token_hex(18) + "_" + secrets.token_hex(32)
    with pytest.raises(UnsafeEndpoint) as exc:
        JevClient(api_key=key, base="http://127.0.0.1:9")
    assert key not in str(exc.value)
    JevClient(api_key=CANARY, base="http://mock")  # canary is accepted off-host


def test_client_repr_never_contains_key():
    client = JevClient(api_key=CANARY, base="http://mock")
    assert CANARY not in repr(client)
