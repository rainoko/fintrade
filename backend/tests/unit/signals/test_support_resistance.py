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
