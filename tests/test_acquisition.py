"""Acquisition correctness: classification, retries, shard resume, boundaries."""

import asyncio
import json
from dataclasses import asdict

import httpx
import pytest

from atlas.sources import shards as sh
from atlas.sources.boundaries import first_id_at_or_after
from atlas.sources.hn_api import FetchRecord, classify, fetch_item


class FakeClient:
    """Serves a dict of id -> item (None means JSON null); fails ids in `flaky` n times."""

    def __init__(self, items, flaky=None, status=503):
        self.items, self.flaky, self.status, self.calls = (
            items,
            dict(flaky or {}),
            status,
            0,
        )

    async def get(self, url):
        self.calls += 1
        i = int(url.rsplit("/", 1)[1].split(".")[0])
        if self.flaky.get(i, 0) > 0:
            self.flaky[i] -= 1
            return httpx.Response(self.status)
        return httpx.Response(200, content=json.dumps(self.items.get(i)).encode())


async def no_sleep(_):
    return None


def run(coro):
    return asyncio.run(coro)


def test_classify_states():
    assert classify(None) == "null"
    assert classify({"id": 1, "deleted": True}) == "deleted"
    assert classify({"id": 1, "dead": True, "text": "x"}) == "dead"
    assert classify({"id": 1, "text": "x"}) == "ok"


def test_retry_attempts_are_recorded():
    c = FakeClient({7: {"id": 7, "time": 1}}, flaky={7: 2})
    rec = run(fetch_item(c, "https://x", 7, max_attempts=5, sleep=no_sleep))
    assert (
        rec.state == "ok"
        and rec.attempts == 3
        and rec.errors == ["http_503", "http_503"]
    )
    assert rec.backoff_s == 3.0  # 1 + 2


def test_exhausted_retries_mark_failed_not_null():
    c = FakeClient({}, flaky={9: 99})
    rec = run(fetch_item(c, "https://x", 9, max_attempts=3, sleep=no_sleep))
    assert rec.state == "failed" and rec.attempts == 3 and rec.item is None


def test_non_retryable_status_stops_early():
    c = FakeClient({}, flaky={9: 99}, status=404)
    rec = run(fetch_item(c, "https://x", 9, max_attempts=5, sleep=no_sleep))
    assert rec.state == "failed" and c.calls == 1


def rec(i, state="ok"):
    item = (
        None
        if state in ("null", "failed")
        else {"id": i, "time": 1000 + i, "type": "comment"}
    )
    return asdict(FetchRecord(i, state, 200, 1, 0.0, "t", "t", 1.0, "h", item))


def test_shard_lifecycle_complete_partial_corrupt(tmp_path):
    spec = sh.ShardSpec(0, 4)
    assert sh.shard_status(tmp_path, spec) == "missing"
    sh.write_shard(
        tmp_path, spec, [rec(0), rec(1, "failed"), rec(2, "null"), rec(3)], 1
    )
    assert sh.shard_status(tmp_path, spec) == "partial"
    assert set(sh.reusable_records(tmp_path, spec)) == {0, 2, 3}
    sh.write_shard(tmp_path, spec, [rec(i) for i in range(4)], 2)
    assert sh.shard_status(tmp_path, spec) == "complete"
    data_p, _ = sh.paths(tmp_path, spec)
    data_p.write_bytes(data_p.read_bytes() + b"x")
    assert sh.shard_status(tmp_path, spec) == "corrupt"


def test_shard_must_cover_ids_exactly(tmp_path):
    with pytest.raises(ValueError):
        sh.write_shard(tmp_path, sh.ShardSpec(0, 3), [rec(0), rec(1), rec(1)], 1)


def test_plan_shards_aligned_and_covering():
    specs = sh.plan_shards(15, 42, 10)
    assert [s.start for s in specs] == [10, 20, 30, 40]


def test_boundary_search_skips_null_ids():
    # time == id * 10, except ids 50..54 are null
    items = {i: {"id": i, "time": i * 10} for i in range(1, 200) if not 50 <= i <= 54}

    async def fetch(i):
        return await fetch_item(FakeClient(items), "https://x", i, sleep=no_sleep)

    assert (
        run(first_id_at_or_after(fetch, 520, 1, 199)) == 50
    )  # nulls 50..54 resolve forward to 55 (time 550), so the cut is 50
    assert run(first_id_at_or_after(fetch, 700, 1, 199)) == 70
