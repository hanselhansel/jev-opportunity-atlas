"""Release allowlist and content gates: text gate plus the staged secret scan.

Problems and findings name files, columns, keys, and line numbers only; they never
carry cell or value content, so they are safe to print anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas.publication.secret_scan import Finding, scan_text

# Snapshot exports keep ids, timestamps, labels, and hashes only; story titles and
# all text_* payload columns are excluded on purpose. None means copy as is.
SNAPSHOT_FILES = {
    "comments.parquet": (
        "id",
        "time",
        "created_at",
        "month",
        "period",
        "story_id",
        "parent_id",
        "depth",
        "thread_type",
        "state",
        "in_window",
        "lang",
        "word_count",
        "eligible",
        "exclusion_reason",
        "text_sha256",
    ),
    "stories.parquet": (
        "id",
        "time",
        "created_at",
        "type",
        "thread_type",
        "state",
        "score",
        "descendants",
        "in_window",
        "url",
    ),
    "coverage.parquet": None,
}

RUN_FILES = (
    "ledger.jsonl",
    "run_manifest.json",
    "answers/*.parquet",
    "eval_*.json",
    "pilot_report.md",
)

# Reproducibility inputs. The taxonomy is deliberately NOT allowlisted.
EXTRA = (
    "manifests/**/*.json",
    "claims/claims.yaml",
    "configs/questions/*.json",
    "configs/rubric*.md",
    "configs/prices.toml",
    "configs/budgets.toml",
)

FORBIDDEN_FIELDS = frozenset(
    {
        "text",
        "text_norm",
        "text_html",
        "title",
        "author",
        "by",
        "sentences",
        "comment",
        "parent",
    }
)

LENGTH_EXEMPT = ("url", "probabilities_json")
MAX_MEDIAN_LEN = 80
LABEL_DROP = ("reviewer",)

_TEXT_GATE_SUFFIXES = (".parquet", ".json", ".jsonl")


def _is_textual(t: pa.DataType) -> bool:
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return True
    if pa.types.is_dictionary(t):
        return pa.types.is_string(t.value_type) or pa.types.is_large_string(
            t.value_type
        )
    if pa.types.is_list(t) or pa.types.is_large_list(t):
        return pa.types.is_string(t.value_type) or pa.types.is_large_string(
            t.value_type
        )
    return False


def _length_exempt(name: str) -> bool:
    return name in LENGTH_EXEMPT or name.endswith(("_sha256", "_hash"))


def _nested_field_names(t: pa.DataType):
    """Field names nested inside a type (struct children, list<struct>, dict)."""
    if pa.types.is_struct(t):
        for f in t:
            yield f.name
            yield from _nested_field_names(f.type)
    elif (
        pa.types.is_list(t)
        or pa.types.is_large_list(t)
        or pa.types.is_dictionary(t)
        or pa.types.is_map(t)
    ):
        yield from _nested_field_names(t.value_type)


def _parquet_field_names(schema: pa.Schema):
    for f in schema:
        yield f.name
        yield from _nested_field_names(f.type)


def _iter_chunks(arr):
    yield from arr.iterchunks() if hasattr(arr, "iterchunks") else iter([arr])


def _decode_string_col(col) -> list[str]:
    """Flatten a string/dict<string>/list<string> column to Python strs."""
    out = []
    for chunk in _iter_chunks(col):
        if pa.types.is_dictionary(chunk.type):
            chunk = chunk.dictionary_decode()
        if pa.types.is_list(chunk.type) or pa.types.is_large_list(chunk.type):
            chunk = chunk.flatten()
        out.extend(v for v in chunk.to_pylist() if v is not None)
    return out


def _json_walk(node, key, key_hits, string_lengths):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in FORBIDDEN_FIELDS:
                key_hits.add(k)
            _json_walk(v, k, key_hits, string_lengths)
    elif isinstance(node, list):
        for item in node:
            _json_walk(item, key, key_hits, string_lengths)
    elif isinstance(node, str):
        string_lengths.setdefault(key, []).append(len(node))


def _gate_parquet(p: Path, rel: str, check_lengths: bool) -> list[str]:
    problems = []
    schema = pq.read_schema(p)
    for name in set(_parquet_field_names(schema)):
        if name in FORBIDDEN_FIELDS:
            problems.append(f"text-gate forbidden-field {rel}:{name}")
    if not check_lengths:
        return problems
    pf = pq.ParquetFile(p)
    for field in schema:
        if not _is_textual(field.type) or _length_exempt(field.name):
            continue
        lengths = []
        for batch in pf.iter_batches(batch_size=65536, columns=[field.name]):
            for chunk in _iter_chunks(batch.column(0)):
                if pa.types.is_dictionary(chunk.type):
                    chunk = chunk.dictionary_decode()
                if pa.types.is_list(chunk.type) or pa.types.is_large_list(
                    chunk.type
                ):
                    chunk = chunk.flatten()
                arr = pc.utf8_length(chunk.drop_null()).to_numpy(
                    zero_copy_only=False
                )
                lengths.append(arr)
        nonempty = [a for a in lengths if a.size]
        if nonempty:
            values = np.concatenate(nonempty)
            if values.size:
                m = float(np.median(values))
                if m > MAX_MEDIAN_LEN:
                    problems.append(
                        f"text-gate long-strings {rel}:{field.name} median={m:g}"
                    )
    return problems


def _gate_json(p: Path, rel: str, check_lengths: bool) -> list[str]:
    key_hits: set[str] = set()
    string_lengths: dict[str, list[int]] = {}
    try:
        if p.suffix == ".jsonl":
            values = [
                json.loads(line)
                for line in p.read_text().splitlines()
                if line.strip()
            ]
        else:
            values = [json.loads(p.read_text())]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [f"text-gate unparseable {rel}"]
    for value in values:
        _json_walk(value, "<root>", key_hits, string_lengths)
    problems = [
        f"text-gate forbidden-field {rel}:{name}" for name in sorted(key_hits)
    ]
    if check_lengths:
        for key, lens in sorted(string_lengths.items()):
            m = float(np.median(np.asarray(lens, dtype=np.float64)))
            if m > MAX_MEDIAN_LEN:
                problems.append(
                    f"text-gate long-strings {rel}:{key} median={m:g}"
                )
    return problems


def text_gate(release_dir: Path) -> list[str]:
    """Block releases that still carry text: forbidden field names anywhere, and
    columns/keys whose median string length looks like free text."""
    problems = []
    for p in sorted(release_dir.rglob("*")):
        if not p.is_file() or p.suffix not in _TEXT_GATE_SUFFIXES:
            continue
        rel = p.relative_to(release_dir).as_posix()
        check_lengths = not rel.startswith("configs/")
        if p.suffix == ".parquet":
            problems.extend(_gate_parquet(p, rel, check_lengths))
        else:
            problems.extend(_gate_json(p, rel, check_lengths))
    return problems


def _scan_parquet(p: Path, rel: str) -> list[Finding]:
    hits = []
    pf = pq.ParquetFile(p)
    schema = pf.schema_arrow
    schema_text = "\n".join(schema.names)
    if schema.metadata:
        schema_text += "\n" + "\n".join(
            f"{k.decode('utf-8', errors='ignore')}={v.decode('utf-8', errors='ignore')}"
            for k, v in schema.metadata.items()
        )
    hits.extend(scan_text(schema_text, f"{rel}#schema"))
    for field in schema:
        if not _is_textual(field.type):
            continue
        row_offset = 0
        for batch in pf.iter_batches(batch_size=65536, columns=[field.name]):
            values = _decode_string_col(batch.column(0))
            path = f"{rel}#{field.name}"
            hits.extend(
                Finding(h.rule, h.path, h.line + row_offset)
                for h in scan_text("\n".join(values), path)
            )
            row_offset += batch.num_rows
    return hits


def scan_release(release_dir: Path) -> list[Finding]:
    """Scan every staged file for secrets, decoding parquet columns and zst."""
    import zstandard

    hits = []
    for p in sorted(release_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(release_dir).as_posix()
        if p.suffix == ".parquet":
            hits.extend(_scan_parquet(p, rel))
        elif p.suffix == ".zst":
            with p.open("rb") as fh:
                reader = zstandard.ZstdDecompressor().stream_reader(fh)
                text = reader.read().decode("utf-8", errors="ignore")
            hits.extend(scan_text(text, rel))
        else:
            text = p.read_bytes().decode("utf-8", errors="ignore")
            hits.extend(scan_text(text, rel))
    return hits
