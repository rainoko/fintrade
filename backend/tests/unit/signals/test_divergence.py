"""Tests for app.signals.divergence (docs/tasks/backend-divergence-detection.json).

Covers the checklist's four pieces separately:

1. MACD-Histogram divergence (bullish + bearish), including the hard centerline-crossing
   requirement ("no crossover, no divergence").
2. Stochastic/RSI divergence (simpler -- no centerline requirement), including the
   informational overbought/oversold "beyond reference line" strength flag.
3. Kerry Lovvorn's spacing (20-40 bars) and half-depth filters, each as standalone
   unit tests of their own named function plus one end-to-end rejection case.
4. "Hound of the Baskervilles" (aborted divergences).

Plus the ``DivergenceSwingCache``/``confirmed_divergence_as_of`` no-look-ahead contract that
``app.signals.engine.analyse_history`` depends on.

**FIXTURE_A** (used by most of the MACD-Histogram tests below) is a 41-bar (index 0-40)
synthetic price/indicator pair, hand-constructed (not real market data -- docs/ideas.md
describes the book's own DJIA 2007-2009 divergence chart only in prose, with no reproducible
numeric series actually transcribed into this repo's docs to build a literal fixture from; see
this task's `decisions` entry) so every filter's pass/fail boundary is independently
verifiable by inspection:

    price:      idx 0-10   100 -> 50   (step -5, 11 bars)   trough at idx 10 = 50
                idx 10-20   50 -> 100   (step +5, 11 bars)   peak   at idx 20 = 100
                idx 20-30  100 -> 20   (step -8, 11 bars)   trough at idx 30 = 20  (a new,
                                                              LOWER low than idx 10's 50)
                idx 30-40   20 -> 60   (step +4, 11 bars)

    indicator (macd_histogram-shaped): idx 10 = -10 (first trough, depth 10 from zero)
                                        idx 11-20 ramps -6,-2,2,6,8,8,8,8,8,8 (crosses above
                                          zero between idx 12 (-2) and idx 13 (2))
                                        idx 21-30 ramps  6,4,2,0,-1,-2,-2,-2,-2,-3 (idx 30 = -3,
                                          a SHALLOWER trough than idx 10's -10 -- depth 3,
                                          ratio 3/10 = 0.3 <= 0.5)
                                        idx 31-40 flat 0

So: price makes a new (lower) low, the indicator makes a shallower low, the indicator crossed
its centerline in between, and the two troughs are exactly 20 bars apart (the tight edge of
Lovvorn's accepted 20-40 range) -- a fully qualifying bullish MACD-Histogram divergence.
"""

import pandas as pd
import pytest

from app.signals import divergence
from app.signals.divergence import (
    DEFAULT_SWING_WINDOW,
    Divergence,
    DivergenceExtreme,
    build_divergence_swing_cache,
    confirmed_divergence_as_of,
    current_divergence,
    find_divergences,
    is_beyond_reference_line,
    is_second_extreme_shallow_enough,
    is_spacing_valid,
    latest_divergence,
    macd_centerline_crossed,
)

_FIXTURE_A_PRICE = pd.Series(
    [float(v) for v in range(100, 49, -5)]  # idx 0-10: 100,95,...,50
    + [float(v) for v in range(55, 101, 5)]  # idx 11-20: 55,60,...,100
    + [float(v) for v in range(92, 19, -8)]  # idx 21-30: 92,84,...,20
    + [float(v) for v in range(24, 61, 4)]  # idx 31-40: 24,28,...,60
)

_FIXTURE_A_MACD_HISTOGRAM = pd.Series(
    [0.0] * 10  # idx 0-9 (unused)
    + [-10.0]  # idx 10 -- first (deeper) trough
    + [-6.0, -2.0, 2.0, 6.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0]  # idx 11-20
    + [6.0, 4.0, 2.0, 0.0, -1.0, -2.0, -2.0, -2.0, -2.0, -3.0]  # idx 21-30 (idx 30 = -3)
    + [0.0] * 10  # idx 31-40 (unused)
)

# Same shape, but never rallies above zero between the two troughs -- otherwise-qualifying in
# every other respect, isolating the centerline-crossing requirement.
_FIXTURE_A_MACD_HISTOGRAM_NO_CROSS = pd.Series(
    [0.0] * 10
    + [-10.0]
    + [-8.0] * 10  # idx 11-20 -- stays negative throughout
    + [-8.0, -7.0, -6.0, -5.0, -4.0, -4.0, -4.0, -4.0, -4.0, -3.0]  # idx 21-30
    + [0.0] * 10
)


def _fixture_a_bullish_divergence() -> Divergence:
    """The hand-verified expected ``Divergence`` for `_FIXTURE_A_PRICE`/
    `_FIXTURE_A_MACD_HISTOGRAM` (see module docstring)."""
    return Divergence(
        indicator="macd_histogram",
        kind="bullish",
        first=DivergenceExtreme(date=10, price=50.0, indicator_value=-10.0),
        second=DivergenceExtreme(date=30, price=20.0, indicator_value=-3.0),
        bars_apart=20,
        centerline_crossed=True,
        beyond_reference_line=None,
        aborted=False,
    )


class TestMacdHistogramDivergence:
    def test_qualifying_bullish_divergence_matches_hand_computed_values(self) -> None:
        results = find_divergences(
            _FIXTURE_A_PRICE,
            _FIXTURE_A_MACD_HISTOGRAM,
            indicator_name="macd_histogram",
            kind="bullish",
        )

        assert results == [_fixture_a_bullish_divergence()]

    def test_bearish_divergence_is_the_mirror_case(self) -> None:
        # Mirror of FIXTURE_A: price makes a new HIGHER high (peak at idx 30 = 130, vs idx 10's
        # 100), the indicator makes a SHALLOWER peak (idx 30 = 3, vs idx 10's 10 -- ratio 0.3),
        # and crosses below zero between the two peaks (idx 13 = -2).
        price = pd.Series(
            [float(v) for v in range(50, 101, 5)]  # idx 0-10: 50,...,100
            + [float(v) for v in range(95, 49, -5)]  # idx 11-20: 95,...,50
            + [float(v) for v in range(58, 131, 8)]  # idx 21-30: 58,...,130
            + [float(v) for v in range(126, 89, -4)]  # idx 31-40: 126,...,90
        )
        histogram = pd.Series(
            [0.0] * 10
            + [10.0]  # idx 10 -- first (higher) peak
            + [6.0, 2.0, -2.0, -6.0, -8.0, -8.0, -8.0, -8.0, -8.0, -8.0]  # idx 11-20
            + [-6.0, -4.0, -2.0, 0.0, 1.0, 2.0, 2.0, 2.0, 2.0, 3.0]  # idx 21-30 (idx 30 = 3)
            + [0.0] * 10
        )

        results = find_divergences(price, histogram, indicator_name="macd_histogram", kind="bearish")

        assert results == [
            Divergence(
                indicator="macd_histogram",
                kind="bearish",
                first=DivergenceExtreme(date=10, price=100.0, indicator_value=10.0),
                second=DivergenceExtreme(date=30, price=130.0, indicator_value=3.0),
                bars_apart=20,
                centerline_crossed=True,
                beyond_reference_line=None,
                aborted=False,
            )
        ]

    def test_no_centerline_crossing_means_no_divergence_at_all(self) -> None:
        # Same price (so the same two swing lows, same spacing, same shallower-depth ratio),
        # but the indicator never rallies above zero in between -- "no crossover, no
        # divergence" per the book, so this must be rejected outright, not merely flagged weak.
        results = find_divergences(
            _FIXTURE_A_PRICE,
            _FIXTURE_A_MACD_HISTOGRAM_NO_CROSS,
            indicator_name="macd_histogram",
            kind="bullish",
        )

        assert results == []

    def test_macd_centerline_crossed_directly(self) -> None:
        assert (
            macd_centerline_crossed(_FIXTURE_A_MACD_HISTOGRAM, 10, 30, "bullish")
            is True
        )
        assert (
            macd_centerline_crossed(
                _FIXTURE_A_MACD_HISTOGRAM_NO_CROSS, 10, 30, "bullish"
            )
            is False
        )


class TestStochasticAndRsiDivergence:
    """Same price swings as FIXTURE_A, but a bounded 0-100 oscillator indicator standing in for
    Stochastic %K/RSI -- no centerline-crossing requirement, just the direct second-vs-first
    comparison, per docs/ideas.md ch. 26/27."""

    def test_beyond_reference_line_when_first_extreme_is_deeply_oversold(self) -> None:
        # idx 10 = 15 (< 30, oversold -- "beyond the reference line"), idx 30 = 35 (>= 30, back
        # inside it) -- the textbook-strongest case. Depth from the oversold line (30):
        # first = |15-30| = 15, second = |35-30| = 5, ratio 5/15 = 0.333 <= 0.5.
        indicator = pd.Series([50.0] * 10 + [15.0] + [50.0] * 19 + [35.0] + [50.0] * 10)

        results = find_divergences(
            _FIXTURE_A_PRICE, indicator, indicator_name="stochastic", kind="bullish"
        )

        assert results == [
            Divergence(
                indicator="stochastic",
                kind="bullish",
                first=DivergenceExtreme(date=10, price=50.0, indicator_value=15.0),
                second=DivergenceExtreme(date=30, price=20.0, indicator_value=35.0),
                bars_apart=20,
                centerline_crossed=None,
                beyond_reference_line=True,
                aborted=False,
            )
        ]

    def test_not_beyond_reference_line_when_second_extreme_stays_below_it(self) -> None:
        # idx 10 = 10 (deep), idx 30 = 25 -- shallower than idx 10 (higher value) but still
        # below the 30 oversold line, so NOT "back inside" it. Still a valid divergence (no
        # requirement, just not the textbook-strongest case): depth first = |10-30| = 20,
        # second = |25-30| = 5, ratio 5/20 = 0.25 <= 0.5.
        indicator = pd.Series([50.0] * 10 + [10.0] + [50.0] * 19 + [25.0] + [50.0] * 10)

        results = find_divergences(_FIXTURE_A_PRICE, indicator, indicator_name="rsi", kind="bullish")

        assert results == [
            Divergence(
                indicator="rsi",
                kind="bullish",
                first=DivergenceExtreme(date=10, price=50.0, indicator_value=10.0),
                second=DivergenceExtreme(date=30, price=20.0, indicator_value=25.0),
                bars_apart=20,
                centerline_crossed=None,
                beyond_reference_line=False,
                aborted=False,
            )
        ]

    def test_is_beyond_reference_line_directly(self) -> None:
        assert is_beyond_reference_line(15.0, 35.0, "bullish") is True
        assert is_beyond_reference_line(10.0, 25.0, "bullish") is False
        assert is_beyond_reference_line(85.0, 65.0, "bearish") is True
        assert is_beyond_reference_line(90.0, 75.0, "bearish") is False

    def test_rsi_beyond_reference_line_uses_rsi_constants_not_stochastic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test for docs/tasks/backend-divergence-detection-followups.json: the RSI
        branch of `_evaluate_pair` must pass `_RSI_OVERSOLD`/`_RSI_OVERBOUGHT` explicitly to
        `is_beyond_reference_line`, not silently fall back to that function's own default
        parameters (which happen to equal `_STOCHASTIC_OVERSOLD`/`_STOCHASTIC_OVERBOUGHT`
        today). Diverges RSI's own constants from Stochastic's here to prove the two are read
        independently -- if the RSI call site ever regressed to relying on the shared default,
        this would compute `beyond_reference_line` against the (now-different) Stochastic
        constants and this test would fail."""
        monkeypatch.setattr(divergence, "_RSI_OVERSOLD", 20.0)
        monkeypatch.setattr(divergence, "_RSI_OVERBOUGHT", 80.0)

        # idx 10 = 15 (below both RSI's patched 20 and Stochastic's unchanged 30 oversold
        # lines -- either constant pair agrees this extreme is deeply oversold). idx 30 = 21:
        # back inside RSI's patched 20 line (correct fix -> beyond_reference_line True), but
        # still below Stochastic's unchanged 30 line (the bug this regression-tests against --
        # silently falling back to Stochastic's defaults -> beyond_reference_line False).
        indicator = pd.Series([50.0] * 10 + [15.0] + [50.0] * 19 + [21.0] + [50.0] * 10)

        results = find_divergences(_FIXTURE_A_PRICE, indicator, indicator_name="rsi", kind="bullish")

        assert len(results) == 1
        assert results[0].beyond_reference_line is True


class TestLovvornFilters:
    """Both filters as standalone, independently-testable functions (per this task's own
    checklist item), plus one end-to-end rejection case each showing they're wired into the
    real detection path, not just unit-tested in isolation."""

    def test_is_spacing_valid_boundaries(self) -> None:
        assert is_spacing_valid(19) is False  # just under the 20-bar floor
        assert is_spacing_valid(20) is True  # the tight edge of the accepted range
        assert is_spacing_valid(40) is True  # the wide edge
        assert is_spacing_valid(41) is False  # just over the 40-bar ceiling

    def test_is_spacing_valid_respects_custom_bounds(self) -> None:
        assert is_spacing_valid(10, min_bars=5, max_bars=15) is True
        assert is_spacing_valid(16, min_bars=5, max_bars=15) is False

    def test_spacing_filter_rejects_a_too_close_pair_end_to_end(self) -> None:
        # Same shape as FIXTURE_A's price/indicator, but with the second trough only 10 bars
        # after the first (idx 20 instead of idx 30) -- otherwise identical qualifying depth/
        # centerline-crossing conditions.
        price = pd.Series(
            [float(v) for v in range(100, 49, -5)]  # idx 0-10: trough at idx 10 = 50
            + [float(v) for v in range(42, 19, -3)]  # idx 11-20: 42,...,21 -- new low at idx 20
        )
        histogram = pd.Series(
            [0.0] * 10 + [-10.0] + [-4.0, 2.0, 4.0, 4.0, 4.0, 4.0, 2.0, 0.0, -1.0, -3.0]
        )

        results = find_divergences(price, histogram, indicator_name="macd_histogram", kind="bullish")

        assert results == []

    def test_is_second_extreme_shallow_enough(self) -> None:
        assert is_second_extreme_shallow_enough(10.0, 5.0) is True  # exactly half
        assert is_second_extreme_shallow_enough(10.0, 5.1) is False  # just over half
        assert is_second_extreme_shallow_enough(10.0, 0.0) is True  # much shallower
        assert is_second_extreme_shallow_enough(0.0, 0.0) is False  # nothing to be a fraction of
        assert is_second_extreme_shallow_enough(-1.0, 0.0) is False  # non-positive first_depth

    def test_depth_filter_rejects_a_second_extreme_that_is_not_shallow_enough(self) -> None:
        # Same price/spacing as FIXTURE_A, but the second trough's indicator value (-8) is only
        # a small fraction shallower than the first (-10) -- depth ratio 8/10 = 0.8 > 0.5.
        histogram = pd.Series(
            [0.0] * 10
            + [-10.0]
            + [-6.0, -2.0, 2.0, 6.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0]
            + [6.0, 4.0, 2.0, 0.0, -1.0, -2.0, -4.0, -6.0, -7.0, -8.0]
            + [0.0] * 10
        )

        results = find_divergences(
            _FIXTURE_A_PRICE, histogram, indicator_name="macd_histogram", kind="bullish"
        )

        assert results == []


class TestHoundOfTheBaskervilles:
    def test_aborted_true_when_price_makes_a_new_low_after_the_divergence(self) -> None:
        # FIXTURE_A's price/indicator through idx 33 (idx 30's own 7-bar swing window, idx
        # 27-33, is left unchanged so idx 30 is still a genuine swing low), but idx 34-40 then
        # crashes well below the second trough's own low (20) instead of recovering the way
        # FIXTURE_A's own idx 34-40 (40,44,...,60) does -- price "ignores" the bullish
        # divergence.
        price = pd.Series(
            _FIXTURE_A_PRICE.iloc[:34].tolist()  # idx 0-33 unchanged (idx 31-33 = 24,28,32)
            + [10.0, 5.0, 0.0, -5.0, -10.0, -15.0, -20.0]  # idx 34-40
        )

        results = find_divergences(
            price, _FIXTURE_A_MACD_HISTOGRAM, indicator_name="macd_histogram", kind="bullish"
        )

        assert len(results) == 1
        assert results[0].aborted is True

    def test_aborted_false_when_price_confirms_the_reversal(self) -> None:
        results = find_divergences(
            _FIXTURE_A_PRICE, _FIXTURE_A_MACD_HISTOGRAM, indicator_name="macd_histogram", kind="bullish"
        )

        assert len(results) == 1
        assert results[0].aborted is False


class TestLatestAndCurrentDivergence:
    def test_latest_divergence_returns_the_single_fixture_a_result(self) -> None:
        result = latest_divergence(
            _FIXTURE_A_PRICE, _FIXTURE_A_MACD_HISTOGRAM, indicator_name="macd_histogram"
        )

        assert result == _fixture_a_bullish_divergence()

    def test_latest_divergence_is_none_when_nothing_qualifies(self) -> None:
        assert (
            latest_divergence(
                _FIXTURE_A_PRICE, _FIXTURE_A_MACD_HISTOGRAM_NO_CROSS, indicator_name="macd_histogram"
            )
            is None
        )

    def test_current_divergence_breaks_ties_in_favor_of_macd_histogram(self) -> None:
        # All three indicators produce a qualifying divergence with the exact same
        # second-extreme date (idx 30, since they all key off the same price swing points) --
        # MACD-Histogram must win the tie-break over Stochastic/RSI.
        stochastic = pd.Series([50.0] * 10 + [15.0] + [50.0] * 19 + [35.0] + [50.0] * 10)
        rsi = pd.Series([50.0] * 10 + [10.0] + [50.0] * 19 + [25.0] + [50.0] * 10)

        result = current_divergence(
            _FIXTURE_A_PRICE,
            macd_histogram=_FIXTURE_A_MACD_HISTOGRAM,
            stochastic=stochastic,
            rsi=rsi,
        )

        assert result is not None
        assert result.indicator == "macd_histogram"

    def test_current_divergence_falls_back_to_stochastic_over_rsi(self) -> None:
        stochastic = pd.Series([50.0] * 10 + [15.0] + [50.0] * 19 + [35.0] + [50.0] * 10)
        rsi = pd.Series([50.0] * 10 + [10.0] + [50.0] * 19 + [25.0] + [50.0] * 10)

        result = current_divergence(
            _FIXTURE_A_PRICE,
            macd_histogram=None,
            stochastic=stochastic,
            rsi=rsi,
        )

        assert result is not None
        assert result.indicator == "stochastic"

    def test_current_divergence_is_none_when_no_series_supplied(self) -> None:
        assert current_divergence(_FIXTURE_A_PRICE) is None


class TestDivergenceSwingCache:
    def test_confirmed_divergence_matches_current_divergence_at_full_history(self) -> None:
        cache = build_divergence_swing_cache(_FIXTURE_A_PRICE, window=DEFAULT_SWING_WINDOW)

        result = confirmed_divergence_as_of(
            cache, len(_FIXTURE_A_PRICE) - 1, macd_histogram=_FIXTURE_A_MACD_HISTOGRAM
        )

        assert result == current_divergence(_FIXTURE_A_PRICE, macd_histogram=_FIXTURE_A_MACD_HISTOGRAM)

    def test_confirmed_divergence_is_none_before_the_second_swing_point_is_confirmed(self) -> None:
        # The second trough is at position 30; app.signals.swing_points needs `window` bars on
        # BOTH sides to confirm a swing point, so it isn't confirmed until position 30 + window.
        # One bar earlier than that, this divergence must not be reported yet -- no look-ahead.
        cache = build_divergence_swing_cache(_FIXTURE_A_PRICE, window=DEFAULT_SWING_WINDOW)
        not_yet_confirmed_position = 30 + DEFAULT_SWING_WINDOW - 1

        result = confirmed_divergence_as_of(
            cache, not_yet_confirmed_position, macd_histogram=_FIXTURE_A_MACD_HISTOGRAM
        )

        assert result is None

    def test_confirmed_divergence_appears_exactly_once_confirmed(self) -> None:
        cache = build_divergence_swing_cache(_FIXTURE_A_PRICE, window=DEFAULT_SWING_WINDOW)
        just_confirmed_position = 30 + DEFAULT_SWING_WINDOW

        result = confirmed_divergence_as_of(
            cache, just_confirmed_position, macd_histogram=_FIXTURE_A_MACD_HISTOGRAM
        )

        assert result == _fixture_a_bullish_divergence()

    def test_confirmed_divergence_as_of_checks_stochastic_and_rsi_too(self) -> None:
        # Same shape/positions as the stochastic/RSI TestStochasticAndRsiDivergence fixtures
        # above, run through the cache-based path instead of find_divergences directly --
        # covers the stochastic/rsi branches of confirmed_divergence_as_of (only
        # macd_histogram is exercised by the other TestDivergenceSwingCache tests).
        stochastic = pd.Series([50.0] * 10 + [15.0] + [50.0] * 19 + [35.0] + [50.0] * 10)
        rsi = pd.Series([50.0] * 10 + [10.0] + [50.0] * 19 + [25.0] + [50.0] * 10)
        cache = build_divergence_swing_cache(_FIXTURE_A_PRICE, window=DEFAULT_SWING_WINDOW)

        result = confirmed_divergence_as_of(
            cache, len(_FIXTURE_A_PRICE) - 1, stochastic=stochastic, rsi=rsi
        )

        assert result is not None
        assert result.indicator == "stochastic"  # priority tie-break over rsi

    def test_confirmed_divergence_as_of_picks_up_a_bearish_pair_too(self) -> None:
        # Covers the `bearish` branch of `_most_recent_confirmed` (every other
        # TestDivergenceSwingCache test above only exercises the bullish side).
        price = pd.Series(
            [float(v) for v in range(50, 101, 5)]
            + [float(v) for v in range(95, 49, -5)]
            + [float(v) for v in range(58, 131, 8)]
            + [float(v) for v in range(126, 89, -4)]
        )
        histogram = pd.Series(
            [0.0] * 10
            + [10.0]
            + [6.0, 2.0, -2.0, -6.0, -8.0, -8.0, -8.0, -8.0, -8.0, -8.0]
            + [-6.0, -4.0, -2.0, 0.0, 1.0, 2.0, 2.0, 2.0, 2.0, 3.0]
            + [0.0] * 10
        )
        cache = build_divergence_swing_cache(price, window=DEFAULT_SWING_WINDOW)

        result = confirmed_divergence_as_of(cache, len(price) - 1, macd_histogram=histogram)

        assert result is not None
        assert result.kind == "bearish"


class TestEvaluatePairErrorHandling:
    """Covers `_evaluate_pair`'s defensive checks -- exercised here via `find_divergences`
    (its public entry point) rather than importing the private function directly."""

    def test_invalid_indicator_name_raises(self) -> None:
        with pytest.raises(ValueError, match="indicator_name"):
            find_divergences(
                _FIXTURE_A_PRICE,
                _FIXTURE_A_MACD_HISTOGRAM,
                indicator_name="not_a_real_indicator",  # type: ignore[arg-type]
                kind="bullish",
            )

    def test_invalid_kind_raises(self) -> None:
        # An invalid `kind` doesn't match "bullish", so find_divergences takes the swing_highs
        # branch -- needs a price series with >= 2 swing highs (FIXTURE_A only has one) for
        # `_evaluate_pair` to actually run and raise.
        price_with_two_swing_highs = pd.Series(
            [float(v) for v in range(50, 101, 5)]
            + [float(v) for v in range(95, 49, -5)]
            + [float(v) for v in range(58, 131, 8)]
            + [float(v) for v in range(126, 89, -4)]
        )
        with pytest.raises(ValueError, match="kind"):
            find_divergences(
                price_with_two_swing_highs,
                _FIXTURE_A_MACD_HISTOGRAM,
                indicator_name="macd_histogram",
                kind="not_a_real_kind",  # type: ignore[arg-type]
            )

    def test_indicator_missing_a_swing_points_date_is_skipped(self) -> None:
        # The indicator series doesn't cover the second swing point's own date at all (not
        # just NaN there) -- must be treated the same as "can't evaluate this pair", not raise.
        short_indicator = _FIXTURE_A_MACD_HISTOGRAM.iloc[:25]

        assert (
            find_divergences(
                _FIXTURE_A_PRICE, short_indicator, indicator_name="macd_histogram", kind="bullish"
            )
            == []
        )

    def test_macd_centerline_crossed_empty_between_range_is_false(self) -> None:
        # No bars at all strictly between the two dates (adjacent positions) -- covers
        # macd_centerline_crossed's `between.empty` branch directly.
        histogram = pd.Series([-5.0, -4.0, -3.0])
        assert macd_centerline_crossed(histogram, 0, 1, "bullish") is False
