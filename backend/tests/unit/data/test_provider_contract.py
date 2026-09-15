"""Shared contract test: every `DataProvider` implementation must be
interchangeable behind app/data/base.py's protocol (docs/architecture/Backend.md
§2: "yfinance and stooq are interchangeable and both are mockable in tests via
the same fake").

Only StooqProvider is registered here for now: `app/data/yfinance_provider.py`
on `main` is still the unimplemented stub raised in the data-provider-yfinance
task (not yet merged as of this task), so there's nothing real to compare
Stooq against yet. Once that task lands, add `YFinanceProvider` to
`_PROVIDER_CLASSES` below (with its own mocked-fetch fixture) so the shape
assertions in `TestProvidersProduceIdenticallyShapedOutput` run cross-provider
-- see this task's `decisions` entry for the full rationale.
"""

import inspect
from pathlib import Path

import pytest

from app.data.base import DataProvider
from app.data.stooq_provider import StooqProvider

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "stooq"

_PROVIDER_CLASSES = [StooqProvider]

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


class TestProvidersProduceIdenticallyShapedOutput:
    """Every provider's output must satisfy the same shape contract from
    app/data/base.py: columns open/high/low/close/volume, index named 'date'.
    """

    def test_stooq_daily_output_matches_protocol_shape(self, mocker) -> None:
        text = (FIXTURES_DIR / "aapl_daily.csv").read_text()
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"

    def test_stooq_weekly_output_matches_protocol_shape(self, mocker) -> None:
        text = (FIXTURES_DIR / "aapl_daily.csv").read_text()
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_weekly_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"
