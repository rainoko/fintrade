"""Tests for app.signals.swing_points (docs/tasks/backend-swing-point-detector.json).

Covers the three scenarios the task's checklist explicitly names (a clean uptrend/downtrend
with no swings, a single well-defined swing, a noisy series with multiple candidate swings
close together) plus the documented contract details (window validation, short-series/empty
handling, NaN handling, and plateau/tie merging) that later divergence-detection work depends
on being predictable.
"""

import numpy as np
import pandas as pd
import pytest

from app.signals.swing_points import SwingPoint, find_swing_points, swing_highs, swing_lows


class TestMonotonicSeriesHaveNoSwings:
    def test_clean_uptrend_has_no_swings(self) -> None:
        series = pd.Series([float(i) for i in range(20)])

        assert find_swing_points(series, window=2) == []

    def test_clean_downtrend_has_no_swings(self) -> None:
        series = pd.Series([float(20 - i) for i in range(20)])

        assert find_swing_points(series, window=2) == []


class TestSingleWellDefinedSwing:
    def test_single_peak_is_detected_as_the_only_swing_high(self) -> None:
        # Strictly rises to index 5, strictly falls after -- one unambiguous swing high.
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert points == [SwingPoint(index=5, value=6.0, kind="high")]

    def test_single_trough_is_detected_as_the_only_swing_low(self) -> None:
        # Mirror of the peak case -- strictly falls then strictly rises.
        values = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert points == [SwingPoint(index=5, value=1.0, kind="low")]

    def test_swing_uses_a_datetime_index_label_unchanged(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
        index = pd.bdate_range(start="2024-01-02", periods=len(values))
        series = pd.Series(values, index=index)

        points = find_swing_points(series, window=2)

        assert points == [SwingPoint(index=index[5], value=6.0, kind="high")]


class TestNoisySeriesWithCloseSwings:
    def test_multiple_close_candidate_swings_are_all_detected_in_order(self) -> None:
        # Two nearby peaks (indices 3 and 7) with a dip (index 5) between them -- hand-verified
        # below by checking each candidate index's 5-bar (window=2) neighborhood directly.
        # i=3: window [1,3,5,8,6,4][... ] -> values[1:6]=[3,5,8,6,4], value 8 == max -> high
        # i=5: values[3:8]=[8,6,4,6,9], value 4 == min -> low
        # i=7: values[5:10]=[4,6,9,7,4], value 9 == max -> high
        values = [1.0, 3.0, 5.0, 8.0, 6.0, 4.0, 6.0, 9.0, 7.0, 4.0, 2.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert points == [
            SwingPoint(index=3, value=8.0, kind="high"),
            SwingPoint(index=5, value=4.0, kind="low"),
            SwingPoint(index=7, value=9.0, kind="high"),
        ]

    def test_narrower_window_finds_more_swings_than_a_wider_one_on_the_same_series(self) -> None:
        # A short, sharp wiggle (index 1..5) that only a narrow window can resolve into
        # separate high/low/high/low/high candidates -- a wider window smooths it into a
        # single dominant swing high.
        values = [1.0, 4.0, 3.0, 5.0, 3.0, 4.0, 1.0]
        series = pd.Series(values)

        narrow = find_swing_points(series, window=1)
        wide = find_swing_points(series, window=2)

        assert narrow == [
            SwingPoint(index=1, value=4.0, kind="high"),
            SwingPoint(index=2, value=3.0, kind="low"),
            SwingPoint(index=3, value=5.0, kind="high"),
            SwingPoint(index=4, value=3.0, kind="low"),
            SwingPoint(index=5, value=4.0, kind="high"),
        ]
        assert wide == [SwingPoint(index=3, value=5.0, kind="high")]
        assert len(narrow) > len(wide)


class TestPlateauAndTieHandling:
    def test_flat_top_plateau_merges_into_a_single_swing_high_at_its_middle_bar(self) -> None:
        # Indices 2-4 form a 3-bar flat top (all 5.0) -- each one's own 5-bar window still has
        # 5.0 as its max, so all three are raw candidates; the contract merges them into one
        # point at the run's middle bar (index 3).
        values = [1.0, 3.0, 5.0, 5.0, 5.0, 3.0, 1.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert points == [SwingPoint(index=3, value=5.0, kind="high")]

    def test_even_length_plateau_merges_toward_the_later_bar(self) -> None:
        # A 2-bar flat top (indices 3-4) -- floor(2/2)=1 picks the second (later) bar.
        values = [1.0, 2.0, 3.0, 5.0, 5.0, 3.0, 2.0, 1.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert points == [SwingPoint(index=4, value=5.0, kind="high")]

    def test_equal_values_far_apart_are_kept_as_two_distinct_swing_points(self) -> None:
        # Two separate peaks that happen to share the exact same value, far enough apart that
        # they are not part of the same plateau run -- both must survive independently.
        values = [1.0, 3.0, 5.0, 3.0, 1.0, 2.0, 1.0, 3.0, 5.0, 3.0, 1.0]
        series = pd.Series(values)

        points = swing_highs(series, window=2)

        assert points == [
            SwingPoint(index=2, value=5.0, kind="high"),
            SwingPoint(index=8, value=5.0, kind="high"),
        ]

    def test_fully_flat_window_is_reported_as_both_a_high_and_a_low(self) -> None:
        series = pd.Series([5.0] * 7)

        points = find_swing_points(series, window=2)

        assert points == [
            SwingPoint(index=3, value=5.0, kind="high"),
            SwingPoint(index=3, value=5.0, kind="low"),
        ]


class TestNaNHandling:
    def test_a_nan_anywhere_in_a_candidates_window_disqualifies_it(self) -> None:
        # Every valid candidate index for window=2 on this 7-bar series has a window that
        # touches the interior NaN at index 2, so no swing point can be confirmed at all --
        # a partial max/min over just the remaining real values is deliberately NOT computed
        # (see this module's "NaN handling" docstring section).
        values = [1.0, 2.0, np.nan, 4.0, 3.0, 2.0, 1.0]
        series = pd.Series(values)

        assert find_swing_points(series, window=2) == []

    def test_indicator_style_warmup_nan_prefix_is_skipped_not_raised(self) -> None:
        # Mimics an EMA-based indicator's warm-up period (leading NaNs) feeding into this
        # function unmodified.
        values = [np.nan, np.nan, np.nan, 1.0, 3.0, 5.0, 3.0, 1.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert points == [SwingPoint(index=5, value=5.0, kind="high")]


class TestWindowAndLengthValidation:
    def test_window_less_than_one_raises_value_error(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0])

        with pytest.raises(ValueError, match="window"):
            find_swing_points(series, window=0)

    def test_empty_series_returns_no_swings(self) -> None:
        assert find_swing_points(pd.Series([], dtype=float), window=2) == []

    def test_series_shorter_than_the_full_window_returns_no_swings(self) -> None:
        # window=2 needs at least 2*2+1 == 5 bars.
        series = pd.Series([1.0, 5.0, 1.0, 5.0])

        assert find_swing_points(series, window=2) == []

    def test_first_and_last_window_bars_can_never_be_swing_points(self) -> None:
        # The global max/min sit right at the edges -- excluded regardless, since neither has
        # a full window on both sides.
        values = [9.0, 1.0, 2.0, 3.0, 4.0, 5.0, 0.0]
        series = pd.Series(values)

        points = find_swing_points(series, window=2)

        assert all(p.index not in (0, len(values) - 1) for p in points)


class TestConvenienceFilters:
    def test_swing_highs_and_swing_lows_filter_by_kind(self) -> None:
        values = [1.0, 3.0, 5.0, 8.0, 6.0, 4.0, 6.0, 9.0, 7.0, 4.0, 2.0]
        series = pd.Series(values)

        highs = swing_highs(series, window=2)
        lows = swing_lows(series, window=2)

        assert all(p.kind == "high" for p in highs)
        assert all(p.kind == "low" for p in lows)
        assert {p.index for p in highs} == {3, 7}
        assert {p.index for p in lows} == {5}
