"""Rehydrate comment text from the official HN API and compare it to the release.

A release carries `text_sha256` per comment, never text. Rehydrate refetches each
item, normalizes it the way the snapshot did (`html_to_text`), and classifies it as
`match`, `changed` (edited since), `missing` (null, deleted, or dead), or `failed`
(the fetch itself failed). Text is written only to data/rehydrated/ (gitignored),
never into a release or export.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

API_BASE = "https://hacker-news.firebaseio.com/v0"
USER_AGENT = "jev-opportunity-atlas/0.1 (research; github.com/hanselhansel)"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def rehydrate(
    expected: dict[int, str],
    transport=None,
    concurrency: int = 32,
    api_base: str = API_BASE,
    normalize=None,
    max_attempts: int = 6,
) -> dict:
    """Fetch every id in `expected` ({id: text_sha256}) and compare hashes."""
    import httpx

    from atlas.sources.hn_api import fetch_item, make_client

    if normalize is None:
        from atlas.sources.htmltext import html_to_text as normalize
    if transport is None:
        client = make_client(concurrency, 30.0)
    else:
        client = httpx.AsyncClient(
            transport=transport, timeout=30.0, headers={"User-Agent": USER_AGENT}
        )
    queue: asyncio.Queue[int] = asyncio.Queue()
    for item_id in expected:
        queue.put_nowait(item_id)
    texts: dict[int, str] = {}
    status: dict[int, str] = {}

    async def worker() -> None:
        while True:
            try:
                item_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            rec = await fetch_item(client, api_base, item_id, max_attempts=max_attempts)
            if rec.state == "failed":
                status[item_id] = "failed"
            elif rec.state != "ok":
                status[item_id] = "missing"
            else:
                text = normalize(rec.item.get("text"))
                texts[item_id] = text
                same = _sha256(text) == expected[item_id]
                status[item_id] = "match" if same else "changed"

    async with client:
        await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    order = list(expected)
    return {
        "texts": {i: texts[i] for i in order if i in texts},
        "status": {i: status[i] for i in order},
        "summary": dict(Counter(status[i] for i in order)),
    }


def _expected_from_release(release_dir: Path) -> tuple[dict[int, str], str]:
    import pyarrow.parquet as pq

    for rel, id_col in (
        ("snapshot/comments_public.parquet", "id"),
        ("site/evidence.parquet", "comment_id"),
    ):
        p = release_dir / rel
        if p.is_file():
            t = pq.read_table(p, columns=[id_col, "text_sha256"]).to_pydict()
            pairs = sorted(
                (int(i), s)
                for i, s in zip(t[id_col], t["text_sha256"])
                if i is not None and s
            )
            return dict(pairs), rel
    raise FileNotFoundError(
        f"{release_dir} has neither snapshot/comments_public.parquet "
        "nor site/evidence.parquet"
    )


def rehydrate_release(
    release_dir: Path,
    out_root: Path,
    limit: int | None = None,
    transport=None,
    api_base: str = API_BASE,
    concurrency: int = 32,
) -> dict:
    """Rehydrate a restored release into <out_root>/<release name>/.

    Writes texts.parquet (id, status, text) and summary.json. Refuses an output
    location inside the release or under exports/.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from atlas import paths

    release_dir, out_root = Path(release_dir).resolve(), Path(out_root).resolve()
    for forbidden in (release_dir, Path(paths.EXPORTS).resolve()):
        if out_root == forbidden or forbidden in out_root.parents:
            raise ValueError(f"rehydrated text must not be written under {forbidden}")
    expected, source = _expected_from_release(release_dir)
    if limit is not None:
        expected = dict(list(expected.items())[:limit])
    result = asyncio.run(
        rehydrate(
            expected, transport=transport, concurrency=concurrency, api_base=api_base
        )
    )
    out = out_root / release_dir.name
    out.mkdir(parents=True, exist_ok=True)
    ids = list(expected)
    pq.write_table(
        pa.table(
            {
                "id": pa.array(ids, pa.int64()),
                "status": pa.array([result["status"][i] for i in ids], pa.string()),
                "text": pa.array([result["texts"].get(i) for i in ids], pa.string()),
            }
        ),
        out / "texts.parquet",
        compression="zstd",
    )
    n = len(ids)
    not_matching = n - result["summary"].get("match", 0)
    summary = {
        "release": release_dir.name,
        "source": source,
        "n": n,
        "summary": result["summary"],
        "no_longer_matching_share": round(not_matching / n, 6) if n else 0.0,
        "out_dir": str(out),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
