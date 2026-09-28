"""Label queue construction.

Queues are JSON files under ``paths.LABELS / "queues"``. A banded queue draws
from score strata so calibration sees high, mid, and low Jev scores; the display
order is shuffled so bands can never be inferred from position. Repeats are a
seeded share of ids re-shown at the end for intra-rater agreement.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas import paths

DEFAULT_BANDS = {"high": (0.5, 1.01), "mid": (0.15, 0.5), "low": (0.0, 0.15)}
DEFAULT_BAND_SIZES = {"high": 60, "mid": 50, "low": 40}


def _ints(values) -> list[int]:
    return [int(v) for v in values]


def build_queue(
    frame: pa.Table,
    n: int | None,
    seed: int,
    exclude=frozenset(),
    bands: dict[str, tuple[float, float]] | None = None,
    band_sizes: dict[str, int] | None = None,
    repeat_share: float = 0.10,
) -> dict:
    """Returns {"ids", "repeats", "bands", "rates", "seed"}.

    ``frame`` has ``comment_id`` and, when ``bands`` is used, a ``score`` column.
    ``bands`` maps name -> (lo, hi) half-open score ranges; ``band_sizes`` maps
    name -> draw size (capped at the band's member count). ``rates[name]`` is
    drawn / members, where members are counted after ``exclude`` is applied.
    """
    rng = np.random.default_rng(seed)
    candidates = sorted(
        c for c in frame.column("comment_id").to_pylist() if c not in exclude
    )
    band_info: dict[str, dict] = {}
    rates: dict[str, float] = {}
    if bands is None:
        if n is None:
            raise ValueError("n is required when bands is None")
        if n > len(candidates):
            raise ValueError(f"n={n} exceeds {len(candidates)} candidates")
        ids = _ints(rng.choice(candidates, size=n, replace=False))
    else:
        if not band_sizes:
            raise ValueError("band_sizes is required when bands is given")
        scores = dict(
            zip(
                frame.column("comment_id").to_pylist(),
                frame.column("score").to_pylist(),
                strict=True,
            )
        )
        drawn: list[int] = []
        for name, (lo, hi) in bands.items():
            members = sorted(c for c in candidates if lo <= scores[c] < hi)
            k = min(band_sizes[name], len(members))
            picked = _ints(rng.choice(members, size=k, replace=False)) if k else []
            band_info[name] = {"lo": lo, "hi": hi, "count": len(members), "ids": picked}
            rates[name] = k / len(members) if members else 0.0
            drawn.extend(picked)
        ids = _ints(rng.permutation(drawn)) if drawn else []
    n_repeats = round(len(ids) * repeat_share)
    repeats = _ints(rng.choice(ids, size=n_repeats, replace=False)) if n_repeats else []
    return {"ids": ids, "repeats": repeats, "bands": band_info, "rates": rates, "seed": seed}


def domain_subset(ids: list[int], seed: int, n: int = 50) -> list[int]:
    """Seeded subset of queue ids that also get a ``domain`` radio (A6)."""
    if not ids:
        return []
    rng = np.random.default_rng(seed + 1)
    return _ints(rng.choice(list(ids), size=min(n, len(ids)), replace=False))


def _allocate(n: int, weights: list[int]) -> list[int]:
    """Largest-remainder split of ``n`` proportional to ``weights``; ties by order."""
    total = sum(weights)
    if total <= 0:
        base, rem = divmod(n, len(weights))
        return [base + (1 if i < rem else 0) for i in range(len(weights))]
    raw = [n * w / total for w in weights]
    floors = [int(x) for x in raw]
    rem = n - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:rem]:
        floors[i] += 1
    return floors


def top_up(
    queue: dict,
    frame: pa.Table,
    n: int,
    bands: tuple[str, ...] = ("high", "mid"),
    repeat_share: float = 0.10,
) -> dict:
    """Draw ``n`` more ids from the named bands. Returns a new queue dict."""
    out = copy.deepcopy(queue)
    seed = queue["seed"] + 1000 * (len(queue.get("top_ups", [])) + 1)
    rng = np.random.default_rng(seed)
    scores = dict(
        zip(
            frame.column("comment_id").to_pylist(),
            frame.column("score").to_pylist(),
            strict=True,
        )
    )
    have = set(queue["ids"])
    weights = [len(queue["bands"][b]["ids"]) for b in bands]
    draws: list[int] = []
    for band, want in zip(bands, _allocate(n, weights), strict=True):
        info = queue["bands"][band]
        members = sorted(
            c
            for c in scores
            if info["lo"] <= scores[c] < info["hi"] and c not in have
        )
        k = min(want, len(members))
        picked = _ints(rng.choice(members, size=k, replace=False)) if k else []
        out["bands"][band]["ids"].extend(picked)
        count = out["bands"][band]["count"]
        out["rates"][band] = len(out["bands"][band]["ids"]) / count if count else 0.0
        draws.extend(picked)
    new_ids = _ints(rng.permutation(draws)) if draws else []
    out["ids"].extend(new_ids)
    n_repeats = round(len(new_ids) * repeat_share)
    if n_repeats and new_ids:
        out["repeats"].extend(
            _ints(rng.choice(new_ids, size=n_repeats, replace=False))
        )
    out.setdefault("top_ups", []).append({"n": n, "seed": seed, "ids": new_ids})
    return out


def sequence(queue: dict) -> list[tuple[int, bool]]:
    """Display order: primary views first, then repeat views (True = repeat)."""
    return [(cid, False) for cid in queue["ids"]] + [
        (cid, True) for cid in queue["repeats"]
    ]


def queue_path(label_set: str) -> Path:
    return paths.LABELS / "queues" / f"{label_set}.json"


def save_queue(queue: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")


def load_queue(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_answers(run_id: str, question_id: str) -> dict[int, dict]:
    """{comment_id: {"noul": float|None, "choice": str|None}} for one question.

    Reads every ``answers/part-*.parquet`` under the run directory; later rows
    win. Empty dict when the directory is missing.
    """
    directory = paths.run_dir(run_id) / "answers"
    out: dict[int, dict] = {}
    if not directory.is_dir():
        return out
    for file in sorted(directory.glob("*.parquet")):
        table = pq.read_table(
            file, columns=["comment_id", "question_id", "noul", "choice"]
        )
        table = table.filter(pc.equal(table.column("question_id"), question_id))
        for cid, noul, choice in zip(
            table.column("comment_id").to_pylist(),
            table.column("noul").to_pylist(),
            table.column("choice").to_pylist(),
            strict=True,
        ):
            out[cid] = {"noul": noul, "choice": choice}
    return out


def labeling_frame(
    sample_id: str, run_id: str, question_id: str = "firsthand_problem"
) -> pa.Table:
    """comment_id / score / weight rows for sampled comments with a noul answer."""
    sample = pq.read_table(paths.sample_path(sample_id), columns=["comment_id", "weight"])
    answers = read_answers(run_id, question_id)
    comment_ids: list[int] = []
    scores: list[float] = []
    weights: list[float] = []
    for cid, weight in zip(
        sample.column("comment_id").to_pylist(),
        sample.column("weight").to_pylist(),
        strict=True,
    ):
        answer = answers.get(cid)
        if answer is None or answer["noul"] is None:
            continue
        comment_ids.append(cid)
        scores.append(answer["noul"])
        weights.append(weight)
    return pa.table(
        {
            "comment_id": pa.array(comment_ids, pa.int64()),
            "score": pa.array(scores, pa.float64()),
            "weight": pa.array(weights, pa.float64()),
        }
    )
