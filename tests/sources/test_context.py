import asyncio
import json

import httpx

from atlas.sources.context import fetch_context

B = 9_000_000_000


class FakeClient:
    def __init__(self, items):
        self.items = items

    async def get(self, url):
        i = int(url.rsplit("/", 1)[1].split(".")[0])
        return httpx.Response(200, content=json.dumps(self.items.get(i)).encode())


async def _no_sleep(_):
    return None


def _patch_sleep(monkeypatch):
    monkeypatch.setattr("atlas.sources.context._SLEEP", _no_sleep)


def _items():
    return {
        B + 99: {
            "id": B + 99,
            "type": "comment",
            "parent": B + 50,
            "time": 1,
            "text": "synthetic old comment",
        },
        B + 50: {
            "id": B + 50,
            "type": "story",
            "time": 0,
            "title": "Synthetic old story",
            "descendants": 3,
        },
    }


def test_walks_up_until_root_and_records_states(tmp_path, monkeypatch):
    _patch_sleep(monkeypatch)
    out = asyncio.run(
        fetch_context(FakeClient(_items()), "https://x", {B + 99}, tmp_path, 4)
    )
    assert out["fetched"] == 2 and out["rounds"] == 2
    lines = [
        json.loads(line)
        for line in (tmp_path / "context.jsonl").read_text().splitlines()
    ]
    assert {r["id"] for r in lines} == {B + 50, B + 99}


def test_resume_fetches_nothing_when_done(tmp_path, monkeypatch):
    _patch_sleep(monkeypatch)
    client = FakeClient(_items())
    asyncio.run(fetch_context(client, "https://x", {B + 99}, tmp_path, 4))
    out = asyncio.run(fetch_context(client, "https://x", {B + 99}, tmp_path, 4))
    assert out == {"fetched": 0, "rounds": 0, "failed": 0}
    lines = (tmp_path / "context.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_known_ids_are_not_fetched(tmp_path, monkeypatch):
    _patch_sleep(monkeypatch)
    items = _items()
    client = FakeClient(items)
    out = asyncio.run(
        fetch_context(
            client, "https://x", {B + 99}, tmp_path, 4, known=range(B + 40, B + 60)
        )
    )
    assert out["fetched"] == 1 and out["rounds"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "context.jsonl").read_text().splitlines()
    ]
    assert {r["id"] for r in rows} == {B + 99}


def test_null_parent_is_recorded_and_stops_the_walk(tmp_path, monkeypatch):
    _patch_sleep(monkeypatch)
    items = _items()
    del items[B + 50]  # parent fetch returns JSON null -> state "null"
    out = asyncio.run(fetch_context(FakeClient(items), "https://x", {B + 99}, tmp_path, 4))
    assert out["fetched"] == 2 and out["failed"] == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "context.jsonl").read_text().splitlines()
    ]
    assert {r["id"]: r["state"] for r in rows} == {B + 99: "ok", B + 50: "null"}


def test_failed_fetches_are_counted(tmp_path, monkeypatch):
    _patch_sleep(monkeypatch)

    class Down(FakeClient):
        async def get(self, url):
            return httpx.Response(404)

    out = asyncio.run(
        fetch_context(Down({}), "https://x", {B + 99}, tmp_path, 4)
    )
    assert out == {"fetched": 1, "rounds": 1, "failed": 1}
