"""The stratified thread bootstrap the whole story shares.

``Replicates`` collapses a frame slice to (stratum, story_id) pairs once and
draws multinomial pair counts per stratum — a cluster bootstrap where the
cluster is the thread, matching ``atlas.sitedata.build_share.boot_totals``.
One draw set per ``Replicates`` object, so every quantity computed from it
(shares over buckets, their differences, ranks) is jointly resampled.
"""

from __future__ import annotations

import numpy as np

from atlas.story import io


def _codes(x) -> np.ndarray:
    return np.unique(np.asarray(x, dtype=object).astype(str), return_inverse=True)[1]


class Replicates:
    """Cluster-bootstrap replicate weights for one frame slice."""

    def __init__(self, frame_subset, R: int = 1000, seed: int = 0):
        self.w = np.asarray(frame_subset["weight"], dtype=float)
        pairs, inv = np.unique(
            np.stack(
                [_codes(frame_subset["stratum"]), _codes(frame_subset["story_id"])],
                axis=1,
            ),
            axis=0,
            return_inverse=True,
        )
        self.pairs, self.inv = pairs, inv.ravel()
        rng = np.random.default_rng(seed)
        self.counts = np.zeros((R, pairs.shape[0]))
        for s in np.unique(pairs[:, 0]):
            idx = np.flatnonzero(pairs[:, 0] == s)
            m = idx.size
            self.counts[:, idx] = rng.multinomial(
                m, np.full(m, 1.0 / m), size=R
            )

    def totals(self, values) -> np.ndarray:
        """(R, k) replicate sums of ``weight * values`` over resampled pairs."""
        v = np.asarray(values, dtype=float)
        if v.ndim == 1:
            v = v[:, None]
        sums = np.zeros((self.pairs.shape[0], v.shape[1]))
        np.add.at(sums, self.inv, self.w[:, None] * v)
        return self.counts @ sums

    def ratio(self, num_cols, den_col):
        """Point estimate ``sum(w*num)/sum(w*den)`` and replicate ratios.

        ``num_cols`` is (n,) or (n, k) per-row numerators; ``den_col`` is the
        (n,) denominator indicator. Returns ``(est[k], reps[R, k])``.
        """
        nums = np.asarray(num_cols, dtype=float)
        if nums.ndim == 1:
            nums = nums[:, None]
        den = np.asarray(den_col, dtype=float).ravel()
        t = self.totals(np.column_stack([den, nums]))
        with np.errstate(divide="ignore", invalid="ignore"):
            reps = t[:, 1:] / t[:, [0]]
        d = float((self.w * den).sum())
        est = (self.w @ nums) / d if d > 0 else np.full(nums.shape[1], np.nan)
        return est, reps


def summarize(est, reps, n: int) -> dict | None:
    """Percentile Est from replicate values; ``None`` when not computable."""
    reps = np.asarray(reps, dtype=float)
    reps = reps[np.isfinite(reps)]
    if est is None or not np.isfinite(est) or reps.size == 0:
        return None
    lo50, hi50, lo95, hi95 = np.quantile(reps, [0.25, 0.75, 0.025, 0.975])
    return io.est(est, lo50, hi50, lo95, hi95, int(n))
