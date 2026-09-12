"""Reference-value tests for app.indicators.ema (docs/Analyse.md §4: EMA periods 13, 26).

Formula under test: EMA_0 = close_0; EMA_t = close_t * k + EMA_{t-1} * (1 - k),
with k = 2 / (period + 1) — the standard recursive EMA definition, seeded with
the first observed price (see the decision recorded on docs/tasks/indicator-ema.json
for why the first-value seed was chosen over an SMA warm-up seed).
"""

import pandas as pd
import pytest

from app.indicators.ema import ema


class TestEma:
    def test_reference_values_period_3(self) -> None:
        """period=3 -> k = 2/(3+1) = 0.5, hand-computed by the recursive formula:

        EMA_0 = 10
        EMA_1 = 12*0.5 + 10*0.5    = 11.0
        EMA_2 = 15*0.5 + 11.0*0.5  = 13.0
        EMA_3 = 14*0.5 + 13.0*0.5  = 13.5
        EMA_4 = 13*0.5 + 13.5*0.5  = 13.25
        EMA_5 = 16*0.5 + 13.25*0.5 = 14.625
        EMA_6 = 18*0.5 + 14.625*0.5 = 16.3125
        EMA_7 = 17*0.5 + 16.3125*0.5 = 16.65625
        """
        closes = pd.Series([10, 12, 15, 14, 13, 16, 18, 17], dtype=float)

        result = ema(closes, period=3)

        assert isinstance(result, pd.Series)
        assert len(result) == len(closes)
        assert result.iloc[0] == pytest.approx(10.0)
        assert result.iloc[2] == pytest.approx(13.0)
        assert result.iloc[4] == pytest.approx(13.25)
        assert result.iloc[7] == pytest.approx(16.65625)

    def test_constant_series_is_steady_state_for_period_13(self) -> None:
        """A constant input is already at EMA steady state: k*c + (1-k)*c == c
        for any k, so EMA(13) of a flat series equals that constant at every
        point. Exercises the period actually used for the Impulse gate/tide.
        """
        closes = pd.Series([50.0] * 20)

        result = ema(closes, period=13)

        assert (result == 50.0).all()

    def test_period_26_matches_hand_computed_first_three_points(self) -> None:
        """period=26 -> k = 2/27, hand-computed for the first three points only
        (the warm-up window most likely to hide an off-by-one in the recursion).

        EMA_0 = 100
        EMA_1 = 102 * (2/27) + 100 * (25/27) = 100.14814814814815
        EMA_2 = 101 * (2/27) + EMA_1 * (25/27) = 100.21124828532237
        """
        closes = pd.Series([100, 102, 101, 105, 103], dtype=float)

        result = ema(closes, period=26)

        assert result.iloc[0] == pytest.approx(100.0)
        assert result.iloc[1] == pytest.approx(100.14814814814815)
        assert result.iloc[2] == pytest.approx(100.21124828532237)

    def test_rejects_non_positive_period(self) -> None:
        closes = pd.Series([1.0, 2.0, 3.0])

        with pytest.raises(ValueError):
            ema(closes, period=0)
