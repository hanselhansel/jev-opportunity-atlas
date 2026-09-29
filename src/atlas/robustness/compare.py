"""Compare paraphrase runs against the main run.

``compare_screen`` restricts the main screen answers to the robustness
subsample and reports, per paraphrase run: weighted prevalence at the cutoff
with a stratified thread-bootstrap interval (``boot_ratio``), item-level
agreement on the side of the cutoff, Cohen's kappa, and the Spearman
correlation of ``firsthand_p``. ``compare_assign`` reports group and card
agreement (``none`` counts as a value) plus the top-20 card shares under each
run with the max absolute difference. Outputs hold IDs and numbers only.
"""

from __future__ import annotations

import numpy as np
import pyarrow.parquet as pq

from atlas import paths
from atlas.sitedata.build_share import boot_ratio


def _screen_probs(run_id: str) -> dict[int, float]:
    """comment_id -> firsthand_p; builds the by-comment table if absent."""
    run_dir = paths.run_dir(run_id)
    path = run_dir / "screen_by_comment.parquet"
    if not path.exists():
        from atlas.screen.unpack import build_screen_table

        build_screen_table(run_id)
    table = pq.read_table(path, columns=["comment_id", "firsthand_p"])
    return {
        int(r["comment_id"]): float(r["firsthand_p"])
        for r in table.to_pylist()
        if r["firsthand_p"] is not None
    }


def _avg_ranks(x) -> np.ndarray:
    """0..n-1 ranks with ties averaged (Spearman's midrank)."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="stable")
    ranks = np.empty(x.shape[0])
    ranks[order] = np.arange(x.shape[0])
    _uniq, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(counts.shape[0])
    np.add.at(sums, inv, ranks)
    return (sums / counts)[inv]


def _spearman(a, b) -> float | None:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape[0] < 2:
        return None
    ra, rb = _avg_ranks(a), _avg_ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _kappa(a, b) -> float | None:
    """Cohen's kappa over two equal-length label arrays."""
    a, b = np.asarray(a), np.asarray(b)
    if a.shape[0] == 0:
        return None
    labels = np.unique(np.concatenate([a, b]))
    p_o = float((a == b).mean())
    p_e = sum(float((a == l).mean()) * float((b == l).mean()) for l in labels)
    if p_e == 1.0:
        return None
    return float((p_o - p_e) / (1.0 - p_e))


def _prevalence(sub_rows, probs, cutoff, n_boot, seed) -> dict:
    rows = [r for r in sub_rows if r["comment_id"] in probs]
    if not rows:
        return {"n": 0, "prevalence": None, "ci_low": None, "ci_high": None}
    num = np.array(
        [float(probs[r["comment_id"]] >= cutoff) for r in rows]
    )
    w = np.array([r["weight"] for r in rows], dtype=float)
    lo, hi = boot_ratio(
        np.ones(len(rows)),
        num,
        w,
        [r["stratum"] for r in rows],
        [r["story_id"] for r in rows],
        n_boot=n_boot,
        seed=seed,
    )
    return {
        "n": len(rows),
        "prevalence": float((w * num).sum() / w.sum()),
        "ci_low": float(lo[0]),
        "ci_high": float(hi[0]),
    }


def compare_screen(
    main_run: str,
    run_ids: list[str],
    sample_id: str,
    cutoff: float = 0.7,
    n_boot: int = 2000,
    seed: int = 0,
) -> dict:
    sample = pq.read_table(paths.sample_path(sample_id))
    sub_rows = sample.to_pylist()
    sub_ids = {r["comment_id"] for r in sub_rows}
    main = _screen_probs(main_run)
    out = {
        "main_run": main_run,
        "sample_id": sample_id,
        "cutoff": cutoff,
        "n_sample": len(sub_rows),
        "runs": {},
    }
    for rid in [main_run, *run_ids]:
        probs = main if rid == main_run else _screen_probs(rid)
        entry = _prevalence(sub_rows, probs, cutoff, n_boot, seed)
        if rid != main_run:
            common = sorted(sub_ids & set(probs) & set(main))
            side_a = np.array([main[c] >= cutoff for c in common])
            side_b = np.array([probs[c] >= cutoff for c in common])
            entry["vs_main"] = {
                "n": len(common),
                "agreement": (
                    float((side_a == side_b).mean()) if common else None
                ),
                "kappa": _kappa(side_a, side_b),
                "spearman": _spearman(
                    [main[c] for c in common], [probs[c] for c in common]
                ),
            }
        out["runs"][rid] = entry
    return out


def _assign_labels(run_id: str, version: str) -> dict[int, tuple[str, str]]:
    """comment_id -> (group_id, card_id); a missing card counts as 'none'."""
    path = paths.run_dir(run_id) / f"assignments-{version}.parquet"
    rows = pq.read_table(path).to_pylist()
    return {
        int(r["comment_id"]): (
            r["group_id"],
            r["card_id"] if r["card_id"] is not None else "none",
        )
        for r in rows
    }


def _card_shares(labels: dict[int, tuple[str, str]]) -> dict[str, float]:
    """Card share over all assignment rows; 'none' is not a card."""
    n = len(labels)
    counts: dict[str, int] = {}
    for _g, card in labels.values():
        if card != "none":
            counts[card] = counts.get(card, 0) + 1
    return {c: cnt / n for c, cnt in counts.items()} if n else {}


def _top_n(shares: dict[str, float], n: int) -> list[str]:
    return sorted(shares, key=lambda c: (-shares[c], c))[:n]


def compare_assign(
    main_run: str, run_ids: list[str], version: str, top: int = 20
) -> dict:
    main = _assign_labels(main_run, version)
    main_shares = _card_shares(main)
    main_top = set(_top_n(main_shares, top))
    out = {
        "main_run": main_run,
        "version": version,
        "n_main": len(main),
        "runs": {},
    }
    for rid in run_ids:
        labels = _assign_labels(rid, version)
        shares = _card_shares(labels)
        cards = {}
        max_diff = 0.0
        for cid in sorted(main_top | set(_top_n(shares, top))):
            m, r = main_shares.get(cid, 0.0), shares.get(cid, 0.0)
            cards[cid] = {"main": m, "run": r, "abs_diff": abs(m - r)}
            max_diff = max(max_diff, abs(m - r))
        common = sorted(set(main) & set(labels))
        n = len(common)
        g_same = sum(main[c][0] == labels[c][0] for c in common)
        c_same = sum(main[c][1] == labels[c][1] for c in common)
        out["runs"][rid] = {
            "n": len(labels),
            "n_common": n,
            "group_agreement": (g_same / n) if n else None,
            "card_agreement": (c_same / n) if n else None,
            "card_shares": cards,
            "max_abs_diff": max_diff,
        }
    return out
