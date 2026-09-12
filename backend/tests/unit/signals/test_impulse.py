"""Tests for app.signals.impulse.evaluate_impulse (docs/Analyse.md §3, the Impulse System).

Three layers of coverage, matching docs/architecture/Backend.md's "Signal engine tests
cover each Screen 1/2/3 + Impulse combination explicitly" guidance:

1. ``TestDirection`` isolates the bar-over-bar direction test itself (the strict ">"
   boundary -- see this task's `decisions` entry on docs/tasks/impulse-system.json for why
   a tie counts as "falling" rather than "rising", and why there's no "flat" state at all
   unlike Screen 1's tide slope).
2. ``TestEvaluateImpulseCombinationLogic`` isolates the GREEN/RED/BLUE decision table from
   real indicator math by mocking ``_direction``/``ema``/``macd_histogram`` -- covers every
   direction x direction combination, not just the two "everything agrees" happy paths.
3. ``TestEvaluateImpulseEndToEnd`` exercises the real, unmocked composition
   (``evaluate_impulse`` -> ``ema``/``macd_histogram`` -> ``_direction``) over small
   synthetic daily OHLCV series, confirming the wiring itself (not just the decision table
   in isolation) produces each of GREEN/RED/BLUE -- including a genuine (non-mocked)
   disagreement case, not just insufficient-data BLUE.
"""

import pandas as pd
import pytest

from app.signals.impulse import _direction, evaluate_impulse


def _daily_ohlcv(closes: pd.Series) -> pd.DataFrame:
    """Wrap a close-price Series into a minimal daily OHLCV frame (open/high/low/volume
    filled with plausible placeholder values -- evaluate_impulse only reads the close column).
    """
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": 1_000_000,
        }
    )


class TestDirection:
    """Isolates the bar-over-bar direction test's boundary behavior."""

    def test_strictly_greater_is_rising(self) -> None:
        assert _direction(pd.Series([1.0, 1.0001])) == "rising"

    def test_strictly_less_is_falling(self) -> None:
        assert _direction(pd.Series([1.0001, 1.0])) == "falling"

    def test_exact_tie_is_falling_not_rising(self) -> None:
        """No change bar-over-bar does not count as "rising" -- the comparison is a strict
        ">", so an exact tie falls through to "falling" (see this task's `decisions` entry
        for the rationale: an unmoved indicator hasn't demonstrated upward momentum, and
        treating it as "falling" is the more conservative gate direction, consistent with
        Screen 1's own use of a strict "> threshold" rather than ">=").
        """
        assert _direction(pd.Series([5.0, 5.0])) == "falling"


class TestEvaluateImpulseCombinationLogic:
    """Isolates the GREEN/RED/BLUE decision table from real indicator math by mocking
    ema()/macd_histogram()/_direction directly -- covers every direction x direction
    combination, not just the two "everything agrees" happy paths.
    """

    def _mock_directions(self, mocker, *, ema_direction: str, histogram_direction: str) -> None:
        # evaluate_impulse computes ema_direction first, then histogram_direction (fixed
        # call order in the implementation) -- side_effect list mirrors that order.
        mocker.patch("app.signals.impulse.ema", return_value=pd.Series([1.0, 2.0]))
        mocker.patch("app.signals.impulse.macd_histogram", return_value=pd.Series([1.0, 2.0]))
        mocker.patch(
            "app.signals.impulse._direction",
            side_effect=[ema_direction, histogram_direction],
        )

    @pytest.mark.parametrize(
        ("ema_direction", "histogram_direction", "expected"),
        [
            ("rising", "rising", "GREEN"),
            ("falling", "falling", "RED"),
            ("rising", "falling", "BLUE"),
            ("falling", "rising", "BLUE"),
        ],
    )
    def test_decision_table(self, mocker, ema_direction, histogram_direction, expected) -> None:
        self._mock_directions(
            mocker, ema_direction=ema_direction, histogram_direction=histogram_direction
        )
        daily_ohlcv = _daily_ohlcv(pd.Series([100.0, 101.0]))

        assert evaluate_impulse(daily_ohlcv) == expected

    def test_empty_frame_is_blue_without_calling_indicators(self, mocker) -> None:
        ema_mock = mocker.patch("app.signals.impulse.ema")
        histogram_mock = mocker.patch("app.signals.impulse.macd_histogram")
        direction_mock = mocker.patch("app.signals.impulse._direction")
        daily_ohlcv = _daily_ohlcv(pd.Series([], dtype=float))

        assert evaluate_impulse(daily_ohlcv) == "BLUE"
        ema_mock.assert_not_called()
        histogram_mock.assert_not_called()
        direction_mock.assert_not_called()

    def test_single_row_frame_is_blue_without_calling_indicators(self, mocker) -> None:
        ema_mock = mocker.patch("app.signals.impulse.ema")
        histogram_mock = mocker.patch("app.signals.impulse.macd_histogram")
        direction_mock = mocker.patch("app.signals.impulse._direction")
        daily_ohlcv = _daily_ohlcv(pd.Series([100.0]))

        assert evaluate_impulse(daily_ohlcv) == "BLUE"
        ema_mock.assert_not_called()
        histogram_mock.assert_not_called()
        direction_mock.assert_not_called()


class TestEvaluateImpulseEndToEnd:
    """Real (unmocked) composition of evaluate_impulse -> ema/macd_histogram -> _direction,
    over small synthetic daily series -- confirms the actual wiring, not just the decision
    table in isolation. Growth/decline rates and lengths were chosen empirically (see
    comments) by running the real indicator functions, not hand-derived by algebra -- each
    test asserts the qualifying facts it relies on (both directions individually), not just
    the final color, so a future change to ema()/macd_histogram() that breaks the scenario
    fails loudly here rather than silently.
    """

    def test_green_on_strong_accelerating_uptrend(self) -> None:
        """30 days of 5%/day compounding growth (100 * 1.05**i): fast momentum keeps both
        EMA(13) and the daily MACD-Histogram rising bar-over-bar.
        """
        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_histogram as real_macd_histogram

        closes = pd.Series([100 * (1.05**i) for i in range(30)], dtype=float)
        daily_ohlcv = _daily_ohlcv(closes)

        assert _direction(real_ema(closes, 13)) == "rising"
        assert _direction(real_macd_histogram(closes)) == "rising"
        assert evaluate_impulse(daily_ohlcv) == "GREEN"

    def test_red_on_sustained_decline(self) -> None:
        """60 days of 3%/day compounding decline (1000 * 0.97**i): sustained decline keeps
        both EMA(13) and the daily MACD-Histogram falling bar-over-bar.
        """
        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_histogram as real_macd_histogram

        closes = pd.Series([1000 * (0.97**i) for i in range(60)], dtype=float)
        daily_ohlcv = _daily_ohlcv(closes)

        assert _direction(real_ema(closes, 13)) == "falling"
        assert _direction(real_macd_histogram(closes)) == "falling"
        assert evaluate_impulse(daily_ohlcv) == "RED"

    def test_blue_on_genuine_disagreement_slowing_uptrend(self) -> None:
        """30 days of mild 1%/day compounding growth (100 * 1.01**i): price is still
        rising bar-over-bar (so EMA(13) is rising too), but the growth rate is too gentle
        to keep pulling the fast EMA away from the slow EMA -- the daily MACD-Histogram's
        last step is falling (decelerating momentum), a genuine directional disagreement
        rather than a mocked one.
        """
        from app.indicators.ema import ema as real_ema
        from app.indicators.macd import macd_histogram as real_macd_histogram

        closes = pd.Series([100 * (1.01**i) for i in range(30)], dtype=float)
        daily_ohlcv = _daily_ohlcv(closes)

        assert _direction(real_ema(closes, 13)) == "rising"
        assert _direction(real_macd_histogram(closes)) == "falling"
        assert evaluate_impulse(daily_ohlcv) == "BLUE"

    def test_blue_on_empty_history(self) -> None:
        daily_ohlcv = _daily_ohlcv(pd.Series([], dtype=float))

        assert evaluate_impulse(daily_ohlcv) == "BLUE"

    def test_blue_on_single_day_history(self) -> None:
        daily_ohlcv = _daily_ohlcv(pd.Series([100.0]))

        assert evaluate_impulse(daily_ohlcv) == "BLUE"
