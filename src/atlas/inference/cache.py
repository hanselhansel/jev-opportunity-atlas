"""SQLite response cache keyed by canonical request content.

`put` uses INSERT OR IGNORE: the first answer wins and is never overwritten, so a
cache hit replays the original response together with its provenance (run_id,
logical_call_id, request_id, input_tokens).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from atlas.inference.questions import canonical_json

SCHEMA = """CREATE TABLE IF NOT EXISTS cache(
    key TEXT PRIMARY KEY,
    response TEXT,
    run_id TEXT,
    logical_call_id TEXT,
    request_id TEXT,
    input_tokens INTEGER,
    created_at TEXT
)"""


def cache_key(state: dict, questions: dict, question_set: str, model: str) -> str:
    blob = canonical_json(
        {
            "state": state,
            "questions": questions,
            "question_set": question_set,
            "model": model,
        }
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(SCHEMA)
        self._db.commit()

    def put(
        self,
        key: str,
        response: dict,
        run_id: str,
        logical_call_id: str,
        request_id: str | None,
        input_tokens: int | None,
    ) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO cache"
            "(key, response, run_id, logical_call_id, request_id, input_tokens, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                json.dumps(response, ensure_ascii=False),
                run_id,
                logical_call_id,
                request_id,
                input_tokens,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._db.commit()

    def get(self, key: str) -> dict | None:
        row = self._db.execute(
            "SELECT response, run_id, logical_call_id, request_id, input_tokens,"
            " created_at FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "response": json.loads(row[0]),
            "run_id": row[1],
            "logical_call_id": row[2],
            "request_id": row[3],
            "input_tokens": row[4],
            "created_at": row[5],
        }

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
