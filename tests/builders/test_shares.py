"""S6 task 2 tests: builder shares, the builder-to-complaint ratio, and the
match rate, all through the month-stratified bootstrap."""

import numpy as np
import pyarrow as pa
import pytest

from atlas.builders import sample, shares


def _assign_row(story_id, card_id, card_p):
    return {
        "comment_id": story_id,
        "card_id": card_id,
        "card_p": card_p,
        "group_id": "g01",
    }


def _sample_table(ids, periods, weights):
    return pa.table(
        {
            "story_id": pa.array(ids, type=pa.int64()),
            "period": pa.array(periods, type=pa.string()),
            "weight": pa.array(weights, type=pa.float64()),
        },
        schema=sample.SAMPLE_SCHEMA,
    )


def _complaints(est, reps=None, n=40):
    return {"est": est, "reps": list(reps) if reps is not None else [est] * 200}


def test_zero_launch_card():
    ids = [9_000_000_001 + i for i in range(4)]
    table = _sample_table(ids, ["P01", "P01", "P02", "P02"], [4.0] * 4)
    assigns = [_assign_row(i, "cA", 0.9) for i in ids]
    story_cards = {
        "cA": _complaints(0.10),
        "cB": _complaints(0.05, reps=[0.04, 0.05, 0.06] * 100),
    }
    _builders, per_card = shares.builder_shares(assigns, table, story_cards)
    zero = per_card["cB"]
    assert zero["launch_share"]["est"] == 0.0
    assert zero["launch_share"]["n"] == 0
    assert zero["launch_share"]["sparse"] is True
    assert zero["ratio"]["est"] == 0.0
    # the upper bound comes out of the joint replicate sets
    assert zero["ratio"]["hi95"] >= zero["ratio"]["est"]
    assert np.isfinite(zero["ratio"]["hi95"])


def test_match_rate_and_card_shares():
    ids = [9_000_000_001 + i for i in range(4)]
    table = _sample_table(ids, ["P01", "P01", "P02", "P02"], [4.0] * 4)
    assigns = [
        _assign_row(ids[0], "cA", 0.9),
        _assign_row(ids[1], "cA", 0.7),
        _assign_row(ids[2], "none", 0.9),
        _assign_row(ids[3], "cB", 0.3),  # below MIN_CARD_P: not a match
    ]
    story_cards = {"cA": _complaints(0.25), "cB": _complaints(0.05)}
    builders, per_card = shares.builder_shares(assigns, table, story_cards)
    assert builders["n_sampled"] == 4
    assert builders["n_population"] == 16
    assert builders["match_rate"]["est"] == pytest.approx(0.5)
    assert per_card["cA"]["launch_share"]["est"] == pytest.approx(0.5)
    assert per_card["cA"]["launch_share"]["n"] == 2
    assert per_card["cA"]["ratio"]["est"] == pytest.approx(0.5 / 0.25)
    # cB has launches in the data but none at card_p >= 0.5
    assert per_card["cB"]["launch_share"]["est"] == 0.0
    assert per_card["cB"]["launch_share"]["sparse"] is True


def test_merged_card_resolves_into_target():
    """Launch assignments on a merged card bucket under its target."""
    ids = [9_000_000_001 + i for i in range(4)]
    table = _sample_table(ids, ["P01", "P01", "P02", "P02"], [4.0] * 4)
    assigns = [
        _assign_row(ids[0], "n136", 0.9),
        _assign_row(ids[1], "n014", 0.9),
        _assign_row(ids[2], "none", 0.9),
        _assign_row(ids[3], "n136", 0.3),  # below MIN_CARD_P: not a match
    ]
    resolve = lambda c: {"n136": "n014"}.get(c, c)
    _, per_card = shares.builder_shares(
        assigns, table, {}, resolve=resolve
    )
    assert "n136" not in per_card
    assert per_card["n014"]["launch_share"]["est"] == pytest.approx(0.5)
    assert per_card["n014"]["launch_share"]["n"] == 2


def test_weighted_share_uses_month_weights():
    ids = [9_000_000_001 + i for i in range(4)]
    # P01 rows weigh 8 each, P02 rows weigh 1 each
    table = _sample_table(ids, ["P01", "P01", "P02", "P02"], [8.0, 8.0, 1.0, 1.0])
    assigns = [
        _assign_row(ids[0], "cA", 0.9),
        _assign_row(ids[1], "cA", 0.9),
        _assign_row(ids[2], "cB", 0.9),
        _assign_row(ids[3], "cB", 0.9),
    ]
    builders, per_card = shares.builder_shares(assigns, table, {})
    # cA: 16/18, cB: 2/18
    assert per_card["cA"]["launch_share"]["est"] == pytest.approx(16 / 18)
    assert per_card["cB"]["launch_share"]["est"] == pytest.approx(2 / 18)
    assert builders["match_rate"]["est"] == pytest.approx(1.0)


def test_deterministic_replicates():
    ids = [9_000_000_001 + i for i in range(6)]
    table = _sample_table(ids, ["P01"] * 3 + ["P02"] * 3, [3.0] * 6)
    assigns = [_assign_row(i, "cA", 0.9) for i in ids[:3]]
    a = shares.builder_shares(assigns, table, {"cA": _complaints(0.2)})
    b = shares.builder_shares(assigns, table, {"cA": _complaints(0.2)})
    assert a == b


def test_ratio_null_when_no_complaint_entry_or_zero():
    ids = [9_000_000_001 + i for i in range(4)]
    table = _sample_table(ids, ["P01", "P01", "P02", "P02"], [2.0] * 4)
    assigns = [_assign_row(i, "cA", 0.9) for i in ids]
    _, per_card = shares.builder_shares(assigns, table, {})
    assert per_card["cA"]["ratio"] is None
    _, per_card = shares.builder_shares(
        assigns, table, {"cA": {"est": 0.0, "reps": [0.0] * 100}}
    )
    assert per_card["cA"]["ratio"] is None


def test_interval_widens_on_few_launches():
    """A card backed by one launch in one month resamples wider than a card
    spread across the sample."""
    ids = [9_000_000_001 + i for i in range(60)]
    table = _sample_table(ids, ["P01"] * 30 + ["P02"] * 30, [2.0] * 60)
    thin = [_assign_row(ids[0], "thin", 0.9)] + [
        _assign_row(i, "none", 0.9) for i in ids[1:]
    ]
    _, thin_cards = shares.builder_shares(thin, table, {})
    spread = [_assign_row(i, "wide", 0.9) for i in ids]
    _, wide_cards = shares.builder_shares(spread, table, {})
    thin = thin_cards["thin"]["launch_share"]
    wide = wide_cards["wide"]["launch_share"]
    assert thin["hi95"] > thin["est"]  # some resamples redraw the one launch
    assert wide["lo95"] == pytest.approx(1.0)  # always everything
    assert thin["sparse"] is True and wide["sparse"] is False
