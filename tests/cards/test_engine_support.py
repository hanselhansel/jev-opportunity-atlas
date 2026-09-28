"""Shared helpers for cards-engine tests: canary key, a RunContext factory, and a
configurable mock transport in the same response shape as
tests.inference.mock_jev (model "jev-1.13.0", usage 300/20 tokens,
x-typesafe-request-id header).

`chooser(state, qid, options) -> option key` (default: first option),
`noul(state, qid) -> float` (default 0.8), `score(state, qid, n) -> index`
(default 1). `confidence` may be a float or a callable(state, qid).
"""

import json

import httpx

from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient, RetryPolicy
from atlas.inference.runner import RunContext

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64
PRICE = 0.042e-6


def make_ctx(tmp_path, transport, run_id="r1", cap=1.0):
    client = JevClient(
        api_key=CANARY,
        base="http://mock",
        transport=transport,
        policy=RetryPolicy(backoff_initial=0, backoff_max=0),
    )
    guard = BudgetGuard(
        cap_usd=cap, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000
    )
    return RunContext(
        run_id=run_id,
        run_dir=tmp_path / run_id,
        client=client,
        guard=guard,
        model="jev-1.13.0",
        price_version="typesafe-2026-09-28",
        cache_path=tmp_path / "cache.sqlite",
        concurrency=4,
    )


def make_transport(chooser=None, noul=None, score=None, seen=None, confidence=0.9):
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        if seen is not None:
            seen.append(request)
        body = json.loads(request.content)
        answers = {}
        for qid, q in body.get("questions", {}).items():
            qtype = q.get("type")
            if qtype == "noul":
                val = noul(body["state"], qid) if callable(noul) else noul
                answers[qid] = {"type": "noul", "noul": 0.8 if val is None else val}
            elif qtype == "choice":
                opts = list(q["criteria"])
                chosen = chooser(body["state"], qid, opts) if chooser else opts[0]
                conf = (
                    confidence(body["state"], qid)
                    if callable(confidence)
                    else confidence
                )
                answers[qid] = {
                    "type": "choice",
                    "choice": chosen,
                    "confidence": conf,
                    "probabilities": {
                        o: (1.0 if o == chosen else 0.0) for o in opts
                    },
                }
            elif qtype == "score":
                crit = q.get("criteria") or []
                idx = score(body["state"], qid, len(crit)) if score else 1
                answers[qid] = {
                    "type": "score",
                    "score": float(idx),
                    "confidence": 0.8,
                    "legend": {str(i): str(c) for i, c in enumerate(crit)},
                    "probabilities": {
                        str(i): (1.0 if i == idx else 0.0)
                        for i in range(len(crit))
                    },
                }
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": f"req_{counter['n']:04d}"},
            json={
                "model": "jev-1.13.0",
                "answers": answers,
                "usage": {"input_tokens": 300, "output_tokens": 20},
            },
        )

    return httpx.MockTransport(handler)


def test_support_helper_answers_all_types(tmp_path):
    import asyncio

    from atlas.inference.questions import QuestionSet
    from atlas.inference.runner import run_batch

    qs = QuestionSet(
        name="t",
        version=1,
        label="t@1",
        state_fields=[],
        questions={
            "c": {"type": "choice", "criteria": {"a": "A", "b": "B"}},
            "n": {"type": "noul", "criteria": {"true": "y", "false": "n"}},
            "s": {"type": "score", "criteria": ["l0", "l1", "l2"]},
        },
        sha256="0" * 64,
    )
    item = {"comment_id": 9_000_000_001, "state": {"x": "y"},
            "questions": dict(qs.questions)}
    transport = make_transport(
        chooser=lambda state, qid, opts: "b",
        noul=lambda state, qid: 0.3,
        score=lambda state, qid, n: 2,
    )
    out = asyncio.run(run_batch(make_ctx(tmp_path, transport), [item], qs))
    assert out["completed"] == 1 and out["failed"] == 0
    import pyarrow.parquet as pq

    rows = {
        r["question_id"]: r
        for r in pq.read_table(tmp_path / "r1" / "answers").to_pylist()
    }
    assert rows["c"]["choice"] == "b"
    assert rows["n"]["noul"] == 0.3
    assert rows["s"]["score"] == 2.0
