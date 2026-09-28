"""Claims ledger check: recompute every published number with DuckDB and flag
drift beyond each claim's tolerance before it reaches public material."""

from __future__ import annotations

from pathlib import Path

REQUIRED = (
    "id",
    "text",
    "value",
    "tolerance",
    "sql",
    "run_id",
    "lane",
    "denominator",
    "question_set",
    "weighted",
    "ci_low",
    "ci_high",
    "qualifier",
)
LANES = ("breadth", "discovery")


def load_claims(path: Path) -> list[dict]:
    import yaml

    data = yaml.safe_load(path.read_text())
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(  # noqa: TRY004 - claims.yaml shape is a data error
            f"{path}: expected a list of claims"
        )
    return data


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate(claim: dict, seen_ids: set) -> str | None:
    missing = [k for k in REQUIRED if k not in claim]
    if missing:
        return "missing: " + ", ".join(sorted(missing))
    if claim["id"] in seen_ids:
        return "duplicate id"
    seen_ids.add(claim["id"])
    if claim["lane"] not in LANES:
        return f"unknown lane: {claim['lane']}"
    if not isinstance(claim["weighted"], bool):
        return "weighted must be a bool"
    if not _numeric(claim["value"]) or not _numeric(claim["tolerance"]):
        return "value and tolerance must be numeric"
    if claim["tolerance"] < 0:
        return "tolerance must be >= 0"
    is_count = isinstance(claim["value"], int) and not isinstance(
        claim["value"], bool
    )
    if not is_count and (claim["ci_low"] is None or claim["ci_high"] is None):
        return "ci_low and ci_high are required for non-count claims"
    is_proportion = isinstance(claim["value"], float) and 0 <= claim["value"] <= 1
    if (
        claim["lane"] == "breadth"
        and is_proportion
        and claim["weighted"] is False
        and "unweighted count" not in str(claim["denominator"]).lower()
    ):
        return (
            "unweighted breadth proportion: "
            "denominator must say 'unweighted count'"
        )
    return None


def check_claims(claims: list[dict], root: Path) -> dict[str, dict]:
    import duckdb

    con = duckdb.connect()
    results = {}
    seen_ids: set = set()
    for index, claim in enumerate(claims):
        key = claim.get("id") or f"#{index}"
        result = {
            "ok": False,
            "expected": claim.get("value"),
            "actual": None,
            "error": None,
        }
        error = _validate(claim, seen_ids)
        if error is not None:
            result["error"] = error
            results[key] = result
            continue
        try:
            rows = con.execute(claim["sql"].replace("{root}", str(root))).fetchall()
        except Exception as exc:  # noqa: BLE001 - surfaced as claim error
            result["error"] = f"{type(exc).__name__}: {exc}"
            results[key] = result
            continue
        if len(rows) != 1 or len(rows[0]) != 1:
            result["error"] = "expected a single scalar"
        elif rows[0][0] is None:
            result["error"] = "query returned null"
        else:
            actual = float(rows[0][0])
            result["actual"] = actual
            result["ok"] = abs(actual - claim["value"]) <= claim["tolerance"]
        results[key] = result
    return results
