"""The ``domains`` section: screened discussion vs firsthand complaints.

``discussion`` is the weighted domain share over all phase-2 rows (pos and
neg together, i.e. every screened comment); ``complaints`` is the same share
over firsthand problems only. ``rate = complaints / discussion`` uses the
same joint replicates, so a domain where complaints outpace general
discussion shows a rate above 1 with an honest interval.
"""

from __future__ import annotations

import numpy as np

from atlas.story.boot import Replicates, summarize
from atlas.story.core import _codes


def build_domains(frame, rep_all: Replicates) -> list[dict]:
    fhpos = (
        (frame["phase"] == "pos") & frame["firsthand"]
    ).to_numpy(dtype=float)
    domv = frame["domain"].astype(object).to_numpy()
    doms = sorted({d for d in domv if isinstance(d, str)})
    codes = _codes(domv, doms)
    nums_d = (codes[:, None] == np.arange(len(doms))[None, :]).astype(float)
    nums_c = nums_d * fhpos[:, None]
    est_d, reps_d = rep_all.ratio(nums_d, np.ones(len(frame)))
    est_c, reps_c = rep_all.ratio(nums_c, fhpos)
    with np.errstate(divide="ignore", invalid="ignore"):
        est_r = est_c / est_d
        reps_r = reps_c / reps_d
    n_d = (nums_d > 0).sum(axis=0).astype(int)
    n_c = (nums_c > 0).sum(axis=0).astype(int)
    return [
        {
            "id": d,
            "discussion": summarize(est_d[k], reps_d[:, k], int(n_d[k])),
            "complaints": summarize(est_c[k], reps_c[:, k], int(n_c[k])),
            "rate": summarize(est_r[k], reps_r[:, k], int(n_c[k])),
        }
        for k, d in enumerate(doms)
    ]
