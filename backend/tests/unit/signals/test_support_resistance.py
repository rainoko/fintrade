"""Tests for app.signals.support_resistance (Elder ch. 18, docs/tasks/backend-support-resistance.json).

Fixtures use a strictly-monotonic "filler" baseline (each bar's close a tiny fraction higher
than the previous) so no filler bar ever ties its neighbors and accidentally registers as a
swing point itself -- only the explicitly-overridden "touch"/"breach" bars are local extrema.
This keeps each fixture's swing points, and therefore its zones, fully predictable and
hand-verifiable rather than relying on the algorithm's own output to define what "should"
happen.
"""

import pandas as pd
import pytest

from app.signals.support_resistance import (
    FalseBreakout,
    Zone,
    _cluster_touches,
    _dollar_volume,
    _height_category,
    _length_category,
    _strength_score,
    detect_support_resistance_zones,
)


def _bar(high: float, low: float, close: float, volume: float = 1_000_000.0) -> dict:
    return {"open": close, "high": high, "low": low, "close": close, "volume": volume}


def _filler_bar(i: int, base: float = 90.0) -> dict:
    close = base + 0.001 * i
    return {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 500_000.0}


def _build_ohlcv(n: int, overrides: dict[int, dict], *, base: float = 90.0) -> pd.DataFrame:
    rows = [_filler_bar(i, base=base) for i in range(n)]
    for i, bar in overrides.items():
        rows[i] = bar
    index = pd.bdate_range(start="2024-01-02", periods=n)
    return pd.DataFrame(rows, index=index)


class TestCleanMultiTouchZone:
    def test_detects_unbroken_resistance_zone_from_repeated_touches(self) -> None:
        daily_ohlcv = _build_ohlcv(
            60,
            {
                4: _bar(110.0, 107.0, 109.0),
                24: _bar(110.0, 107.0, 109.3),
                44: _bar(110.0, 107.0, 108.8),
            },
        )

        zones = detect_support_resistance_zones(daily_ohlcv)
        matches = [z for z in zones if z.role == "resistance" and z.lower == pytest.approx(108.8)]

        assert len(matches) == 1
        zone = matches[0]
        assert zone.upper == pytest.approx(109.3)
        assert zone.touch_count == 3
        assert zone.first_touch_date == daily_ohlcv.index[4]
        assert zone.last_touch_date == daily_ohlcv.index[44]
        # 40 business days apart == 8 weeks == 56 calendar days, under the 60-day intermediate floor.
        assert zone.length_days == 56
        assert zone.length_category == "minor"
        assert zone.broken is False
        assert zone.break_date is None
        assert zone.false_breakout is None

    def test_max_zones_caps_the_returned_list(self) -> None:
        daily_ohlcv = _build_ohlcv(
            60,
            {
                4: _bar(110.0, 107.0, 109.0),
                24: _bar(110.0, 107.0, 109.3),
                44: _bar(110.0, 107.0, 108.8),
            },
        )

        zones = detect_support_resistance_zones(daily_ohlcv, max_zones=1)

        assert len(zones) == 1


class TestRankingSurvivesCheapScoreExpensiveBuildSplit:
    """Regression coverage for PR #164's efficiency refactor (splitting the old
    "score everything, then sort" pipeline into a cheap `_score_candidate` used for
    ranking every candidate, and the expensive `_build_zone` -- the break/false-breakout
    scan and dollar-volume aggregation -- run only on the top-`max_zones` survivors).

    `test_max_zones_caps_the_returned_list` above only exercises a single qualifying
    candidate truncated to `max_zones=1` -- it can't catch a ranking-order regression
    (e.g. a future edit to the sort key, or to the score/build split) since there's
    nothing to reorder. This builds 20 candidate resistance zones (more than the
    default `max_zones=15`) spanning every reachable `strength_score` value below the
    "major length" category (worth avoiding here purely to keep the fixture's bar count
    reasonable -- "major" length needs a >=730-calendar-day touch span) and asserts the
    real returned zones are genuinely the top-15 by (strength_score, touch_count,
    last_touch_date) descending, not just any 15 zones.
    """

    # Business-day gaps chosen (and verified below) to land squarely inside the "minor"
    # (<60 calendar days) and "intermediate" (60-729 calendar days) length categories,
    # clear of both boundaries.
    _LENGTH_GAP_BDAYS = {"minor": 16, "intermediate": 45}
    # height_pct targets chosen clear of the minor/intermediate (2%) and
    # intermediate/major (5%) boundaries.
    _HEIGHT_PCT_TARGET = {"minor": 1.0, "intermediate": 3.0, "major": 7.0}

    # 20 (length_category, height_category) combos, ordered so that band index `k`
    # (0-19) increases monotonically with the band's own place in time (see
    # `_build_fixture` below) *and* groups by resulting strength_score tier:
    #   k 0-2:   minor/minor         -> score 33.33 (tier D, all 3 dropped)
    #   k 3-9:   minor/intermediate & intermediate/minor -> score 50.00 (tier C, 7
    #            candidates but only max_zones-10=5 slots remain -- the 2 EARLIEST
    #            (lowest k, earliest last_touch_date) of these 7 must be dropped)
    #   k 10-16: minor/major & intermediate/intermediate -> score 66.67 (tier B, all 7 kept)
    #   k 17-19: intermediate/major -> score 83.33 (tier A, all 3 kept)
    # This deliberately exercises both a fully-kept tier, a fully-dropped tier, AND a
    # tier that's only partially kept (so the tie-break on last_touch_date, not just
    # strength_score, has to be right for the cap to land on the correct candidates).
    _COMBOS = (
        [("minor", "minor")] * 3
        + [("minor", "intermediate")] * 3
        + [("intermediate", "minor")] * 4
        + [("minor", "major")] * 3
        + [("intermediate", "intermediate")] * 4
        + [("intermediate", "major")] * 3
    )

    def _build_fixture(self) -> tuple[pd.DataFrame, list[dict]]:
        assert len(self._COMBOS) == 20

        cursor = 5
        band_meta: list[dict] = []
        for k, (length_kind, height_kind) in enumerate(self._COMBOS):
            gap = self._LENGTH_GAP_BDAYS[length_kind]
            first_idx = cursor
            last_idx = first_idx + gap
            # Band price levels spaced 5% apart (and starting at 2000) so that no two
            # bands' touches ever fall within `_CLUSTER_TOLERANCE_PCT` (1%) of each
            # other's running mean and accidentally merge into one cluster.
            band_price = 2000.0 * (1 + 0.05 * k)
            band_meta.append(
                {
                    "k": k,
                    "length_kind": length_kind,
                    "height_kind": height_kind,
                    "first_idx": first_idx,
                    "last_idx": last_idx,
                    "band_price": band_price,
                }
            )
            # +10 buffer so this band's touch bars are never within the fractal
            # window (2) of the next band's -- each override bar must independently
            # register as a local high regardless of its neighbors.
            cursor = last_idx + 10
        n = cursor + 10  # trailing buffer so the last touch still has a full window

        # Matches `_filler_bar`'s own formula for the series' last close (no override
        # ever lands on the final bar), computed up front since every band's
        # height_pct is deliberately anchored to this single reference price.
        reference_price = 90.0 + 0.001 * (n - 1)

        overrides: dict[int, dict] = {}
        for meta in band_meta:
            height_gap = self._HEIGHT_PCT_TARGET[meta["height_kind"]] / 100 * reference_price
            lower_price = meta["band_price"]
            upper_price = lower_price + height_gap
            # Two touches per band (== _MIN_TOUCHES), well within 1% of each other
            # (height_gap is at most 7% of the ~91 reference_price, i.e. a few
            # dollars, against a >=2000 band price -- comfortably inside tolerance).
            overrides[meta["first_idx"]] = _bar(lower_price + 2, lower_price - 2, lower_price)
            overrides[meta["last_idx"]] = _bar(upper_price + 2, upper_price - 2, upper_price)
            meta["upper"] = upper_price
            meta["lower"] = lower_price

        daily_ohlcv = _build_ohlcv(n, overrides)

        index = daily_ohlcv.index
        for meta in band_meta:
            length_days = (index[meta["last_idx"]] - index[meta["first_idx"]]).days
            height_pct = abs(meta["upper"] - meta["lower"]) / reference_price * 100
            length_category = _length_category(length_days)
            height_category = _height_category(height_pct)
            # Confirms the fixture itself actually lands in the intended category --
            # if this ever fails, the fixture's own construction needs adjusting, not
            # the code under test.
            assert length_category == meta["length_kind"]
            assert height_category == meta["height_kind"]
            meta["strength_score"] = _strength_score(length_category, height_category)
            meta["last_touch_date"] = index[meta["last_idx"]]

        return daily_ohlcv, band_meta

    def test_top_max_zones_survive_in_strict_descending_strength_order(self) -> None:
        daily_ohlcv, band_meta = self._build_fixture()

        # Independently-computed expected ranking: sort every candidate by
        # (strength_score, k) descending -- `k` stands in for `last_touch_date` here
        # since every band has an equal touch_count (2) and `_build_fixture` places
        # bands strictly later in time as `k` increases, so higher k == later
        # last_touch_date == the correct tie-break winner.
        expected_ranked = sorted(band_meta, key=lambda m: (m["strength_score"], m["k"]), reverse=True)
        expected_kept = expected_ranked[:15]
        expected_dropped = expected_ranked[15:]
        # Sanity-check the fixture actually produces the partial-tier-truncation
        # scenario this test is designed to exercise (see class docstring).
        assert {m["k"] for m in expected_kept} == {5, 6, 7, 8, 9} | set(range(10, 20))
        assert {m["k"] for m in expected_dropped} == {0, 1, 2, 3, 4}

        zones = detect_support_resistance_zones(daily_ohlcv)

        assert len(zones) == 15

        # 1. The returned zones are truly sorted by the documented key, strictly
        # descending pair-by-pair (not just "roughly ordered").
        for earlier, later in zip(zones, zones[1:], strict=False):
            earlier_key = (earlier.strength_score, earlier.touch_count, earlier.last_touch_date)
            later_key = (later.strength_score, later.touch_count, later.last_touch_date)
            assert earlier_key > later_key

        # 2. Each returned zone matches the independently-computed expected survivor
        # at that same rank -- not just "some 15 zones in the right order", but the
        # SPECIFIC 15 the sort key says should win.
        for zone, expected in zip(zones, expected_kept, strict=True):
            assert zone.strength_score == pytest.approx(expected["strength_score"])
            assert zone.touch_count == 2
            assert zone.last_touch_date == expected["last_touch_date"]
            assert zone.upper == pytest.approx(expected["upper"])
            assert zone.lower == pytest.approx(expected["lower"])

        # 3. None of the 5 lowest-ranked candidates (all of tier D, plus the 2
        # earliest of the partially-kept tier C) leaked into the result.
        returned_last_touch_dates = {zone.last_touch_date for zone in zones}
        for expected in expected_dropped:
            assert expected["last_touch_date"] not in returned_last_touch_dates


class TestZoneRoleFlip:
    def test_true_breakout_flips_role_and_marks_broken(self) -> None:
        overrides = {
            4: _bar(110.0, 107.0, 109.0),
            24: _bar(110.0, 107.0, 109.3),
            44: _bar(110.0, 107.0, 108.8),
        }
        # A sustained close above the zone, with no bar ever closing back inside it within
        # the false-breakout confirmation window -- a genuine, held breakout.
        for i in range(50, 60):
            overrides[i] = _bar(116.0, 113.0, 115.0)
        daily_ohlcv = _build_ohlcv(60, overrides)

        zones = detect_support_resistance_zones(daily_ohlcv)
        matches = [z for z in zones if z.upper == pytest.approx(109.3) and z.lower == pytest.approx(108.8)]

        assert len(matches) == 1
        zone = matches[0]
        assert zone.broken is True
        assert zone.break_date == daily_ohlcv.index[50]
        assert zone.role == "support"  # flipped from resistance
        assert zone.false_breakout is None


class TestFalseBreakout:
    def test_false_breakout_is_flagged_without_flipping_role_or_breaking(self) -> None:
        overrides = {
            4: _bar(83.0, 80.0, 82.0),
            24: _bar(83.0, 80.0, 82.3),
            44: _bar(83.0, 80.0, 81.8),
            # Breach: closes below the support zone's lower edge (81.8).
            48: _bar(78.0, 70.0, 75.0),
            # Reentry: closes back inside [81.8, 82.3] within the confirmation window.
            49: _bar(83.0, 81.0, 82.0),
        }
        daily_ohlcv = _build_ohlcv(60, overrides, base=130.0)

        zones = detect_support_resistance_zones(daily_ohlcv)
        matches = [z for z in zones if z.role == "support" and z.lower == pytest.approx(81.8)]

        assert len(matches) == 1
        zone = matches[0]
        assert zone.upper == pytest.approx(82.3)
        assert zone.broken is False
        assert zone.break_date is None
        assert zone.false_breakout == FalseBreakout(
            direction="down",
            breakout_date=daily_ohlcv.index[48],
            reentry_date=daily_ohlcv.index[49],
            extreme_price=70.0,
        )


    def test_false_breakout_up_direction_uses_the_failed_moves_own_high_as_extreme(self) -> None:
        overrides = {
            4: _bar(110.0, 107.0, 109.0),
            24: _bar(110.0, 107.0, 109.3),
            44: _bar(110.0, 107.0, 108.8),
            # Breach: closes above the resistance zone's upper edge (109.3).
            48: _bar(120.0, 112.0, 115.0),
            # Reentry: closes back inside [108.8, 109.3] within the confirmation window.
            49: _bar(110.0, 108.9, 109.0),
        }
        daily_ohlcv = _build_ohlcv(60, overrides)

        zones = detect_support_resistance_zones(daily_ohlcv)
        matches = [z for z in zones if z.role == "resistance" and z.lower == pytest.approx(108.8)]

        assert len(matches) == 1
        zone = matches[0]
        assert zone.broken is False
        assert zone.false_breakout == FalseBreakout(
            direction="up",
            breakout_date=daily_ohlcv.index[48],
            reentry_date=daily_ohlcv.index[49],
            extreme_price=120.0,
        )


class TestValidationAndDegenerateInputs:
    def test_empty_daily_ohlcv_returns_no_zones(self) -> None:
        daily_ohlcv = pd.DataFrame(columns=["high", "low", "close", "volume"])

        assert detect_support_resistance_zones(daily_ohlcv) == []

    def test_too_short_daily_ohlcv_returns_no_zones(self) -> None:
        daily_ohlcv = _build_ohlcv(3, {})  # shorter than 2*fractal_window + 1 == 5

        assert detect_support_resistance_zones(daily_ohlcv) == []

    def test_missing_required_column_raises_value_error(self) -> None:
        daily_ohlcv = _build_ohlcv(10, {}).drop(columns=["volume"])

        with pytest.raises(ValueError, match="volume"):
            detect_support_resistance_zones(daily_ohlcv)


class TestClusterTouchesChainDrift:
    def test_running_mean_merge_can_drift_a_clusters_span_beyond_tolerance_pct(self) -> None:
        """Regression test for the "chain drift" limitation documented on
        _cluster_touches: each point is merged if it's within ``tolerance_pct`` of the
        cluster's CURRENT running mean, not its original anchor point, so a sequence of
        individually-in-tolerance merges can walk the cluster's own end-to-end span past
        ``tolerance_pct`` -- not a bug (upper/lower are still the cluster's real price
        extremes), but worth pinning down so it can't silently change without a test noticing.
        """
        touches = [
            (pd.Timestamp("2024-01-01"), 100.0),
            # +0.90% vs the running mean so far (100.0) -- merges.
            (pd.Timestamp("2024-01-02"), 100.9),
            # +1.00% vs the running mean so far ((100.0 + 100.9) / 2 == 100.45) -- still
            # merges, even though this point is +1.45% away from the cluster's FIRST point.
            (pd.Timestamp("2024-01-03"), 101.45),
        ]

        clusters = _cluster_touches(touches, tolerance_pct=0.01, min_touches=2, min_length_days=0)

        assert len(clusters) == 1
        cluster = clusters[0]
        assert cluster["touch_count"] == 3
        assert cluster["upper"] == pytest.approx(101.45)
        assert cluster["lower"] == pytest.approx(100.0)
        span_pct = (cluster["upper"] - cluster["lower"]) / cluster["lower"] * 100
        # The cluster's total end-to-end span (1.45%) exceeds the nominal 1% per-step
        # tolerance -- every individual merge decision was in-tolerance, but the chain as a
        # whole drifted past it.
        assert span_pct == pytest.approx(1.45)
        assert span_pct > 1.0


class TestStrengthScoringHelpers:
    def test_length_category_thresholds(self) -> None:
        assert _length_category(13) == "minor"
        assert _length_category(59) == "minor"
        assert _length_category(60) == "intermediate"
        assert _length_category(729) == "intermediate"
        assert _length_category(730) == "major"

    def test_height_category_thresholds(self) -> None:
        assert _height_category(1.9) == "minor"
        assert _height_category(2.0) == "intermediate"
        assert _height_category(4.9) == "intermediate"
        assert _height_category(5.0) == "major"

    def test_strength_score_is_average_of_category_scores(self) -> None:
        assert _strength_score("minor", "minor") == pytest.approx(100 / 3)
        assert _strength_score("major", "major") == pytest.approx(100.0)
        assert _strength_score("minor", "major") == pytest.approx((100 / 3 + 100.0) / 2)

    def test_dollar_volume_is_days_times_avg_volume_times_avg_price(self) -> None:
        index = pd.bdate_range(start="2024-01-02", periods=3)
        daily_ohlcv = pd.DataFrame(
            {
                "high": [11.0, 12.0, 13.0],
                "low": [9.0, 10.0, 11.0],
                "close": [10.0, 11.0, 12.0],
                "volume": [1_000.0, 2_000.0, 3_000.0],
            },
            index=index,
        )

        result = _dollar_volume(daily_ohlcv, index[0], index[2])

        # 3 trading days x avg volume (2000) x avg close (11) == 66000
        assert result == pytest.approx(3 * 2_000.0 * 11.0)

    def test_dollar_volume_is_zero_for_a_window_with_no_matching_dates(self) -> None:
        index = pd.bdate_range(start="2024-01-02", periods=3)
        daily_ohlcv = pd.DataFrame(
            {"high": [11.0], "low": [9.0], "close": [10.0], "volume": [1_000.0]},
            index=[index[0]],
        )

        result = _dollar_volume(daily_ohlcv, index[1], index[2])

        assert result == 0.0


class TestZoneDataclassRepr:
    def test_zone_is_a_plain_dataclass_with_expected_fields(self) -> None:
        zone = Zone(
            role="resistance",
            upper=100.0,
            lower=98.0,
            first_touch_date=pd.Timestamp("2024-01-01"),
            last_touch_date=pd.Timestamp("2024-02-01"),
            touch_count=2,
            length_days=31,
            length_category="minor",
            height_pct=2.0,
            height_category="intermediate",
            dollar_volume=1_000.0,
            strength_score=50.0,
        )

        assert zone.broken is False
        assert zone.break_date is None
        assert zone.false_breakout is None
