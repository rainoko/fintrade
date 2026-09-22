"""Tests for app.data.ibkr_provider.IBKRProvider (docs/tasks/backend-ibkr-data-provider.json).

Per docs/architecture/Testing.md ("no live network calls in tests") and this task's own
`description` (no sandboxed/CI environment has a live authenticated gateway), every test
here mocks ``IBKRProvider._request`` -- the one method that performs a real HTTP call
against the gateway -- and feeds it canned payloads matching the documented Web API
response shapes (docs/ideas.md). A dedicated `TestRequest` class instead mocks the
underlying `httpx.Client` to exercise `_request` itself.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.data.ibkr_provider import (
    DEFAULT_BASE_URL,
    IBKRBar,
    IBKRProvider,
    IBKRRateLimitedError,
    IBKRUnavailableError,
    ScannerResult,
)


class _FakeClock:
    """Deterministic, manually-advanced stand-in for `time.monotonic` -- lets rate-limit
    tests assert exact boundary behavior without a real `time.sleep`."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TestGetGatewayStatus:
    def test_authenticated_true_is_available(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            return_value={"authenticated": True, "connected": True},
        )

        status = IBKRProvider().get_gateway_status()

        assert status.state == "available"

    def test_authenticated_false_is_not_authenticated(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            return_value={"authenticated": False, "message": "please log in"},
        )

        status = IBKRProvider().get_gateway_status()

        assert status.state == "not_authenticated"
        assert status.detail == "please log in"

    def test_unparseable_or_non_dict_payload_is_not_authenticated(self, mocker) -> None:
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=["unexpected"])

        status = IBKRProvider().get_gateway_status()

        assert status.state == "not_authenticated"
        assert status.detail is None

    def test_transport_failure_is_gateway_unreachable(self, mocker) -> None:
        """The gateway process not even running (the common local-dev case) is
        distinguishable from 'running but not logged in' -- checklist item 2."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=IBKRUnavailableError("connection refused"),
        )

        status = IBKRProvider().get_gateway_status()

        assert status.state == "gateway_unreachable"
        assert "connection refused" in status.detail

    def test_never_raises(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=IBKRUnavailableError("boom"),
        )

        # Would raise if get_gateway_status let the underlying error propagate.
        IBKRProvider().get_gateway_status()


class TestGetHourlyBars:
    @staticmethod
    def _bar_at(hours_ago: float, price: float = 100.0) -> dict:
        """A bar `hours_ago` hours before the current wall-clock time -- expressed
        relative to "now" (rather than a fixed historical epoch) so it sits at a known
        position relative to `get_hourly_bars`'s own `datetime.now(UTC)`-based cutoff
        regardless of when this test suite happens to run.
        """
        ts = datetime.now(UTC) - timedelta(hours=hours_ago)
        ts_ms = int(ts.timestamp() * 1000)
        return {"t": ts_ms, "o": price, "h": price + 1, "l": price - 1, "c": price + 0.5, "v": 1000}

    def test_raises_when_gateway_not_available(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="gateway_unreachable", detail="down"),
        )
        request = mocker.patch("app.data.ibkr_provider.IBKRProvider._request")

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider().get_hourly_bars("265598", lookback_days=5)

        request.assert_not_called()

    def test_single_page_returns_sorted_bars(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        # Deliberately out of order in the source payload -- result must still come back sorted.
        payload = {
            "data": [
                self._bar_at(hours_ago=1, price=102),
                self._bar_at(hours_ago=2, price=100),
            ]
        }
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=5)

        assert len(bars) == 2
        assert all(isinstance(b, IBKRBar) for b in bars)
        assert bars[0].timestamp < bars[1].timestamp
        assert bars[0].open == 100.0

    def test_requests_conid_and_hourly_bar_size(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            return_value={"data": [self._bar_at(hours_ago=1)]},
        )

        IBKRProvider().get_hourly_bars("265598", lookback_days=5)

        _method, path = request.call_args.args
        assert path == "/iserver/marketdata/history"
        assert request.call_args.kwargs["params"]["conid"] == "265598"
        assert request.call_args.kwargs["params"]["bar"] == "1h"

    def test_paginates_backward_when_first_page_is_full(self, mocker) -> None:
        """A full 1,000-bar first page (spanning ~41.6 days back, less than the 60-day
        lookback requested) must trigger a second call with a `startTime` cursor --
        checklist item 3's pagination requirement."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        first_page = {"data": [self._bar_at(hours_ago=i) for i in range(1000)]}
        second_page = {"data": [self._bar_at(hours_ago=1000)]}
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=[first_page, second_page],
        )

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=60)

        assert request.call_count == 2
        second_call_kwargs = request.call_args_list[1].kwargs
        assert "startTime" in second_call_kwargs["params"]
        assert len(bars) == 1001

    def test_full_page_with_one_malformed_row_still_paginates(self, mocker) -> None:
        """A raw page of exactly 1,000 rows (a genuinely full page, meaning more history
        may exist further back) that includes one malformed row must still trigger a
        second page -- the full/short-page decision has to be based on the RAW response
        row count, not `len(page_bars)` (the count AFTER `_parse_bars` drops the
        malformed row down to 999). Using the post-parse count would make this look like
        a short/final page and silently truncate history with no error surfaced."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        raw_rows = [self._bar_at(hours_ago=i) for i in range(999)]
        raw_rows.append({"t": 1_700_000_000_000})  # malformed: missing o/h/l/c/v
        assert len(raw_rows) == 1000  # a genuinely full raw page
        first_page = {"data": raw_rows}
        second_page = {"data": [self._bar_at(hours_ago=1000)]}
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=[first_page, second_page],
        )

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=60)

        assert request.call_count == 2
        second_call_kwargs = request.call_args_list[1].kwargs
        assert "startTime" in second_call_kwargs["params"]
        # 999 parsed from the first page (the malformed row dropped) + 1 from the second.
        assert len(bars) == 1000

    def test_stops_once_cutoff_reached_without_a_second_page(self, mocker) -> None:
        """A full 1,000-bar page spans ~41.6 days -- already past a 1-day lookback
        cutoff -- so pagination must stop after this one page despite it being full,
        rather than always continuing whenever a page happens to be full-sized."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        page_one = {"data": [self._bar_at(hours_ago=i) for i in range(1000)]}
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            side_effect=[page_one, AssertionError("should not fetch a second page")],
        )

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=1)

        assert request.call_count == 1
        # Only the bars within the last day survive the cutoff filter, not all 1,000.
        assert 0 < len(bars) < 30

    def test_empty_first_page_returns_empty_list(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value={"data": []})

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=5)

        assert bars == []

    def test_malformed_bar_rows_are_skipped_not_fatal(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {
            "data": [
                {"t": 1_700_000_000_000},  # missing o/h/l/c/v
                self._bar_at(hours_ago=1),
                "not even a dict",
            ]
        }
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=5)

        assert len(bars) == 1

    def test_non_dict_payload_returns_empty_list(self, mocker) -> None:
        """A response shape this provider doesn't recognize at all (not even the
        documented `{"data": [...]}` envelope) must degrade to an empty page rather
        than raising -- same treatment as a page with no bars."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=["unexpected"])

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=5)

        assert bars == []

    def test_stops_at_the_page_safety_bound_when_cutoff_is_never_reached(self, mocker) -> None:
        """A pathological lookback (or a source that never signals 'no more/short
        page') must still terminate at `_MAX_PAGINATION_PAGES`, not loop forever."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )

        def _full_page(*_args, **_kwargs) -> dict:
            # A fresh, always-full, always-further-back page every call -- `earliest`
            # never reaches the (huge) requested lookback's cutoff, and every bar is
            # new, so nothing but the page-count safety bound can stop this loop.
            call_index = request.call_count
            return {
                "data": [
                    self._bar_at(hours_ago=call_index * 1000 + i) for i in range(1000)
                ]
            }

        request = mocker.patch("app.data.ibkr_provider.IBKRProvider._request", side_effect=_full_page)

        bars = IBKRProvider().get_hourly_bars("265598", lookback_days=100_000)

        assert request.call_count == 20  # _MAX_PAGINATION_PAGES
        assert len(bars) == 20_000


class TestGetScannerParams:
    def test_raises_when_gateway_not_available(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="not_authenticated", detail=None),
        )

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider().get_scanner_params()

    def test_fetches_and_returns_params(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {"scan_type_list": [{"code": "TOP_PERC_GAIN"}]}
        request = mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        result = IBKRProvider().get_scanner_params()

        assert result == payload
        request.assert_called_once()

    def test_second_call_within_ttl_is_served_from_cache(self, mocker) -> None:
        clock = _FakeClock()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request", return_value={"scan_type_list": []}
        )
        provider = IBKRProvider(clock=clock)

        provider.get_scanner_params()
        clock.advance(60.0)  # well within the 15-minute TTL
        provider.get_scanner_params()

        request.assert_called_once()

    def test_call_after_ttl_expiry_refetches(self, mocker) -> None:
        clock = _FakeClock()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request", return_value={"scan_type_list": []}
        )
        provider = IBKRProvider(clock=clock)

        provider.get_scanner_params()
        clock.advance(15 * 60.0 + 1.0)
        provider.get_scanner_params()

        assert request.call_count == 2


class TestRunScanner:
    def test_raises_when_gateway_not_available(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="gateway_unreachable", detail=None),
        )

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider().run_scanner({"instrument": "STK", "type": "TOP_PERC_GAIN"})

    def test_posts_scan_config_and_parses_contracts(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {
            "contracts": [
                {"conid": 265598, "symbol": "AAPL", "companyName": "Apple Inc", "rank": 1},
                {"conid": 272093, "symbol": "MSFT", "companyName": "Microsoft Corp", "rank": 2},
            ]
        }
        request = mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)
        scan_config = {"instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR"}

        results = IBKRProvider().run_scanner(scan_config)

        assert results == [
            ScannerResult(conid=265598, symbol="AAPL", company_name="Apple Inc", rank=1),
            ScannerResult(conid=272093, symbol="MSFT", company_name="Microsoft Corp", rank=2),
        ]
        _method, path = request.call_args.args
        assert path == "/iserver/scanner/run"
        assert request.call_args.kwargs["json"] == scan_config

    def test_contracts_missing_conid_are_skipped(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {"contracts": [{"symbol": "NOCONID"}, {"conid": 1, "symbol": "OK"}]}
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        results = IBKRProvider().run_scanner({})

        assert len(results) == 1
        assert results[0].symbol == "OK"

    def test_non_dict_payload_returns_empty_list(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=["unexpected"])

        results = IBKRProvider().run_scanner({})

        assert results == []

    def test_non_dict_contract_rows_are_skipped(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {"contracts": ["not a dict", {"conid": 1, "symbol": "OK"}]}
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        results = IBKRProvider().run_scanner({})

        assert len(results) == 1
        assert results[0].symbol == "OK"

    def test_non_numeric_conid_is_skipped(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {"contracts": [{"conid": "not-a-number", "symbol": "BAD"}]}
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        results = IBKRProvider().run_scanner({})

        assert results == []

    def test_non_numeric_rank_maps_to_none_rather_than_dropping_the_row(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = {"contracts": [{"conid": 1, "symbol": "AAPL", "rank": "not-a-number"}]}
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        results = IBKRProvider().run_scanner({})

        assert results[0].rank is None

    def test_second_call_within_one_second_raises_rate_limited(self, mocker) -> None:
        clock = _FakeClock()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value={"contracts": []})
        provider = IBKRProvider(clock=clock)

        provider.run_scanner({})
        clock.advance(0.5)

        with pytest.raises(IBKRRateLimitedError) as exc_info:
            provider.run_scanner({})
        assert exc_info.value.retry_after == pytest.approx(0.5)

    def test_throttled_second_call_makes_no_http_request(self, mocker) -> None:
        """The client-side throttle check must run BEFORE any network call -- including
        the `_require_available` gateway-status check `run_scanner` itself makes -- per
        `IBKRRateLimitedError`'s own documented 'no network round-trip' contract. Unlike
        `test_second_call_within_one_second_raises_rate_limited` above (which mocks
        `get_gateway_status` directly, hiding whether it was ever called), this mocks the
        underlying `httpx.Client` so a real call to `get_gateway_status`'s
        `GET /iserver/auth/status` would be observable."""
        clock = _FakeClock()
        mock_response = mocker.Mock(status_code=200)
        mock_response.json.return_value = {"authenticated": True, "contracts": []}
        mock_client = mocker.Mock()
        mock_client.request.return_value = mock_response
        provider = IBKRProvider(client=mock_client, clock=clock)

        provider.run_scanner({})
        mock_client.request.reset_mock()  # only care about calls made by the 2nd run_scanner
        clock.advance(0.5)

        with pytest.raises(IBKRRateLimitedError):
            provider.run_scanner({})

        mock_client.request.assert_not_called()

    def test_call_after_one_second_succeeds(self, mocker) -> None:
        clock = _FakeClock()
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request", return_value={"contracts": []}
        )
        provider = IBKRProvider(clock=clock)

        provider.run_scanner({})
        clock.advance(1.0)
        provider.run_scanner({})

        assert request.call_count == 2


class TestResolveConid:
    """docs/tasks/backend-ibkr-symbol-resolution.json -- `GET /iserver/secdef/search`
    mocked per this module's own no-live-gateway testing constraint."""

    @staticmethod
    def _stk_entry(symbol: str, conid: int, extra_sections: list[dict] | None = None) -> dict:
        return {
            "conid": str(conid),
            "companyHeader": f"{symbol} INC - NASDAQ",
            "companyName": f"{symbol} INC",
            "symbol": symbol,
            "sections": [{"secType": "STK"}, *(extra_sections or [])],
        }

    def test_raises_when_gateway_not_available(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="gateway_unreachable", detail=None),
        )
        request = mocker.patch("app.data.ibkr_provider.IBKRProvider._request")

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider().resolve_conid("AAPL")

        request.assert_not_called()

    def test_single_exact_match_resolves(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [self._stk_entry("AAPL", 265598, extra_sections=[{"secType": "OPT"}])]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        conid = IBKRProvider().resolve_conid("AAPL")

        assert conid == 265598

    def test_request_uses_symbol_query_param(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        request = mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            return_value=[self._stk_entry("AAPL", 265598)],
        )

        IBKRProvider().resolve_conid("AAPL")

        _method, path = request.call_args.args
        assert path == "/iserver/secdef/search"
        assert request.call_args.kwargs["params"] == {"symbol": "AAPL"}

    def test_match_is_case_insensitive(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider._request",
            return_value=[self._stk_entry("AAPL", 265598)],
        )

        conid = IBKRProvider().resolve_conid("aapl")

        assert conid == 265598

    def test_no_match_returns_none(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=[])

        assert IBKRProvider().resolve_conid("NOSUCHTICKER") is None

    def test_ambiguous_multiple_distinct_conids_returns_none(self, mocker) -> None:
        """The same symbol resolving to two distinct stock conids (e.g. dual listings on
        different exchanges) is ambiguous -- degrades to `None` rather than guessing."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [self._stk_entry("BAR", 111), self._stk_entry("BAR", 222)]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("BAR") is None

    def test_duplicate_rows_for_the_same_conid_are_not_ambiguous(self, mocker) -> None:
        """Two rows resolving to the SAME conid (e.g. one row per derivative-bearing
        section returned as separate entries) isn't genuine ambiguity."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [self._stk_entry("AAPL", 265598), self._stk_entry("AAPL", 265598)]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("AAPL") == 265598

    def test_non_exact_symbol_matches_are_ignored(self, mocker) -> None:
        """The search endpoint can return fuzzy/partial matches -- only an exact
        (case-insensitive) symbol match counts."""
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [self._stk_entry("AAPLX", 999), self._stk_entry("AAPL", 265598)]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("AAPL") == 265598

    def test_option_only_entry_without_stk_section_is_ignored(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [
            {"conid": "1", "symbol": "AAPL", "sections": [{"secType": "OPT"}]},
            self._stk_entry("AAPL", 265598),
        ]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("AAPL") == 265598

    def test_malformed_conid_row_is_skipped(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [{"conid": "not-a-number", "symbol": "AAPL", "sections": [{"secType": "STK"}]}]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("AAPL") is None

    def test_non_list_payload_returns_none(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value={"unexpected": "shape"})

        assert IBKRProvider().resolve_conid("AAPL") is None

    def test_non_dict_rows_are_skipped(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = ["unexpected", self._stk_entry("AAPL", 265598)]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("AAPL") == 265598

    def test_non_list_sections_is_ignored(self, mocker) -> None:
        mocker.patch(
            "app.data.ibkr_provider.IBKRProvider.get_gateway_status",
            return_value=mocker.Mock(state="available", detail=None),
        )
        payload = [{"conid": "1", "symbol": "AAPL", "sections": "not-a-list"}]
        mocker.patch("app.data.ibkr_provider.IBKRProvider._request", return_value=payload)

        assert IBKRProvider().resolve_conid("AAPL") is None


class TestRequest:
    """Direct tests of the one method that performs the real HTTP call (mocked at the
    `httpx.Client` boundary here, unlike every other test class above which mocks
    `_request` itself) -- matches `StooqProvider`'s own `TestFetchCsv` pattern."""

    def test_returns_parsed_json_on_200(self, mocker) -> None:
        mock_response = mocker.Mock(status_code=200)
        mock_response.json.return_value = {"authenticated": True}
        mock_client = mocker.Mock()
        mock_client.request.return_value = mock_response

        result = IBKRProvider(client=mock_client)._request("GET", "/iserver/auth/status")

        assert result == {"authenticated": True}
        mock_client.request.assert_called_once_with(
            "GET", f"{DEFAULT_BASE_URL}/iserver/auth/status"
        )

    def test_transport_error_raises_ibkr_unavailable(self, mocker) -> None:
        mock_client = mocker.Mock()
        mock_client.request.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider(client=mock_client)._request("GET", "/iserver/auth/status")

    def test_non_200_raises_ibkr_unavailable(self, mocker) -> None:
        mock_response = mocker.Mock(status_code=503)
        mock_client = mocker.Mock()
        mock_client.request.return_value = mock_response

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider(client=mock_client)._request("GET", "/iserver/auth/status")

    def test_unparseable_body_raises_ibkr_unavailable(self, mocker) -> None:
        mock_response = mocker.Mock(status_code=200)
        mock_response.json.side_effect = ValueError("not json")
        mock_client = mocker.Mock()
        mock_client.request.return_value = mock_response

        with pytest.raises(IBKRUnavailableError):
            IBKRProvider(client=mock_client)._request("GET", "/iserver/auth/status")


class TestLifecycle:
    def test_close_closes_owned_client(self, mocker) -> None:
        mock_client_cls = mocker.patch("app.data.ibkr_provider.httpx.Client")
        mock_client = mock_client_cls.return_value

        provider = IBKRProvider()
        provider.close()

        mock_client.close.assert_called_once()

    def test_close_does_not_close_injected_client(self, mocker) -> None:
        injected_client = mocker.Mock()

        provider = IBKRProvider(client=injected_client)
        provider.close()

        injected_client.close.assert_not_called()

    def test_context_manager_closes_owned_client(self, mocker) -> None:
        mock_client_cls = mocker.patch("app.data.ibkr_provider.httpx.Client")
        mock_client = mock_client_cls.return_value

        with IBKRProvider() as provider:
            assert isinstance(provider, IBKRProvider)

        mock_client.close.assert_called_once()
