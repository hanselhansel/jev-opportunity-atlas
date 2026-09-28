"""Deterministic fake of POST /v1/systemone. `script` is a list of outcomes consumed
per request: "ok", "429", "529", "500", "422", "401", "timeout", "connect_error",
"read_error", "null_usage", "bad_json", "bad_choice", "missing_question",
"wrong_model". An empty queue answers "ok".

`seen` (optional list) records every request that reaches the handler.
`on_request(n, request)` (optional) runs at the start of every request, n being the
1-based request count, before the outcome is chosen; it may raise to inject a crash.
Any request whose questions still carry a `"SENTENCE_IDS"` criterion raises
AssertionError (the marker must be expanded per item before sending).
"""

import json

import httpx


def answer_for(q: dict) -> dict:
    if q["type"] == "noul":
        return {"type": "noul", "noul": 0.8}
    if q["type"] == "choice":
        opts = list(q["criteria"])
        return {
            "type": "choice",
            "choice": opts[0],
            "confidence": 0.9,
            "probabilities": {o: (1.0 if i == 0 else 0.0) for i, o in enumerate(opts)},
        }
    n = len(q["criteria"])
    return {
        "type": "score",
        "score": 1.0,
        "confidence": 0.8,
        "legend": {str(i): str(c) for i, c in enumerate(q["criteria"])},
        "probabilities": {str(i): (1.0 if i == 1 else 0.0) for i in range(n)},
    }


def make_transport(
    script: list[str], seen: list | None = None, on_request=None
) -> httpx.MockTransport:
    queue = list(script)
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        n = counter["n"]
        if seen is not None:
            seen.append(request)
        if on_request is not None:
            on_request(n, request)
        body = json.loads(request.content)
        for q in body.get("questions", {}).values():
            if q.get("criteria") == "SENTENCE_IDS":
                raise AssertionError("unexpanded SENTENCE_IDS")
        outcome = queue.pop(0) if queue else "ok"
        rid = {"x-typesafe-request-id": f"req_{n:04d}"}
        if outcome == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if outcome == "connect_error":
            raise httpx.ConnectError("connect failed", request=request)
        if outcome == "read_error":
            raise httpx.ReadError("read failed", request=request)
        if outcome == "401":
            return httpx.Response(401, headers=rid, json={"error": "unauthorized"})
        if outcome in ("429", "529", "500"):
            return httpx.Response(
                int(outcome),
                headers={**rid, "retry-after": "0"},
                json={"error": outcome},
            )
        if outcome == "422":
            return httpx.Response(422, headers=rid, json={"error": "bad request"})
        if outcome == "bad_json":
            return httpx.Response(200, headers=rid, content=b"{not json")
        usage = (
            None
            if outcome == "null_usage"
            else {"input_tokens": 300, "output_tokens": 20}
        )
        answers = {}
        bad_choice_done = False
        for k, q in body["questions"].items():
            a = answer_for(q)
            if outcome == "bad_choice" and q["type"] == "choice" and not bad_choice_done:
                a = {**a, "choice": "not_an_option"}
                bad_choice_done = True
            answers[k] = a
        if outcome == "missing_question":
            first = next(iter(body["questions"]), None)
            if first is not None:
                answers.pop(first, None)
        model = "jev-9.9.9" if outcome == "wrong_model" else "jev-1.13.0"
        return httpx.Response(
            200,
            headers=rid,
            json={"model": model, "answers": answers, "usage": usage},
        )

    return httpx.MockTransport(handler)
