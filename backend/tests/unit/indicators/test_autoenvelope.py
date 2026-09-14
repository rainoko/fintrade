"""Reference-value tests for app.indicators.autoenvelope (docs/Analyse.md §4:
Autoenvelope / Channel = EMA 13 ± avg % deviation).

Formula under test:
    mid_t        = EMA(close, ema_period)   -- same recursive EMA as
                   app.indicators.ema (first-value seed, k = 2/(period+1))
    pct_dev_t    = |close_t - mid_t| / mid_t
    avg_pct_t    = trailing rolling mean of pct_dev over the last
                   `deviation_lookback` bars (undefined/NaN until the window
                   is full)
    upper_t      = mid_t * (1 + avg_pct_t)
    lower_t      = mid_t * (1 - avg_pct_t)

Reference values below were hand-computed independently of
app.indicators.autoenvelope's pandas-based implementation, via a standalone
Python loop (no pandas, no ewm/rolling) for the fixture:

    closes = [10, 12, 15, 14, 13, 16, 18, 17]   (same fixture as
              test_ema.py's period=3 case, reused for cross-checkable EMA
              values: ema = [10, 11.0, 13.0, 13.5, 13.25, 14.625, 16.3125,
              16.65625])
    ema_period = 3, deviation_lookback = 3

    pct_dev = [0.0, 0.09090909090909091, 0.15384615384615385,
               0.037037037037037035, 0.018867924528301886,
               0.09401709401709402, 0.10344827586206896,
               0.020637898686679174]

    avg (rolling mean of pct_dev, window=3, first full window at index 2):
        avg[2] = mean(pct_dev[0:3])  = 0.08158508158508158
        avg[3] = mean(pct_dev[1:4])  = 0.09393076059742726
        avg[4] = mean(pct_dev[2:5])  = 0.06991703847049759
        avg[5] = mean(pct_dev[3:6])  = 0.04997401852747765
        avg[6] = mean(pct_dev[4:7])  = 0.07211109813582163
        avg[7] = mean(pct_dev[5:8])  = 0.07270108952194738

    upper/lower = mid * (1 +/- avg):
        t=2: mid=13.0,     upper=14.06060606060606,  lower=11.93939393939394
        t=3: mid=13.5,     upper=14.76806526806527,  lower=12.231934731934732
        t=4: mid=13.25,    upper=14.176400759734094, lower=12.323599240265906
        t=5: mid=14.625,   upper=15.355870020964362, lower=13.89412997903564
        t=6: mid=16.3125,  upper=17.488812288340593, lower=15.13618771165941
        t=7: mid=16.65625, upper=17.867177522349934, lower=15.445322477650063
"""

import pandas as pd
import pytest

from app.indicators.autoenvelope import autoenvelope


CLOSES = pd.Series([10, 12, 15, 14, 13, 16, 18, 17], dtype=float)


class TestAutoenvelope:
    def test_mid_matches_ema(self) -> None:
        """'mid' is exactly EMA(close, ema_period), reusing app.indicators.ema."""
        result = autoenvelope(CLOSES, ema_period=3, deviation_lookback=3)

        expected_mid = [10, 11.0, 13.0, 13.5, 13.25, 14.625, 16.3125, 16.65625]
        for i, expected in enumerate(expected_mid):
            assert result["mid"].iloc[i] == pytest.approx(expected)

    def test_upper_lower_are_nan_before_full_deviation_window(self) -> None:
        """The rolling average deviation needs `deviation_lookback` bars of
        history; before that, 'mid' is defined but 'upper'/'lower' are NaN."""
        result = autoenvelope(CLOSES, ema_period=3, deviation_lookback=3)

        assert result["upper"].iloc[0:2].isna().all()
        assert result["lower"].iloc[0:2].isna().all()
        assert not pd.isna(result["mid"].iloc[0])
        assert not pd.isna(result["mid"].iloc[1])

    def test_reference_values_upper_lower(self) -> None:
        result = autoenvelope(CLOSES, ema_period=3, deviation_lookback=3)

        expected_upper = {
            2: 14.06060606060606,
            3: 14.76806526806527,
            4: 14.176400759734094,
            5: 15.355870020964362,
            6: 17.488812288340593,
            7: 17.867177522349934,
        }
        expected_lower = {
            2: 11.93939393939394,
            3: 12.231934731934732,
            4: 12.323599240265906,
            5: 13.89412997903564,
            6: 15.13618771165941,
            7: 15.445322477650063,
        }

        for i, expected in expected_upper.items():
            assert result["upper"].iloc[i] == pytest.approx(expected)
        for i, expected in expected_lower.items():
            assert result["lower"].iloc[i] == pytest.approx(expected)

    def test_upper_above_mid_above_lower_when_deviation_nonzero(self) -> None:
        result = autoenvelope(CLOSES, ema_period=3, deviation_lookback=3)

        for i in range(2, len(CLOSES)):
            assert result["lower"].iloc[i] < result["mid"].iloc[i] < result["upper"].iloc[i]

    def test_zero_deviation_collapses_bands_onto_mid(self) -> None:
        """A perfectly flat series has zero deviation from its own EMA at
        every bar, so upper == mid == lower once the window is full."""
        flat = pd.Series([50.0] * 10)

        result = autoenvelope(flat, ema_period=3, deviation_lookback=3)

        assert result["upper"].iloc[3:].eq(50.0).all()
        assert result["lower"].iloc[3:].eq(50.0).all()

    def test_default_lookback_is_100(self) -> None:
        """deviation_lookback defaults to 100 (docs/tasks/indicator-autoenvelope.json
        decision) -- a series shorter than that has no defined band yet."""
        result = autoenvelope(CLOSES, ema_period=3)

        assert result["upper"].isna().all()
        assert result["lower"].isna().all()

    def test_rejects_non_positive_deviation_lookback(self) -> None:
        with pytest.raises(ValueError):
            autoenvelope(CLOSES, ema_period=3, deviation_lookback=0)

    def test_rejects_non_integer_deviation_lookback(self) -> None:
        with pytest.raises(TypeError):
            autoenvelope(CLOSES, ema_period=3, deviation_lookback=10.5)

    def test_rejects_bool_deviation_lookback(self) -> None:
        """bool is a subclass of int in Python; deviation_lookback=True must
        not be silently accepted as deviation_lookback=1."""
        with pytest.raises(TypeError):
            autoenvelope(CLOSES, ema_period=3, deviation_lookback=True)

    def test_propagates_ema_period_validation(self) -> None:
        """ema_period validation is delegated to app.indicators.ema; a bad
        period must still raise, not be silently swallowed."""
        with pytest.raises(ValueError):
            autoenvelope(CLOSES, ema_period=0, deviation_lookback=3)

        with pytest.raises(TypeError):
            autoenvelope(CLOSES, ema_period=13.5, deviation_lookback=3)
