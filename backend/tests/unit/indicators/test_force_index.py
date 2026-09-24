"""Reference-value tests for app.indicators.force_index (docs/Analyse.md §2/§4:
Force Index = Volume x price change, EMA-smoothed with 2-period EMA for entry
timing and 13-period EMA for trend confirmation).

Formula under test:
    raw_t   = volume_t * (close_t - close_{t-1})   (undefined/NaN for bar 0)
    fi_t    = EMA(raw, ema_period), using the same recursive definition as
              app.indicators.ema (k = 2 / (ema_period + 1), seeded with the
              first non-NaN raw value; see the decision recorded on
              docs/tasks/indicator-ema.json for why first-value seeding was
              chosen over an SMA warm-up seed -- the same convention is
              reused here for consistency).

Reference values below were hand-computed with the recursive EMA formula
independently of app.indicators.force_index's pandas.ewm-based implementation
(worked by hand, then cross-checked with a standalone Python loop that does
not call ewm), for the fixture:

    closes  = [10, 12, 11, 13, 12, 15, 14, 16]
    volumes = [1000, 1500, 1200, 1800, 1300, 2000, 1100, 1900]
    diff    = [ -, 2, -1, 2, -1, 3, -1, 2]
    raw     = [ -, 3000, -1200, 3600, -1300, 6000, -1100, 3800]
"""

import pandas as pd
import pytest

from app.indicators.force_index import force_index

CLOSES = pd.Series([10, 12, 11, 13, 12, 15, 14, 16], dtype=float)
VOLUMES = pd.Series([1000, 1500, 1200, 1800, 1300, 2000, 1100, 1900], dtype=float)


class TestForceIndex:
    def test_first_bar_is_nan_no_prior_close(self) -> None:
        """Bar 0 has no prior close, so raw Force Index (and hence its EMA)
        is undefined for both smoothing periods."""
        result_2 = force_index(CLOSES, VOLUMES, ema_period=2)
        result_13 = force_index(CLOSES, VOLUMES, ema_period=13)

        assert pd.isna(result_2.iloc[0])
        assert pd.isna(result_13.iloc[0])

    def test_reference_values_ema_period_2(self) -> None:
        """period=2 -> k = 2/(2+1) = 2/3, hand-computed by the recursive
        formula, seeded at bar 1 (first non-NaN raw value = 3000):

        fi_1 = 3000                                            (seed)
        fi_2 = -1200*(2/3) + 3000*(1/3)     = 200
        fi_3 = 3600*(2/3) + 200*(1/3)       = 2466.666666666667
        fi_4 = -1300*(2/3) + 2466.6667*(1/3) = -44.44444444444
        fi_5 = 6000*(2/3) + -44.4444*(1/3)   = 3985.185185185185
        fi_6 = -1100*(2/3) + 3985.1852*(1/3) = 595.0617283950619
        fi_7 = 3800*(2/3) + 595.0617*(1/3)   = 2731.6872427983535
        """
        result = force_index(CLOSES, VOLUMES, ema_period=2)

        assert result.iloc[1] == pytest.approx(3000.0)
        assert result.iloc[2] == pytest.approx(200.0000000000001)
        assert result.iloc[3] == pytest.approx(2466.6666666666665)
        assert result.iloc[4] == pytest.approx(-44.44444444444434)
        assert result.iloc[5] == pytest.approx(3985.185185185185)
        assert result.iloc[6] == pytest.approx(595.0617283950619)
        assert result.iloc[7] == pytest.approx(2731.6872427983535)

    def test_reference_values_ema_period_13(self) -> None:
        """period=13 -> k = 2/(13+1) = 1/7, hand-computed by the recursive
        formula, seeded at bar 1 (first non-NaN raw value = 3000):

        fi_1 = 3000                                              (seed)
        fi_2 = -1200*(1/7) + 3000*(6/7)      = 2400.0
        fi_3 = 3600*(1/7) + 2400*(6/7)       = 2571.4285714285716
        fi_4 = -1300*(1/7) + 2571.4286*(6/7) = 2018.3673469387759
        fi_5 = 6000*(1/7) + 2018.3673*(6/7)  = 2587.172011661808
        fi_6 = -1100*(1/7) + 2587.1720*(6/7) = 2060.4331528529783
        fi_7 = 3800*(1/7) + 2060.4332*(6/7)  = 2308.94270244541
        """
        result = force_index(CLOSES, VOLUMES, ema_period=13)

        assert result.iloc[1] == pytest.approx(3000.0)
        assert result.iloc[2] == pytest.approx(2400.0)
        assert result.iloc[3] == pytest.approx(2571.4285714285716)
        assert result.iloc[4] == pytest.approx(2018.3673469387759)
        assert result.iloc[5] == pytest.approx(2587.172011661808)
        assert result.iloc[6] == pytest.approx(2060.4331528529783)
        assert result.iloc[7] == pytest.approx(2308.94270244541)

    def test_negative_price_change_yields_negative_raw_value(self) -> None:
        """A down day (close falls) with positive volume produces a negative
        raw Force Index -- the sign convention Analyse.md relies on to flag
        selling spikes in a downtrend / buying dips in an uptrend."""
        result = force_index(CLOSES, VOLUMES, ema_period=2)

        # bar 2: close 11 < close 10 at bar 1's predecessor... actually bar 2
        # is close_2=11 vs close_1=12, a decline, volume 1200 -> raw = -1200,
        # which pulls the still-warming-up EMA down from its bar-1 seed of 3000.
        assert result.iloc[2] < result.iloc[1]

    def test_rejects_non_positive_ema_period(self) -> None:
        with pytest.raises(ValueError):
            force_index(CLOSES, VOLUMES, ema_period=0)

    def test_rejects_mismatched_lengths(self) -> None:
        with pytest.raises(ValueError):
            force_index(CLOSES, VOLUMES.iloc[:-1], ema_period=13)

    def test_rejects_index_misalignment_even_with_equal_length(self) -> None:
        """close and volume with the same length but offset index labels
        must raise rather than silently combine via pandas' label-based
        alignment (volume * close.diff() would otherwise shift one series
        relative to the other and produce a wrong result with no error)."""
        offset_volumes = VOLUMES.copy()
        offset_volumes.index = offset_volumes.index + 1

        with pytest.raises(ValueError):
            force_index(CLOSES, offset_volumes, ema_period=2)

    def test_rejects_non_integer_ema_period(self) -> None:
        """ema_period is documented as int; a float like 13.5 must be
        rejected explicitly rather than silently passed through to
        app.indicators.ema.ema's own ewm-based span coercion."""
        with pytest.raises(TypeError):
            force_index(CLOSES, VOLUMES, ema_period=13.5)

    def test_rejects_bool_ema_period(self) -> None:
        """bool is a subclass of int in Python; ema_period=True must not be
        silently accepted as ema_period=1."""
        with pytest.raises(TypeError):
            force_index(CLOSES, VOLUMES, ema_period=True)
