"""Replay a restored release with no network: verify it, recompute every claim,
and build the site data directory the static site reads.

Claims run against the release directory (`{root}` is the release). A claim that
reads files from the full bundle fails on a site-only restore; restore the full
bundle to replay it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from atlas.publication.bundles import _meta_mode, verify_release


def _claims(release_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    from atlas.publication.claims import check_claims, load_claims

    path = release_dir / "claims" / "claims.yaml"
    if not path.is_file():
        return {}, {}
    results = check_claims(load_claims(path), release_dir)
    verdicts, errors = {}, {}
    for cid, r in results.items():
        verdicts[cid] = "pass" if r["ok"] else "fail"
        if not r["ok"]:
            errors[cid] = r["error"] or (
                f"actual {r['actual']} vs expected {r['expected']}"
            )
    return verdicts, errors


def _site_data(release_dir: Path, out: Path) -> list[str]:
    """Copy the release's site tables into `out`; return problems (empty if ok)."""
    from atlas.publication.allowlist import text_gate
    from atlas.sitedata.tables import SITE_TABLES

    src = release_dir / "site"
    absent = [n for n in sorted(SITE_TABLES) if not (src / f"{n}.parquet").is_file()]
    if absent:
        return ["site tables missing: " + ", ".join(absent)]
    if _meta_mode(src) != "real":
        return ["site tables need meta.mode == real"]
    out.mkdir(parents=True, exist_ok=True)
    for n in sorted(SITE_TABLES):
        shutil.copy2(src / f"{n}.parquet", out / f"{n}.parquet")
    return text_gate(out)


def replay(release_dir: Path, site_out: Path | None = None) -> dict:
    """Verify, check claims, build site data. Never touches the network."""
    release_dir = Path(release_dir)
    out = (
        Path(site_out)
        if site_out
        else release_dir.with_name(f"{release_dir.name}-site-data")
    )
    report = {
        "ok": False,
        "release": release_dir.name,
        "verify": verify_release(release_dir),
        "claims": {},
        "claim_errors": {},
        "site_data": None,
        "site_problems": [],
    }
    if not report["verify"]["ok"]:
        return report
    report["claims"], report["claim_errors"] = _claims(release_dir)
    report["site_problems"] = _site_data(release_dir, out)
    if not report["site_problems"]:
        report["site_data"] = str(out)
    report["ok"] = not report["claim_errors"] and not report["site_problems"]
    return report
