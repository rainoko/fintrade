"""Tests for app.signals.seasons.classify_season (docs/Analyse.md, Elder ch. 32 "Time",
"Indicator Seasons").

Covers all four slope x centerline-position combinations (Spring/Summer/Autumn/Winter),
the tie-is-falling convention shared with app.signals.impulse._direction, the exact-zero-is-
below-centerline convention, and the insufficient-history/NaN degrade-to-None cases.
"""

import math

import pandas as pd

from app.signals.seasons import classify_season


class TestFourSeasons:
    """Each of the four slope x centerline-position combinations, from a minimal 2-point
    histogram series (only the last two points matter -- see TestOnlyLastTwoPointsMatter)."""

    def test_rising_below_centerline_is_spring(self) -> None:
        # -2.0 -> -1.0: rising (increased), still negative (below the zero centerline).
        assert classify_season(pd.Series([-2.0, -1.0])) == "Spring"

    def test_rising_above_centerline_is_summer(self) -> None:
        # 1.0 -> 2.0: rising, positive (above the centerline).
        assert classify_season(pd.Series([1.0, 2.0])) == "Summer"

    def test_falling_above_centerline_is_autumn(self) -> None:
        # 2.0 -> 1.0: falling (decreased), still positive (above the centerline).
        assert classify_season(pd.Series([2.0, 1.0])) == "Autumn"

    def test_falling_below_centerline_is_winter(self) -> None:
        # -1.0 -> -2.0: falling, negative (below the centerline).
        assert classify_season(pd.Series([-1.0, -2.0])) == "Winter"


class TestSeasonTransitions:
    """A single series walked through all four seasons in Elder's own natural cycle order
    (Winter -> Spring -> Summer -> Autumn -> Winter), read off each successive pair of
    points -- confirms the classification tracks a moving histogram correctly, not just
    isolated two-point fixtures."""

    def test_full_cycle(self) -> None:
        # Winter (still falling, below 0) -> trough -> Spring (rising, below 0) ->
        # crosses 0 -> Summer (rising, above 0) -> peak -> Autumn (falling, above 0) ->
        # crosses back below 0 -> Winter again (falling, below 0). Since only the latest
        # value decides centerline position, a centerline-crossing step itself already
        # reads as the new season (Summer/Winter respectively) rather than lagging a step.
        histogram = pd.Series([-1.0, -3.0, -2.0, -0.5, 1.0, 2.0, 1.5, -0.5, -2.0])

        seasons = [
            classify_season(histogram.iloc[: i + 1]) for i in range(1, len(histogram))
        ]

        assert seasons == [
            "Winter",  # -1.0 -> -3.0: falling, below
            "Spring",  # -3.0 -> -2.0: rising, below
            "Spring",  # -2.0 -> -0.5: rising, below
            "Summer",  # -0.5 -> 1.0: rising, above
            "Summer",  # 1.0 -> 2.0: rising, above
            "Autumn",  # 2.0 -> 1.5: falling, above
            "Winter",  # 1.5 -> -0.5: falling, and already below (crossed the centerline
            # this same step) -- Winter, not Autumn.
            "Winter",  # -0.5 -> -2.0: falling, below
        ]


class TestCenterlineAndTieConventions:
    def test_exact_zero_counts_as_below_centerline_not_above(self) -> None:
        # -1.0 -> 0.0: rising, and the new value (exactly 0) is treated as "below", not
        # "above" -- Spring, not Summer. See classify_season's own docstring for the
        # rationale (mirrors _is_force_index_spike's `sign * latest <= 0` treatment of zero
        # as not-positive).
        assert classify_season(pd.Series([-1.0, 0.0])) == "Spring"

    def test_exact_tie_counts_as_falling_not_rising(self) -> None:
        # 1.0 -> 1.0: an unmoved histogram is classified "falling" (Autumn, since it's also
        # above the centerline) -- same tie-is-falling convention as
        # app.signals.impulse._direction.
        assert classify_season(pd.Series([1.0, 1.0])) == "Autumn"

    def test_exact_tie_below_centerline_is_winter_not_spring(self) -> None:
        assert classify_season(pd.Series([-1.0, -1.0])) == "Winter"


class TestInsufficientHistory:
    def test_empty_series_returns_none(self) -> None:
        assert classify_season(pd.Series([], dtype=float)) is None

    def test_single_point_returns_none(self) -> None:
        assert classify_season(pd.Series([1.0])) is None

    def test_nan_latest_value_returns_none(self) -> None:
        assert classify_season(pd.Series([1.0, math.nan])) is None

    def test_nan_previous_value_returns_none(self) -> None:
        assert classify_season(pd.Series([math.nan, 1.0])) is None


class TestOnlyLastTwoPointsMatter:
    def test_earlier_history_is_ignored(self) -> None:
        """A long, wildly varying earlier history shouldn't affect the result -- only the
        last two points do."""
        earlier_noise = pd.Series([100.0, -50.0, 30.0, -10.0, 5.0])
        tail = pd.Series([-2.0, -1.0])  # rising, below -> Spring

        full_series = pd.concat([earlier_noise, tail], ignore_index=True)

        assert classify_season(full_series) == "Spring"
        assert classify_season(tail) == classify_season(full_series)
