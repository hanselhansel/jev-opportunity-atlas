from atlas.inference.cache import ResponseCache, cache_key


def test_key_depends_on_every_input():
    base = {"state": {"comment": "x"}, "questions": {"q": {"type": "noul", "instructions": "?"}},
            "question_set": "screen@0", "model": "jev-1.13.0"}
    k = cache_key(**base)
    assert k == cache_key(**base)
    for field, value in [("state", {"comment": "y"}), ("question_set", "screen@1"), ("model", "jev-1.14.0")]:
        assert cache_key(**{**base, field: value}) != k


def test_put_get_keeps_original_provenance(tmp_path):
    c = ResponseCache(tmp_path / "jev.sqlite")
    c.put("k1", {"answers": {"q": {"type": "noul", "noul": 0.5}}}, run_id="r1", logical_call_id="L9",
          request_id="req_1", input_tokens=300)
    hit = c.get("k1")
    assert hit["response"]["answers"]["q"]["noul"] == 0.5
    assert (hit["run_id"], hit["logical_call_id"], hit["request_id"], hit["input_tokens"]) == ("r1", "L9", "req_1", 300)
    assert c.get("missing") is None
    c.close()


def test_first_answer_wins(tmp_path):
    c = ResponseCache(tmp_path / "jev.sqlite")
    c.put("k1", {"answers": {"q": {"noul": 0.1}}}, run_id="r1", logical_call_id="L1",
          request_id="req_1", input_tokens=100)
    c.put("k1", {"answers": {"q": {"noul": 0.9}}}, run_id="r2", logical_call_id="L2",
          request_id="req_2", input_tokens=200)
    hit = c.get("k1")
    assert hit["response"]["answers"]["q"]["noul"] == 0.1 and hit["run_id"] == "r1"
    c.close()
