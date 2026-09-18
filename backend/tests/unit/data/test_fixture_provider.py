"""Tests for FixtureDataProvider (app/data/fixture_provider.py) -- the deterministic,
no-network DataProvider used only by the frontend e2e suite (frontend-e2e-tests task).

No mocking needed anywhere in this file: FixtureDataProvider makes no I/O calls at all
(that's the whole point), so exercising the real class directly still satisfies
docs/architecture/Testing.md's "no live network calls in any test" rule.
"""

import pandas as pd
import pytest

from app.data.exceptions import TickerNotFoundError
from app.data.fixture_provider import _FIXTURE_TICKERS, FixtureDataProvider


class TestKnownTickers:
    @pytest.mark.parametrize("ticker", sorted(_FIXTURE_TICKERS))
    def test_daily_ohlcv_is_well_formed_for_every_known_ticker(self, ticker: str) -> None:
        frame = FixtureDataProvider().get_daily_ohlcv(ticker)

        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.is_monotonic_increasing  # oldest first, per DataProvider's contract
        assert len(frame) > 0
        assert frame[["open", "high", "low", "close", "volume"]].notna().all().all()
        # high/low must actually bound open/close, not just be plausible-looking numbers.
        assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
        assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
        assert (frame["low"] > 0).all()

    @pytest.mark.parametrize("ticker", sorted(_FIXTURE_TICKERS))
    def test_weekly_ohlcv_has_enough_bars_for_screen_1(self, ticker: str) -> None:
        # Analyse.md §8: Screen 1 needs >= 26 weeks of history to seed its 26-week EMA --
        # matches YFinanceProvider/StooqProvider's own _MIN_WEEKLY_BARS check.
        frame = FixtureDataProvider().get_weekly_ohlcv(ticker)

        assert len(frame) >= 26
        assert frame.index.name == "date"
        assert frame.index.is_monotonic_increasing

    def test_lowercase_ticker_is_treated_case_insensitively(self) -> None:
        upper = FixtureDataProvider().get_daily_ohlcv("AAPL")
        lower = FixtureDataProvider().get_daily_ohlcv("aapl")

        pd.testing.assert_frame_equal(upper, lower)

    def test_repeated_calls_are_deterministic(self) -> None:
        """Two independent calls (even from two separate instances) for the same ticker
        must produce byte-identical output -- FixtureDataProvider carries no mutable
        state and seeds its RNG from the ticker name alone."""
        first = FixtureDataProvider().get_daily_ohlcv("MSFT")
        second = FixtureDataProvider().get_daily_ohlcv("MSFT")

        pd.testing.assert_frame_equal(first, second)

    def test_different_tickers_produce_different_series(self) -> None:
        aapl = FixtureDataProvider().get_daily_ohlcv("AAPL")
        msft = FixtureDataProvider().get_daily_ohlcv("MSFT")

        assert not aapl["close"].reset_index(drop=True).equals(msft["close"].reset_index(drop=True))

    def test_uptrend_ticker_ends_higher_than_it_starts(self) -> None:
        """AAPL's fixture spec has a strongly positive drift_per_day -- confirms the
        noise amplitude doesn't overwhelm the intended trend direction."""
        frame = FixtureDataProvider().get_daily_ohlcv("AAPL")

        assert frame["close"].iloc[-1] > frame["close"].iloc[0]

    def test_downtrend_ticker_ends_lower_than_it_starts(self) -> None:
        """TSLA's fixture spec has a negative drift_per_day."""
        frame = FixtureDataProvider().get_daily_ohlcv("TSLA")

        assert frame["close"].iloc[-1] < frame["close"].iloc[0]


class TestUnknownTicker:
    def test_daily_ohlcv_raises_ticker_not_found(self) -> None:
        with pytest.raises(TickerNotFoundError):
            FixtureDataProvider().get_daily_ohlcv("ZZZZINVALID")

    def test_weekly_ohlcv_raises_ticker_not_found(self) -> None:
        with pytest.raises(TickerNotFoundError):
            FixtureDataProvider().get_weekly_ohlcv("ZZZZINVALID")
