"""Tests for app.signals.timeframe -- the generic long-term/intermediate/short-term
timeframe domain model (Elder ch. 39, docs/tasks/backend-day-trader-timeframe-mode.json
checklist item 2).
"""

import pytest

from app.signals.timeframe import (
    DEFAULT_SWING_TRIPLE_CODES,
    TimeframeInterval,
    TimeframeTriple,
    TimeframeUnit,
    TradingMode,
)


class TestTimeframeIntervalParseAndCode:
    @pytest.mark.parametrize(
        "code,unit,count",
        [
            ("1w", TimeframeUnit.WEEK, 1),
            ("1d", TimeframeUnit.DAY, 1),
            ("25m", TimeframeUnit.MINUTE, 25),
            ("5m", TimeframeUnit.MINUTE, 5),
            ("39m", TimeframeUnit.MINUTE, 39),
        ],
    )
    def test_parse_valid_codes(self, code: str, unit: TimeframeUnit, count: int) -> None:
        interval = TimeframeInterval.parse(code)
        assert interval.unit is unit
        assert interval.count == count

    def test_code_round_trips(self) -> None:
        for code in ("1w", "1d", "25m", "39m"):
            assert TimeframeInterval.parse(code).code == code

    @pytest.mark.parametrize(
        "bad_code",
        ["", "0m", "-5m", "5", "m5", "5x", "05m", "5 m", "5mm"],
    )
    def test_parse_rejects_malformed_codes(self, bad_code: str) -> None:
        with pytest.raises(ValueError):
            TimeframeInterval.parse(bad_code)

    def test_direct_construction_rejects_non_positive_count(self) -> None:
        with pytest.raises(ValueError):
            TimeframeInterval(unit=TimeframeUnit.DAY, count=0)
        with pytest.raises(ValueError):
            TimeframeInterval(unit=TimeframeUnit.MINUTE, count=-1)


class TestApproxTradingMinutes:
    def test_one_week_equals_five_trading_days(self) -> None:
        week = TimeframeInterval.parse("1w")
        five_days = TimeframeInterval.parse("5d")
        assert week.approx_trading_minutes == five_days.approx_trading_minutes

    def test_one_day_equals_390_minutes(self) -> None:
        day = TimeframeInterval.parse("1d")
        assert day.approx_trading_minutes == 390.0

    def test_minutes_are_literal(self) -> None:
        assert TimeframeInterval.parse("25m").approx_trading_minutes == 25.0


class TestTimeframeTripleOrdering:
    def test_valid_ordering_constructs_cleanly(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1w"),
            intermediate=TimeframeInterval.parse("1d"),
            short_term=TimeframeInterval.parse("30m"),
        )
        assert triple.long_term.code == "1w"

    def test_book_25min_5min_2min_day_trading_example_is_valid(self) -> None:
        # Elder ch. 39's own day-trading example.
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        assert triple.factor_of_five_warnings() == []

    def test_book_39min_8min_pairing_is_within_guideline_band(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("39m"),
            intermediate=TimeframeInterval.parse("8m"),
            short_term=TimeframeInterval.parse("1m"),
        )
        # 39/8 ~= 4.9x, 8/1 = 8x -- both within the 2x-10x band.
        assert triple.factor_of_five_warnings() == []

    def test_inverted_ordering_raises(self) -> None:
        with pytest.raises(ValueError):
            TimeframeTriple(
                long_term=TimeframeInterval.parse("1d"),
                intermediate=TimeframeInterval.parse("1w"),
                short_term=TimeframeInterval.parse("30m"),
            )

    def test_equal_legs_raises(self) -> None:
        with pytest.raises(ValueError):
            TimeframeTriple(
                long_term=TimeframeInterval.parse("1d"),
                intermediate=TimeframeInterval.parse("1d"),
                short_term=TimeframeInterval.parse("30m"),
            )

    def test_default_swing_triple_codes_would_not_construct_as_a_timeframe_triple(self) -> None:
        # Documented, deliberate: DEFAULT_SWING_TRIPLE_CODES is intermediate == short_term
        # ("1d", "1d"), which the strict ordering rule correctly rejects -- see the constant's
        # own docstring for why it's kept as a plain tuple of codes instead.
        long_code, intermediate_code, short_code = DEFAULT_SWING_TRIPLE_CODES
        with pytest.raises(ValueError):
            TimeframeTriple(
                long_term=TimeframeInterval.parse(long_code),
                intermediate=TimeframeInterval.parse(intermediate_code),
                short_term=TimeframeInterval.parse(short_code),
            )


class TestFactorOfFiveWarnings:
    def test_weekly_daily_pairing_needs_a_third_leg_within_band(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1w"),
            intermediate=TimeframeInterval.parse("1d"),
            short_term=TimeframeInterval.parse("120m"),
        )
        # 1w=1950min, 1d=390min (ratio 5x, in-band); 1d=390min vs 120min (ratio 3.25x, in-band).
        assert triple.factor_of_five_warnings() == []

    def test_ratio_below_band_warns(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("10m"),
            intermediate=TimeframeInterval.parse("8m"),
            short_term=TimeframeInterval.parse("1m"),
        )
        warnings = triple.factor_of_five_warnings()
        assert len(warnings) == 1
        assert "long_term" in warnings[0] and "intermediate" in warnings[0]

    def test_ratio_above_band_warns(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("100m"),
            short_term=TimeframeInterval.parse("1m"),
        )
        warnings = triple.factor_of_five_warnings()
        assert len(warnings) == 1
        assert "intermediate" in warnings[0] and "short_term" in warnings[0]

    def test_both_legs_out_of_band_warns_twice(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("100m"),
            intermediate=TimeframeInterval.parse("90m"),
            short_term=TimeframeInterval.parse("89m"),
        )
        warnings = triple.factor_of_five_warnings()
        assert len(warnings) == 2

    def test_ratio_exactly_at_min_boundary_does_not_warn(self) -> None:
        # Both legs exactly 2.0x -- _FACTOR_OF_FIVE_MIN_RATIO's own value -- pins the `<` (not
        # `<=`) comparison in factor_of_five_warnings(): the boundary itself is in-band.
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("20m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("5m"),
        )
        assert triple.factor_of_five_warnings() == []

    def test_ratio_exactly_at_max_boundary_does_not_warn(self) -> None:
        # Both legs exactly 10.0x -- _FACTOR_OF_FIVE_MAX_RATIO's own value -- pins the `>` (not
        # `>=`) comparison in factor_of_five_warnings(): the boundary itself is in-band.
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("100m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("1m"),
        )
        assert triple.factor_of_five_warnings() == []


class TestTradingModeEnum:
    def test_values(self) -> None:
        assert TradingMode.SWING.value == "swing"
        assert TradingMode.DAY_TRADER.value == "day_trader"
