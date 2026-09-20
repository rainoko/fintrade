"""Tests for app.signals._swing_extremes (docs/tasks/backend-swing-point-detector-followups-
followups.json).

This package-internal module has no dedicated test file of its own prior to this task --
its behavior was previously exercised only indirectly through app.signals.swing_points and
app.signals.support_resistance's own test suites. These tests lock in the module's own
contract directly: rolling_max_mask/rolling_min_mask (the single-purpose wrappers this task
added so support_resistance.py doesn't compute and discard an unused rolling reduction) agree
with rolling_extreme_masks's combined result, and require_full_window's NaN-tolerance switch
behaves as documented for each.
"""

import numpy as np
import pandas as pd

from app.signals._swing_extremes import (
    rolling_extreme_masks,
    rolling_max_mask,
    rolling_min_mask,
)


class TestRollingMaxMinMasksAgreeWithCombinedFunction:
    def test_max_mask_matches_combined_first_element(self) -> None:
        series = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 1.0])

        combined_max, _combined_min = rolling_extreme_masks(series, 3, require_full_window=False)
        solo_max = rolling_max_mask(series, 3, require_full_window=False)

        pd.testing.assert_series_equal(combined_max, solo_max)

    def test_min_mask_matches_combined_second_element(self) -> None:
        series = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 1.0])

        _combined_max, combined_min = rolling_extreme_masks(series, 3, require_full_window=False)
        solo_min = rolling_min_mask(series, 3, require_full_window=False)

        pd.testing.assert_series_equal(combined_min, solo_min)

    def test_masks_agree_with_require_full_window_true_too(self) -> None:
        series = pd.Series([1.0, np.nan, 2.0, 5.0, 4.0, 6.0, 1.0])

        combined_max, combined_min = rolling_extreme_masks(series, 3, require_full_window=True)
        solo_max = rolling_max_mask(series, 3, require_full_window=True)
        solo_min = rolling_min_mask(series, 3, require_full_window=True)

        pd.testing.assert_series_equal(combined_max, solo_max)
        pd.testing.assert_series_equal(combined_min, solo_min)


class TestRequireFullWindowNanHandling:
    def test_require_full_window_true_excludes_positions_whose_window_touches_nan(self) -> None:
        # window of span 3 centered on index 1 includes index 0 (NaN) -- position 1 must be
        # excluded from both masks despite its own value (5.0) being the series' overall max.
        series = pd.Series([np.nan, 5.0, 1.0, 2.0, 3.0])

        is_high = rolling_max_mask(series, 3, require_full_window=True)
        is_low = rolling_min_mask(series, 3, require_full_window=True)

        assert bool(is_high.iloc[1]) is False
        assert bool(is_low.iloc[1]) is False

    def test_require_full_window_false_tolerates_nan_via_skipna(self) -> None:
        # Same series, but the permissive mode should still flag index 1 as a max/min over
        # whatever real neighbors are available (skipna aggregation), matching
        # app.signals.support_resistance's original, more permissive behavior.
        series = pd.Series([np.nan, 5.0, 1.0, 2.0, 3.0])

        is_high = rolling_max_mask(series, 3, require_full_window=False)

        assert bool(is_high.iloc[1]) is True

    def test_index_is_preserved_on_a_non_default_index(self) -> None:
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        series = pd.Series([1.0, 2.0, 5.0, 2.0, 1.0], index=dates)

        is_high = rolling_max_mask(series, 3, require_full_window=True)

        assert list(is_high.index) == list(dates)
        assert bool(is_high.loc[dates[2]]) is True
