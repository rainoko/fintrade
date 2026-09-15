"""Reference-value tests for app.indicators.macd (docs/Analyse.md §2 & §4:
MACD-Histogram, periods 12/26/9).

MACD line = EMA(close, fast) - EMA(close, slow)
Signal line = EMA(MACD line, signal)
Histogram = MACD line - Signal line

macd_histogram() is built on top of app.indicators.ema.ema (already covered
by hand-computed reference tests in test_ema.py), so this file hand-computes
with small custom periods (fast=2, slow=4, signal=3) to make the recursion
tractable by hand, then separately checks that the documented default
periods (12, 26, 9) are wired correctly by composing ema() directly in the
test -- an independent path from the implementation under test.
"""

import pandas as pd
import pytest

from app.indicators.ema import ema
from app.indicators.macd import macd_components, macd_histogram


class TestMacdHistogram:
    def test_reference_values_custom_periods(self) -> None:
        """fast=2 (k=2/3), slow=4 (k=2/5), signal=3 (k=1/2).

        EMA(fast=2):
          e2_0 = 10
          e2_1 = 12*(2/3) + 10*(1/3)      = 11.333333
          e2_2 = 15*(2/3) + 11.333333*(1/3) = 13.777778
          e2_3 = 14*(2/3) + 13.777778*(1/3) = 13.925926

        EMA(slow=4):
          e4_0 = 10
          e4_1 = 12*0.4 + 10*0.6         = 10.8
          e4_2 = 15*0.4 + 10.8*0.6       = 12.48
          e4_3 = 14*0.4 + 12.48*0.6      = 13.088

        MACD line = e2 - e4:
          macd_0 = 10 - 10           = 0.0
          macd_1 = 11.333333 - 10.8  = 0.533333
          macd_2 = 13.777778 - 12.48 = 1.297778
          macd_3 = 13.925926 - 13.088 = 0.837926

        Signal = EMA(macd line, signal=3), k=0.5:
          sig_0 = macd_0                        = 0.0
          sig_1 = macd_1*0.5 + sig_0*0.5         = 0.266667
          sig_2 = macd_2*0.5 + sig_1*0.5         = 0.782222
          sig_3 = macd_3*0.5 + sig_2*0.5         = 0.810074

        Histogram = macd - signal:
          hist_0 = 0.0 - 0.0             = 0.0
          hist_1 = 0.533333 - 0.266667   = 0.266667
          hist_2 = 1.297778 - 0.782222   = 0.515556
          hist_3 = 0.837926 - 0.810074   = 0.027852
        """
        closes = pd.Series([10, 12, 15, 14], dtype=float)

        result = macd_histogram(closes, fast=2, slow=4, signal=3)

        assert isinstance(result, pd.Series)
        assert len(result) == len(closes)
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(0.266667, abs=1e-6)
        assert result.iloc[2] == pytest.approx(0.515556, abs=1e-6)
        assert result.iloc[3] == pytest.approx(0.027852, abs=1e-6)

    def test_reference_values_continue_past_warmup(self) -> None:
        """Continues the same series/periods as the test above past the
        first four points, to exercise sign changes (positive -> negative
        histogram, the kind of crossing Screen 1's slope detection cares
        about) rather than only the warm-up window.

        Extending closes = [10, 12, 15, 14, 13, 16, 18, 17, 19, 20] and
        continuing the same recursion as above (e2_3 = 13.925926,
        e4_3 = 13.088, macd_3 = 0.837926, sig_3 = 0.810074) to index 4:
          e2_4 = 13*(2/3) + e2_3*(1/3)   = 13.308642
          e4_4 = 13*0.4 + e4_3*0.6       = 13.0528
          macd_4 = e2_4 - e4_4           = 0.255842
          sig_4 = macd_4*0.5 + sig_3*0.5 = 0.532958
          hist_4 = macd_4 - sig_4        = -0.277116

        Continuing the identical recursion four more steps to index 8
        (closes 16, 18, 17, 19) gives hist_8 = 0.053873.
        """
        closes = pd.Series([10, 12, 15, 14, 13, 16, 18, 17, 19, 20], dtype=float)

        result = macd_histogram(closes, fast=2, slow=4, signal=3)

        assert result.iloc[4] == pytest.approx(-0.277116, abs=1e-6)
        assert result.iloc[8] == pytest.approx(0.053873, abs=1e-6)

    def test_default_periods_are_12_26_9(self) -> None:
        """docs/Analyse.md §2 & §4 pin MACD-Histogram to (12, 26, 9) -- the
        defaults must match without callers having to pass them explicitly.
        Verified by composing ema() directly here (independent of
        macd_histogram's internals) rather than re-asserting fast/slow/signal
        values already covered by the hand-computed test above.
        """
        closes = pd.Series(
            [100 + i + (i % 3) * 0.7 for i in range(30)], dtype=float
        )

        result = macd_histogram(closes)

        expected_macd_line = ema(closes, 12) - ema(closes, 26)
        expected_signal_line = ema(expected_macd_line, 9)
        expected_histogram = expected_macd_line - expected_signal_line

        pd.testing.assert_series_equal(
            result, expected_histogram, check_names=False
        )

    def test_zero_at_first_point(self) -> None:
        """At index 0 every EMA involved is seeded with the same first
        value (per app.indicators.ema's first-value-seed convention), so
        MACD line, signal line, and therefore the histogram must all be
        exactly zero regardless of the periods used.
        """
        closes = pd.Series([42.0, 43.5, 41.0, 44.25, 45.0])

        result = macd_histogram(closes, fast=12, slow=26, signal=9)

        assert result.iloc[0] == pytest.approx(0.0)


class TestMacdComponents:
    """macd_components() exposes the intermediate EMAs alongside the histogram
    (app.signals.triple_screen.evaluate_tide needs EMA(slow) too, and would
    otherwise have to compute ema(close, 26) a second time -- see the
    screen1-tide task's `decisions` entry).
    """

    def test_histogram_matches_macd_histogram(self) -> None:
        """macd_histogram() is a thin wrapper over macd_components() -- both
        must agree exactly, not just approximately.
        """
        closes = pd.Series([10, 12, 15, 14, 13, 16, 18, 17, 19, 20], dtype=float)

        components = macd_components(closes, fast=2, slow=4, signal=3)
        standalone = macd_histogram(closes, fast=2, slow=4, signal=3)

        pd.testing.assert_series_equal(
            components.histogram, standalone, check_names=False
        )

    def test_exposes_fast_and_slow_ema(self) -> None:
        """ema_fast/ema_slow are exactly ema(close, fast)/ema(close, slow) --
        an independent path from the implementation under test.
        """
        closes = pd.Series([10, 12, 15, 14, 13, 16, 18, 17, 19, 20], dtype=float)

        components = macd_components(closes, fast=2, slow=4, signal=3)

        pd.testing.assert_series_equal(
            components.ema_fast, ema(closes, 2), check_names=False
        )
        pd.testing.assert_series_equal(
            components.ema_slow, ema(closes, 4), check_names=False
        )

    def test_macd_line_and_signal_line_reference_values(self) -> None:
        """Reuses TestMacdHistogram.test_reference_values_custom_periods'
        hand-computed macd_1/sig_1 values to check the intermediate series,
        not just the final histogram.
        """
        closes = pd.Series([10, 12, 15, 14], dtype=float)

        components = macd_components(closes, fast=2, slow=4, signal=3)

        assert components.macd_line.iloc[1] == pytest.approx(0.533333, abs=1e-6)
        assert components.signal_line.iloc[1] == pytest.approx(0.266667, abs=1e-6)
