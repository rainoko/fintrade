"""Tests for app.data.ibkr_data_provider (backend-ibkr-primary-data-provider).

Per docs/architecture/Testing.md, mocks `IBKRProvider._request` (the one method that
performs a real HTTP call) and `IBKRProvider.get_gateway_status` -- the same boundary
tests/unit/data/test_ibkr_provider.py itself uses -- rather than ever reaching a real
gateway. `tests/unit/data/test_provider_contract.py` separately covers
`IBKRDataProvider`'s `DataProvider`-protocol conformance and basic output shape; this
module covers its own behavior in depth (conid resolution/error-mapping/the
`get_extended_data` carve-out), plus `IBKRPrimaryDataProvider`'s routing.
"""

import pandas as pd
import pytest

from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.ibkr_data_provider import IBKRDataProvider, IBKRPrimaryDataProvider
from app.data.ibkr_provider import IBKRProvider, IBKRUnavailableError


def _available(mocker) -> None:
    mocker.patch(
        "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
        return_value=mocker.Mock(state="available", detail=None),
    )


def _bars_payload(count: int, *, start_t: int = 1665149400000, step_ms: int = 86_400_000) -> dict:
    return {
        "data": [
            {
                "t": start_t + i * step_ms,
                "o": 100.0 + i,
                "h": 101.0 + i,
                "l": 99.0 + i,
                "c": 100.5 + i,
                "v": 1000.0 + i,
            }
            for i in range(count)
        ]
    }


_SEARCH_SINGLE_MATCH = [{"conid": "265598", "symbol": "AAPL", "sections": [{"secType": "STK"}]}]
_SEARCH_NO_MATCH: list = []
_SEARCH_AMBIGUOUS = [
    {"conid": "1", "symbol": "BAR", "sections": [{"secType": "STK"}]},
    {"conid": "2", "symbol": "BAR", "sections": [{"secType": "STK"}]},
]


class TestGetDailyOhlcv:
    def test_resolves_conid_and_returns_bars(self, mocker) -> None:
        _available(mocker)
        payload = _bars_payload(5)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else payload,
        )

        result = IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"
        assert len(result) == 5
        assert result.index.is_monotonic_increasing
        assert result.index.tz is None

    def test_unresolvable_ticker_raises_ticker_not_found(self, mocker) -> None:
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_NO_MATCH,
        )

        with pytest.raises(TickerNotFoundError):
            IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("NOSUCHTICKER")

    def test_ambiguous_ticker_raises_ticker_not_found(self, mocker) -> None:
        """An ambiguous resolution (`resolve_conid` returning `None` for a ticker with
        more than one distinct listed conid -- e.g. a cross-listed ticker like AAPL
        itself was found to be, live, during this task's own research) degrades to the
        same `TickerNotFoundError` as a genuinely unknown ticker: from this provider's own
        perspective, both mean "no usable data for this ticker", mirroring every other
        `DataProvider`'s `TickerNotFoundError` semantics (app/data/exceptions.py)."""
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_AMBIGUOUS,
        )

        with pytest.raises(TickerNotFoundError):
            IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("BAR")

    def test_resolved_conid_with_no_bars_raises_ticker_not_found(self, mocker) -> None:
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else {"data": []},
        )

        with pytest.raises(TickerNotFoundError):
            IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("AAPL")

    def test_gateway_unavailable_raises_data_provider_unavailable(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="gateway_unreachable", detail="down"),
        )

        with pytest.raises(DataProviderUnavailableError):
            IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("AAPL")

    def test_per_call_failure_raises_data_provider_unavailable_not_ibkr_specific_error(
        self, mocker
    ) -> None:
        """Callers of this class (e.g. `CachedDataProvider`) expect the shared
        `app.data.exceptions` hierarchy, not `IBKRUnavailableError` -- this is the
        translation boundary that makes that true."""
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=IBKRUnavailableError("IBKR gateway returned HTTP 500 from /x"),
        )

        with pytest.raises(DataProviderUnavailableError):
            IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("AAPL")

    def test_requests_single_page_with_long_period(self, mocker) -> None:
        """Confirms `get_daily_ohlcv` goes through `IBKRProvider.get_daily_bars` (a single
        `bar="1d"` request), not `get_hourly_bars`'s pagination loop -- see
        `IBKRProvider.get_daily_bars`'s own docstring for why."""
        _available(mocker)
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else _bars_payload(3),
        )

        IBKRDataProvider(IBKRProvider()).get_daily_ohlcv("AAPL")

        history_calls = [c for c in request.call_args_list if c.args[1] == "/iserver/marketdata/history"]
        assert len(history_calls) == 1
        assert history_calls[0].kwargs["params"]["bar"] == "1d"


class TestGetWeeklyOhlcv:
    def test_returns_bars_when_above_minimum(self, mocker) -> None:
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else _bars_payload(26, step_ms=7 * 86_400_000),
        )

        result = IBKRDataProvider(IBKRProvider()).get_weekly_ohlcv("AAPL")

        assert len(result) == 26
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]

    def test_raises_insufficient_history_below_minimum(self, mocker) -> None:
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else _bars_payload(10, step_ms=7 * 86_400_000),
        )

        with pytest.raises(InsufficientHistoryError) as exc_info:
            IBKRDataProvider(IBKRProvider()).get_weekly_ohlcv("AAPL")

        assert exc_info.value.available == 10
        assert exc_info.value.required == 26

    def test_unresolvable_ticker_raises_ticker_not_found(self, mocker) -> None:
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_NO_MATCH,
        )

        with pytest.raises(TickerNotFoundError):
            IBKRDataProvider(IBKRProvider()).get_weekly_ohlcv("NOSUCHTICKER")

    def test_resolved_conid_with_no_bars_raises_ticker_not_found(self, mocker) -> None:
        _available(mocker)
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else {"data": []},
        )

        with pytest.raises(TickerNotFoundError):
            IBKRDataProvider(IBKRProvider()).get_weekly_ohlcv("AAPL")

    def test_requests_weekly_bar_size(self, mocker) -> None:
        _available(mocker)
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=lambda method, path, **kw: _SEARCH_SINGLE_MATCH
            if path == "/iserver/secdef/search"
            else _bars_payload(26, step_ms=7 * 86_400_000),
        )

        IBKRDataProvider(IBKRProvider()).get_weekly_ohlcv("AAPL")

        history_calls = [c for c in request.call_args_list if c.args[1] == "/iserver/marketdata/history"]
        assert len(history_calls) == 1
        assert history_calls[0].kwargs["params"]["bar"] == "1w"


class TestGetExtendedData:
    def test_always_reports_unavailable(self) -> None:
        """`IBKRDataProvider` alone has no extended-data source at all -- confirmed live
        during this task's own research (no IBKR Client Portal Web API equivalent to
        yfinance's calendar/info/insider_transactions fields). Never makes a request."""
        result = IBKRDataProvider(IBKRProvider()).get_extended_data("AAPL")

        assert result.unavailable_reason == "fallback_provider_active"
        assert result.earnings_date is None
        assert result.insider_transactions == []


class TestIBKRPrimaryDataProvider:
    """The composition `app.api.dependencies._build_ibkr_primary_data_provider` wires up --
    routes OHLCV to one `DataProvider`, extended data to a separate one."""

    def test_routes_daily_and_weekly_to_ohlcv_provider(self, mocker) -> None:
        ohlcv_provider = mocker.Mock()
        ohlcv_provider.get_daily_ohlcv.return_value = pd.DataFrame()
        ohlcv_provider.get_weekly_ohlcv.return_value = pd.DataFrame()
        extended_data_provider = mocker.Mock()

        provider = IBKRPrimaryDataProvider(ohlcv_provider, extended_data_provider)
        provider.get_daily_ohlcv("AAPL")
        provider.get_weekly_ohlcv("AAPL")

        ohlcv_provider.get_daily_ohlcv.assert_called_once_with("AAPL")
        ohlcv_provider.get_weekly_ohlcv.assert_called_once_with("AAPL")
        extended_data_provider.get_daily_ohlcv.assert_not_called()
        extended_data_provider.get_weekly_ohlcv.assert_not_called()

    def test_routes_extended_data_to_extended_data_provider_not_ohlcv_provider(self, mocker) -> None:
        ohlcv_provider = mocker.Mock()
        extended_data_provider = mocker.Mock()
        sentinel = object()
        extended_data_provider.get_extended_data.return_value = sentinel

        provider = IBKRPrimaryDataProvider(ohlcv_provider, extended_data_provider)
        result = provider.get_extended_data("AAPL")

        assert result is sentinel
        extended_data_provider.get_extended_data.assert_called_once_with("AAPL")
        ohlcv_provider.get_extended_data.assert_not_called()
