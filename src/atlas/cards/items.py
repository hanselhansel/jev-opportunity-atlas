"""Build the cards item table from a facets run (L23, main-run port).

`build_items` joins facets answers (question set `facets@2`) with the
two-phase facet sample and the snapshot's sentence lists: one row per
firsthand account, carrying the chosen pain sentence plus phase/half/weight
for downstream weighting. `draft_sample` draws the seeded PPS explore-half
sample the card-drafting step reads.
"""

from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.cards.engine.assign import read_answers
from atlas.sources.items import load_items

FACETS_LABEL = "facets@2"
LOAD_CHUNK = 5000
PAIN_CAP = 300

# The columns `cards assign --items` reads come first; domain/severity ride
# along so `cards draft-sample` can write the drafting TSV without re-reading
# the facet answers.
ITEMS_SCHEMA = pa.schema(
    [
        ("comment_id", pa.int64()),
        ("pain_sentence", pa.string()),
        ("sentences", pa.list_(pa.string())),
        ("domain", pa.string()),
        ("severity", pa.float64()),
    ]
)
ITEMS_COLUMNS = [f.name for f in ITEMS_SCHEMA]


@dataclass
class ItemsResult:
    rows: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __iter__(self):
        # `rows, meta = build_items(...)` unpacks like a tuple.
        return iter((self.rows, self.meta))


def _sentences_of(item) -> list:
    sents = item["sentences"] if isinstance(item, dict) else item.sentences
    return list(sents or [])


def _pain_index(choice) -> int:
    """`s<k>` -> k; anything else (missing, malformed) -> -1."""
    if isinstance(choice, str) and choice.startswith("s") and choice[1:].isdigit():
        return int(choice[1:])
    return -1


def _meta_counts(answers, sample, account_types) -> dict:
    """Per-phase account_type counts over answered sample rows (the reference
    diagnostic loop), plus kept/dropped bookkeeping filled by the caller."""
    counts: dict[str, collections.Counter] = {
        "pos": collections.Counter(),
        "neg": collections.Counter(),
    }
    answered_in_sample = 0
    for cid, a in answers.items():
        s = sample.get(cid)
        if s is None:
            continue
        answered_in_sample += 1
        phase = s.get("phase")
        at = (a.get("account_type") or {}).get("choice")
        counts.setdefault(str(phase), collections.Counter())[str(at)] += 1
    return {
        "answered_in_sample": answered_in_sample,
        "counts": {
            phase: dict(c) for phase, c in sorted(counts.items()) if c
        },
        "account_types": list(account_types),
    }


def build_items(
    facets_run,
    sample_id,
    snapshot_id,
    account_types=("firsthand_account",),
    label=FACETS_LABEL,
) -> ItemsResult:
    """One items row per sampled comment whose account_type answer is in
    `account_types` and whose pain_sentence choice resolves to a sentence.

    Rows carry comment_id, pain_sentence, sentences, phase, half, weight,
    domain, severity. Comments missing from the sample are skipped; a missing
    or out-of-range pain_sentence choice drops the row into
    meta["dropped_missing_pain"].
    """
    sample = {
        r["comment_id"]: r
        for r in pq.read_table(paths.sample_path(sample_id)).to_pylist()
    }
    answers = read_answers(paths.run_dir(facets_run), label)
    meta = _meta_counts(answers, sample, account_types)
    meta.update(
        {
            "facets_run": facets_run,
            "sample": sample_id,
            "snapshot": snapshot_id,
            "label": label,
        }
    )

    wanted = set(account_types)
    keep = [
        cid
        for cid, a in answers.items()
        if cid in sample
        and (a.get("account_type") or {}).get("choice") in wanted
    ]
    keep.sort()

    snap_dir = paths.snapshot_dir(snapshot_id)
    rows: list[dict] = []
    dropped = 0
    for i in range(0, len(keep), LOAD_CHUNK):
        for item in load_items(snap_dir, keep[i : i + LOAD_CHUNK]):
            cid = item["comment_id"]
            sents = _sentences_of(item)
            a = answers[cid]
            k = _pain_index((a.get("pain_sentence") or {}).get("choice"))
            if not (0 <= k < len(sents)):
                dropped += 1
                continue
            s = sample[cid]
            rows.append(
                {
                    "comment_id": cid,
                    "pain_sentence": sents[k],
                    "sentences": sents,
                    "phase": s.get("phase"),
                    "half": s.get("half"),
                    "weight": s.get("weight"),
                    "domain": (a.get("domain") or {}).get("choice"),
                    "severity": (a.get("severity") or {}).get("score"),
                }
            )
    meta["kept"] = len(rows)
    meta["dropped_missing_pain"] = dropped
    return ItemsResult(rows=rows, meta=meta)


def items_table(rows) -> pa.Table:
    """The assign-consumable items table: ITEMS_COLUMNS only."""
    return pa.Table.from_pylist(
        [{k: r.get(k) for k in ITEMS_COLUMNS} for r in rows],
        schema=ITEMS_SCHEMA,
    )


def write_items(rows, out) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(items_table(rows), str(out))
    return out


def draft_sample(items, n, seed, half="explore", phase="pos") -> list[dict]:
    """PPS-without-replacement draw over the phase/half pool, in comment_id
    order, identical to the scratch script:
    np.random.default_rng(seed).choice(len(pool), n, replace=False, p=w/w.sum()).
    """
    pool = [
        r for r in items if r.get("phase") == phase and r.get("half") == half
    ]
    pool.sort(key=lambda r: r["comment_id"])
    if not pool:
        raise ValueError(f"empty draft pool for phase={phase!r} half={half!r}")
    if n > len(pool):
        raise ValueError(
            f"--n {n} exceeds the {phase}/{half} pool of {len(pool)}"
        )
    w = np.array([r["weight"] for r in pool], dtype=float)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(pool), n, replace=False, p=w / w.sum())
    return [pool[int(j)] for j in sorted(pick)]


def draft_tsv_lines(rows) -> list[str]:
    """One TSV line per picked row: comment_id, domain, severity, pain text
    (whitespace-normalized, capped at PAIN_CAP chars)."""
    lines = []
    for r in rows:
        pain = " ".join(str(r["pain_sentence"]).split())[:PAIN_CAP]
        sev = r.get("severity")
        sev_s = "" if sev is None else str(round(sev, 2))
        dom = r.get("domain") or ""
        lines.append(f"{r['comment_id']}\t{dom}\t{sev_s}\t{pain}")
    return lines


def write_draft_tsv(rows, out) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(line + "\n" for line in draft_tsv_lines(rows)),
        encoding="utf-8",
    )
    return out


def write_meta(meta: dict, out) -> Path:
    meta_path = Path(out).with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps(meta, indent=1) + "\n", encoding="utf-8"
    )
    return meta_path
