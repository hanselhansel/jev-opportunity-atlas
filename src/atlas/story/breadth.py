"""Per-card breadth: domain mix, coverage-adjusted entropy, residuals.

``domains`` is the card's weighted domain distribution. ``entropy`` is the
Chao-Shen coverage-adjusted Shannon entropy in bits of the card's unweighted
domain counts, with an interval from the card's own cluster-bootstrap
replicates (resampled threads reshape the count vector). ``residuals`` are
the Pearson residuals of the whole card x domain contingency table under
independence, so a card is judged against the population's domain mix, not
its own.
"""

from __future__ import annotations

import numpy as np

from atlas.story import io
from atlas.story.boot import Replicates

SPARSE_N = 100


def _chao_shen(counts: np.ndarray) -> float:
    """Chao-Shen entropy in bits of a count vector."""
    x = np.asarray(counts, dtype=float)
    n = x.sum()
    if n <= 0:
        return float("nan")
    p = x[x > 0] / n
    f1 = float((x == 1).sum())
    cov = 1.0 - f1 / n
    pc = cov * p
    pc = pc[pc > 0]
    corr = 1.0 - np.power(1.0 - pc, n)
    ok = corr > 0
    if not ok.any():
        return 0.0
    return float(-(pc[ok] * np.log2(pc[ok]) / corr[ok]).sum())


def _placed(frame, require_domain: bool = True):
    mask = (
        (frame["phase"] == "pos")
        & frame["firsthand"]
        & frame["card"].notna()
    )
    if require_domain:
        mask &= frame["domain"].notna()
    return frame[mask]


def _residuals(fh, cards: list, domains: list) -> dict:
    """Pearson residuals (obs - exp)/sqrt(exp) per card x domain cell."""
    dcodes = fh["domain"].astype(object).map(
        {d: k for k, d in enumerate(domains)}
    )
    ccodes = fh["card"].astype(object).map(
        {c: k for k, c in enumerate(cards)}
    )
    keep = dcodes.notna() & ccodes.notna()
    obs = np.zeros((len(cards), len(domains)))
    np.add.at(
        obs,
        (
            ccodes[keep].to_numpy(dtype=int),
            dcodes[keep].to_numpy(dtype=int),
        ),
        1.0,
    )
    row_t = obs.sum(axis=1, keepdims=True)
    col_t = obs.sum(axis=0, keepdims=True)
    total = obs.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        exp = row_t * col_t / total if total else np.zeros_like(obs)
        resid = np.where(exp > 0, (obs - exp) / np.sqrt(np.where(exp > 0, exp, 1)), np.nan)
    out = {}
    for k, card in enumerate(cards):
        out[card] = {
            d: float(resid[k, j])
            for j, d in enumerate(domains)
            if np.isfinite(resid[k, j])
        }
    return out


def card_breadth(frame, R: int = 1000, seed: int = 0) -> dict:
    """``{card: {entropy: Est, domains: {name: float}, residuals}}``."""
    fh = _placed(frame)
    placed = _placed(frame, require_domain=False)
    cards = sorted(
        placed["card"].unique()
        if frame.attrs.get("cardset") is None
        else frame.attrs["cardset"].cards
    )
    domains = sorted({d for d in fh["domain"] if isinstance(d, str)})
    dpos = {d: j for j, d in enumerate(domains)}
    residuals = _residuals(fh, cards, domains) if domains else {}
    card_vals = fh["card"].astype(object).to_numpy()
    card_all = placed["card"].astype(object).to_numpy()
    out = {}
    for card in cards:
        mask = card_vals == card
        sub = fh[mask]
        n_all = int((card_all == card).sum())
        dom_idx = np.array(
            [dpos.get(d, -1) for d in sub["domain"].astype(object)]
        )
        counts = np.array(
            [(dom_idx == j).sum() for j in range(len(domains))], dtype=float
        )
        w = sub["weight"].to_numpy(dtype=float)
        wd = np.zeros(len(domains))
        np.add.at(wd, dom_idx[dom_idx >= 0], w[dom_idx >= 0])
        wsum = wd.sum()
        dist = {
            d: float(wd[j] / wsum)
            for j, d in enumerate(domains)
            if wsum > 0 and wd[j] > 0
        }
        ent = _chao_shen(counts)
        ent_est = None
        if np.isfinite(ent):
            rep = Replicates(sub, R=R, seed=seed)
            pair_counts = np.zeros((rep.pairs.shape[0], len(domains)))
            np.add.at(
                pair_counts,
                (rep.inv, dom_idx.clip(0)),
                (dom_idx >= 0).astype(float),
            )
            rep_counts = rep.counts @ pair_counts
            reps = np.array([_chao_shen(r) for r in rep_counts])
            reps = reps[np.isfinite(reps)]
            if reps.size:
                lo50, hi50, lo95, hi95 = np.quantile(
                    reps, [0.25, 0.75, 0.025, 0.975]
                )
                ent_est = io.est(ent, lo50, hi50, lo95, hi95, n_all)
                ent_est["sparse"] = n_all < SPARSE_N
        out[card] = {
            "entropy": ent_est,
            "domains": dist,
            "residuals": residuals.get(card, {}),
        }
    return out
