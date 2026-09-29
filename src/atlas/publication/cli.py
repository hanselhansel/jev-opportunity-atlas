"""`atlas release ...` and `atlas claims check`.

Staging builds exports/<release> locally through the allowlist, the text gate,
and the secret scan; check re-verifies a staged release in place; pack writes the
site and full bundles for a manual, reviewed `gh release create`. Restore
downloads a published release over plain HTTPS. Nothing here uploads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _default_snapshot_id() -> str:
    import tomllib

    from atlas import paths

    cfg = tomllib.loads((paths.CONFIGS / "acquisition.toml").read_text())
    return cfg["snapshot_id"]


def _release_stage(args) -> None:
    from atlas import paths
    from atlas.publication.export import ExportError, stage_release

    snapshot = args.snapshot if args.snapshot else _default_snapshot_id()
    try:
        release_dir = stage_release(paths.ROOT, args.release, snapshot, args.run)
    except ExportError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    manifest = json.loads((release_dir / "release_manifest.json").read_text())
    print(
        json.dumps(
            {
                "release_dir": str(release_dir),
                "file_count": manifest["file_count"],
            }
        )
    )


def _release_check(args) -> None:
    from atlas import paths
    from atlas.publication.allowlist import scan_release, text_gate
    from atlas.publication.export import verify_release

    d = paths.EXPORTS / args.release
    if not d.is_dir():
        print(
            f"release {args.release} not found under {paths.EXPORTS}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    verify = verify_release(d)
    gate = text_gate(d)
    secrets = [str(f) for f in scan_release(d)]
    gitleaks = "not installed"
    if shutil.which("gitleaks"):
        cmd = [
            "gitleaks",
            "dir",
            str(d),
            "--redact",
            "--no-banner",
            "--log-level",
            "warn",
        ]
        cfg = paths.ROOT / ".gitleaks.toml"
        if cfg.exists():
            cmd += ["--config", str(cfg)]
        proc = subprocess.run(cmd, capture_output=True, check=False)
        gitleaks = "ok" if proc.returncode == 0 else "failed"
    report = {
        "verify": verify,
        "text_gate": gate,
        "secrets": secrets,
        "gitleaks": gitleaks,
    }
    print(json.dumps(report, indent=2))
    if not verify["ok"] or gate or secrets or gitleaks == "failed":
        raise SystemExit(1)


def _release_pack(args) -> None:
    from atlas import paths
    from atlas.publication.restore import ReleaseError, add_site_tables, pack_release

    release_dir = paths.EXPORTS / args.release
    out = Path(args.out) if args.out else paths.EXPORTS / f"{args.release}-assets"
    try:
        if args.site_data:
            add_site_tables(release_dir, Path(args.site_data))
        index = pack_release(release_dir, out, limit=args.chunk_limit)
    except ReleaseError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps({"assets_dir": str(out), **index}, indent=2))
    print(
        f"upload (manual, reviewed): gh release create {args.release} {out}/*",
        file=sys.stderr,
    )


def _release_restore(args) -> None:
    from atlas import paths
    from atlas.publication.restore import ReleaseError, restore

    dest = Path(args.dest) if args.dest else paths.DATA / "releases"
    try:
        report = restore(
            args.release,
            dest,
            bundles=tuple(args.bundle or ["site"]),
            repo=args.repo,
            use_gh=args.gh,
        )
    except ReleaseError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(report, indent=2))


def _release_rehydrate(args) -> None:
    from atlas import paths
    from atlas.publication.rehydrate import rehydrate_release

    summary = rehydrate_release(
        Path(args.release_dir),
        paths.DATA / "rehydrated",
        limit=args.limit,
        concurrency=args.concurrency,
    )
    print(json.dumps(summary, indent=2))


def _release_replay(args) -> None:
    from atlas.publication.replay import replay

    report = replay(
        Path(args.release_dir), Path(args.site_out) if args.site_out else None
    )
    v = report["verify"]
    if v["ok"]:
        print(f"verify: ok (schema_version {v['schema_version']})")
    else:
        print(
            f"verify: FAIL bad={v['bad']} missing={v['missing']} "
            f"extra={v['extra']} schema_version={v['schema_version']}"
        )
    for cid, verdict in report["claims"].items():
        detail = report["claim_errors"].get(cid)
        print(f"claim {cid}: {verdict}" + (f" ({detail})" if detail else ""))
    if v["ok"]:
        print(f"claims: {len(report['claims'])} checked")
    for problem in report["site_problems"]:
        print(f"site data: {problem}")
    if report["site_data"]:
        print(f"site data: {report['site_data']}")
    print("replay: ok" if report["ok"] else "replay: FAIL")
    if not report["ok"]:
        raise SystemExit(1)


def _claims_check(args) -> None:
    from atlas import paths
    from atlas.publication.claims import check_claims, load_claims

    path = (
        Path(args.file)
        if args.file
        else paths.ROOT / "claims" / "claims.yaml"
    )
    results = check_claims(load_claims(path), paths.ROOT)
    failed = False
    for cid, result in results.items():
        if result["ok"]:
            print(f"ok {cid}")
        else:
            failed = True
            detail = result["error"] or (
                f"actual {result['actual']} vs expected {result['expected']}"
            )
            print(f"FAIL {cid}: {detail}")
    if failed:
        raise SystemExit(1)


def register(sub) -> None:
    release = sub.add_parser(
        "release", help="Stage and verify a public release export"
    )
    rsub = release.add_subparsers(dest="release_cmd", required=True)
    stage = rsub.add_parser(
        "stage", help="Build exports/<release> through the gates"
    )
    stage.add_argument("--release", required=True, help="Release tag")
    stage.add_argument(
        "--snapshot",
        default=None,
        help="Snapshot id (default: snapshot_id in configs/acquisition.toml)",
    )
    stage.add_argument(
        "--run", action="append", default=[], help="Run id (repeatable)"
    )
    stage.set_defaults(func=_release_stage)
    check = rsub.add_parser(
        "check", help="Re-verify a staged release in place"
    )
    check.add_argument("--release", required=True, help="Release tag")
    check.set_defaults(func=_release_check)
    pack = rsub.add_parser(
        "pack", help="Write site and full bundles plus assets-<tag>.json"
    )
    pack.add_argument("--release", required=True, help="Release tag")
    pack.add_argument(
        "--site-data", default=None, help="Real site tables to add first"
    )
    pack.add_argument(
        "--out", default=None, help="Assets dir (default: exports/<tag>-assets)"
    )
    pack.add_argument("--chunk-limit", type=int, default=1_900_000_000)
    pack.set_defaults(func=_release_pack)
    rest = rsub.add_parser(
        "restore", help="Download, verify, and unpack a published release"
    )
    rest.add_argument("--release", required=True, help="Release tag")
    rest.add_argument("--repo", default="hanselhansel/jev-opportunity-atlas")
    rest.add_argument(
        "--dest", default=None, help="Parent dir (default: data/releases)"
    )
    rest.add_argument(
        "--bundle",
        action="append",
        choices=("site", "full"),
        help="Bundle to restore (repeatable; default: site)",
    )
    rest.add_argument(
        "--gh", action="store_true", help="Download with gh instead of HTTPS"
    )
    rest.set_defaults(func=_release_restore)
    rehy = rsub.add_parser(
        "rehydrate",
        help="Refetch comment text from the HN API into data/rehydrated/",
    )
    rehy.add_argument("--release-dir", required=True, help="Restored release dir")
    rehy.add_argument("--limit", type=int, default=None, help="First N ids only")
    rehy.add_argument("--concurrency", type=int, default=32)
    rehy.set_defaults(func=_release_rehydrate)
    rep = rsub.add_parser(
        "replay", help="Verify, check claims, and build site data (no network)"
    )
    rep.add_argument("--release-dir", required=True, help="Restored release dir")
    rep.add_argument(
        "--site-out", default=None, help="Site data dir (default: <dir>-site-data)"
    )
    rep.set_defaults(func=_release_replay)

    claims = sub.add_parser("claims", help="Claims ledger")
    csub = claims.add_subparsers(dest="claims_cmd", required=True)
    ccheck = csub.add_parser(
        "check", help="Recompute every claim with DuckDB"
    )
    ccheck.add_argument(
        "--file", default=None, help="Claims file (default: claims/claims.yaml)"
    )
    ccheck.set_defaults(func=_claims_check)
