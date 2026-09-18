"""Shared contract test: every `DataProvider` implementation must be
interchangeable behind app/data/base.py's protocol (docs/architecture/Backend.md
§2: "yfinance and stooq are interchangeable and both are mockable in tests via
the same fake").

Both StooqProvider and YFinanceProvider are registered in `_PROVIDER_CLASSES`
below, each with its own mocked-fetch fixture, so the shape assertions in
`TestProvidersProduceIdenticallyShapedOutput` run cross-provider rather than
Stooq-only -- see this task's (data-provider-stooq-followups) `decisions`
entry for why this was updated after data-provider-yfinance merged to main.
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.data.base import DataProvider
from app.data.fixture_provider import FixtureDataProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"
STOOQ_FIXTURES_DIR = FIXTURES_DIR / "stooq"
YFINANCE_FIXTURES_DIR = FIXTURES_DIR / "yfinance"

# FixtureDataProvider (app/data/fixture_provider.py) is included here too: it's a third real
# DataProvider implementation (used by the frontend e2e suite, not the live app), so the same
# interchangeability contract applies to it -- see this task's (frontend-e2e-tests) `decisions`
# entry.
_PROVIDER_CLASSES = [StooqProvider, YFinanceProvider, FixtureDataProvider]

_PROTOCOL_METHODS = ["get_daily_ohlcv", "get_weekly_ohlcv"]


class TestProviderProtocolConformance:
    """Every provider must implement DataProvider's methods with matching signatures."""

    @pytest.mark.parametrize("provider_cls", _PROVIDER_CLASSES)
    def test_implements_every_protocol_method(self, provider_cls) -> None:
        # app/data/base.py's DataProvider is a plain (non-runtime_checkable)
        # Protocol, so this checks structurally rather than via isinstance().
        for method_name in _PROTOCOL_METHODS:
            assert callable(getattr(provider_cls, method_name, None))

    @pytest.mark.parametrize("provider_cls", _PROVIDER_CLASSES)
    @pytest.mark.parametrize("method_name", _PROTOCOL_METHODS)
    def test_method_signature_matches_protocol(self, provider_cls, method_name) -> None:
        protocol_sig = inspect.signature(getattr(DataProvider, method_name))
        impl_sig = inspect.signature(getattr(provider_cls, method_name))

        # Compare parameter names (drop `self`) rather than full Signature
        # equality, since return-type annotations/defaults aren't part of
        # the interchangeability contract, just the call shape.
        assert list(protocol_sig.parameters) == list(impl_sig.parameters)


def _load_yfinance_fixture(name: str) -> pd.DataFrame:
    """Load a recorded yfinance ``Ticker.history()`` response from CSV.

    Mirrors test_yfinance_provider.py's ``_load_fixture`` -- duplicated
    rather than imported so this contract test stays self-contained and
    doesn't depend on another test module's internals.
    """
    df = pd.read_csv(YFINANCE_FIXTURES_DIR / f"{name}.csv", index_col="Date")
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


class TestProvidersProduceIdenticallyShapedOutput:
    """Every provider's output must satisfy the same shape contract from
    app/data/base.py: columns open/high/low/close/volume, index named 'date'.
    """

    def test_stooq_daily_output_matches_protocol_shape(self, mocker) -> None:
        text = (STOOQ_FIXTURES_DIR / "aapl_daily.csv").read_text()
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"

    def test_stooq_weekly_output_matches_protocol_shape(self, mocker) -> None:
        text = (STOOQ_FIXTURES_DIR / "aapl_daily.csv").read_text()
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_weekly_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"

    def test_yfinance_daily_output_matches_protocol_shape(self, mocker) -> None:
        raw = _load_yfinance_fixture("aapl_daily")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"

    def test_yfinance_weekly_output_matches_protocol_shape(self, mocker) -> None:
        raw = _load_yfinance_fixture("aapl_weekly")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = raw
        mocker.patch("app.data.yfinance_provider.yf.Ticker", return_value=mock_ticker)

        result = YFinanceProvider().get_weekly_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"

    def test_fixture_daily_output_matches_protocol_shape(self) -> None:
        result = FixtureDataProvider().get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"

    def test_fixture_weekly_output_matches_protocol_shape(self) -> None:
        result = FixtureDataProvider().get_weekly_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"
