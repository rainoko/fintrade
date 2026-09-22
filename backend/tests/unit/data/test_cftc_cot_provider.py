"""Tests for app.data.cftc_cot_provider (docs/tasks/backend-cftc-cot-data.json).

Per docs/architecture/Testing.md ("Data provider adapters are tested against recorded
fixtures ... never live network calls"), every test here mocks
``CFTCCOTProvider._request`` -- the one method that performs the actual HTTP GET against
CFTC's public Socrata endpoint and parses its JSON body -- matching
`IBKRProvider._request`'s own mocking pattern (tests/unit/data/test_ibkr_provider.py)
rather than `StooqProvider._fetch_csv`'s raw-text one, since Socrata already returns clean
JSON with nothing provider-specific left to unit-test in the parsing step itself.
"""

import json

import pytest

from app.data.cftc_cot_provider import (
    COT_MARKETS,
    CFTCCOTProvider,
    cot_index,
)
from app.data.exceptions import DataProviderUnavailableError


def _row(
    *,
    code: str,
    name: str,
    report_date: str,
    open_interest: int = 100_000,
    comm_long: int = 40_000,
    comm_short: int = 30_000,
    noncomm_long: int = 35_000,
    noncomm_short: int = 45_000,
    nonrept_long: int = 10_000,
    nonrept_short: int = 12_000,
) -> dict:
    return {
        "cftc_contract_market_code": code,
        "market_and_exchange_names": name,
        "report_date_as_yyyy_mm_dd": f"{report_date}T00:00:00.000",
        "open_interest_all": str(open_interest),
        "comm_positions_long_all": str(comm_long),
        "comm_positions_short_all": str(comm_short),
        "noncomm_positions_long_all": str(noncomm_long),
        "noncomm_positions_short_all": str(noncomm_short),
        "nonrept_positions_long_all": str(nonrept_long),
        "nonrept_positions_short_all": str(nonrept_short),
    }


class TestGetRecentReports:
    def test_parses_rows_into_reports_most_recent_first(self, mocker) -> None:
        rows = [
            _row(code="088691", name="GOLD - COMMODITY EXCHANGE INC.", report_date="2026-09-15"),
            _row(code="088691", name="GOLD - COMMODITY EXCHANGE INC.", report_date="2026-09-08"),
        ]
        mocker.patch("app.data.cftc_cot_provider.CFTCCOTProvider._request", return_value=rows)

        reports = CFTCCOTProvider().get_recent_reports("gold")

        assert len(reports) == 2
        assert reports[0].report_date.isoformat() == "2026-09-15"
        assert reports[0].market_and_exchange_name == "GOLD - COMMODITY EXCHANGE INC."
        assert reports[0].open_interest == 100_000
        assert reports[0].commercial_long == 40_000
        assert reports[0].commercial_short == 30_000
        assert reports[0].commercial_net == 10_000
        assert reports[0].large_speculator_long == 35_000
        assert reports[0].large_speculator_short == 45_000
        assert reports[0].large_speculator_net == -10_000
        assert reports[0].small_speculator_long == 10_000
        assert reports[0].small_speculator_short == 12_000
        assert reports[0].small_speculator_net == -2_000

    def test_unknown_market_key_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            CFTCCOTProvider().get_recent_reports("not-a-real-market")

    def test_requests_the_correct_contract_code_and_limit(self, mocker) -> None:
        mock_request = mocker.patch(
            "app.data.cftc_cot_provider.CFTCCOTProvider._request",
            return_value=[_row(code="099741", name="EURO FX - CHICAGO MERCANTILE EXCHANGE", report_date="2026-09-15")],
        )

        CFTCCOTProvider().get_recent_reports("eur", weeks=10)

        (url,), _ = mock_request.call_args
        assert "%24where=cftc_contract_market_code" in url
        assert "%27099741%27" in url
        assert "%24limit=10" in url

    def test_malformed_row_raises_data_provider_unavailable(self, mocker) -> None:
        bad_row = _row(code="088691", name="GOLD - COMMODITY EXCHANGE INC.", report_date="2026-09-15")
        del bad_row["open_interest_all"]
        mocker.patch("app.data.cftc_cot_provider.CFTCCOTProvider._request", return_value=[bad_row])

        with pytest.raises(DataProviderUnavailableError):
            CFTCCOTProvider().get_recent_reports("gold")


class TestGetAllRecent:
    def test_returns_one_entry_per_fixed_market_in_a_single_request(self, mocker) -> None:
        rows = [
            _row(code=code, name=f"NAME-{key}", report_date="2026-09-15")
            for key, code in COT_MARKETS.items()
        ]
        mock_request = mocker.patch("app.data.cftc_cot_provider.CFTCCOTProvider._request", return_value=rows)

        result = CFTCCOTProvider().get_all_recent()

        assert set(result.keys()) == set(COT_MARKETS.keys())
        for key in COT_MARKETS:
            assert result[key][0].market_and_exchange_name == f"NAME-{key}"
        assert mock_request.call_count == 1

    def test_groups_multiple_weeks_per_market_most_recent_first(self, mocker) -> None:
        rows = [
            _row(code="088691", name="GOLD - COMMODITY EXCHANGE INC.", report_date="2026-09-15"),
            _row(code="099741", name="EURO FX - CHICAGO MERCANTILE EXCHANGE", report_date="2026-09-15"),
            _row(code="088691", name="GOLD - COMMODITY EXCHANGE INC.", report_date="2026-09-08"),
            _row(code="099741", name="EURO FX - CHICAGO MERCANTILE EXCHANGE", report_date="2026-09-08"),
            _row(code="097741", name="JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE", report_date="2026-09-15"),
            _row(code="067651", name="CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE", report_date="2026-09-15"),
            _row(code="020601", name="U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE", report_date="2026-09-15"),
        ]
        mocker.patch("app.data.cftc_cot_provider.CFTCCOTProvider._request", return_value=rows)

        result = CFTCCOTProvider().get_all_recent()

        assert [r.report_date.isoformat() for r in result["gold"]] == ["2026-09-15", "2026-09-08"]
        assert [r.report_date.isoformat() for r in result["eur"]] == ["2026-09-15", "2026-09-08"]
        assert len(result["jpy"]) == 1

    def test_missing_market_in_response_raises_data_provider_unavailable(self, mocker) -> None:
        rows = [
            _row(code=code, name=f"NAME-{key}", report_date="2026-09-15")
            for key, code in COT_MARKETS.items()
            if key != "gold"
        ]
        mocker.patch("app.data.cftc_cot_provider.CFTCCOTProvider._request", return_value=rows)

        with pytest.raises(DataProviderUnavailableError):
            CFTCCOTProvider().get_all_recent()


class TestRequest:
    """Direct test of the one method that performs the real HTTP GET + JSON parsing
    (mocked at the urllib boundary here, unlike the rest of this file which mocks
    `_request` itself) -- matches `StooqProvider`'s `TestFetchCsv`/`IBKRProvider`'s
    equivalent boundary-level test.
    """

    def test_returns_parsed_json_body(self, mocker) -> None:
        payload = [{"a": 1}]
        mock_response = mocker.MagicMock()
        mock_response.read.return_value = json.dumps(payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mocker.patch("app.data.cftc_cot_provider.urllib.request.urlopen", return_value=mock_response)

        result = CFTCCOTProvider()._request("https://publicreporting.cftc.gov/resource/6dca-aqww.json")

        assert result == payload

    def test_transport_failure_raises_data_provider_unavailable(self, mocker) -> None:
        mocker.patch(
            "app.data.cftc_cot_provider.urllib.request.urlopen",
            side_effect=ConnectionError("boom"),
        )

        with pytest.raises(DataProviderUnavailableError):
            CFTCCOTProvider()._request("https://publicreporting.cftc.gov/resource/6dca-aqww.json")

    def test_unparseable_response_raises_data_provider_unavailable(self, mocker) -> None:
        mock_response = mocker.MagicMock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__.return_value = mock_response
        mocker.patch("app.data.cftc_cot_provider.urllib.request.urlopen", return_value=mock_response)

        with pytest.raises(DataProviderUnavailableError):
            CFTCCOTProvider()._request("https://publicreporting.cftc.gov/resource/6dca-aqww.json")

    def test_non_list_response_raises_data_provider_unavailable(self, mocker) -> None:
        mock_response = mocker.MagicMock()
        mock_response.read.return_value = json.dumps({"error": "nope"}).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mocker.patch("app.data.cftc_cot_provider.urllib.request.urlopen", return_value=mock_response)

        with pytest.raises(DataProviderUnavailableError):
            CFTCCOTProvider()._request("https://publicreporting.cftc.gov/resource/6dca-aqww.json")


class TestCotIndex:
    def test_current_at_low_end_of_range_is_zero(self) -> None:
        assert cot_index(-10, [-10, 0, 10]) == 0.0

    def test_current_at_high_end_of_range_is_100(self) -> None:
        assert cot_index(10, [-10, 0, 10]) == 100.0

    def test_current_at_midpoint_is_50(self) -> None:
        assert cot_index(0, [-10, 0, 10]) == 50.0

    def test_fewer_than_two_history_points_is_none(self) -> None:
        assert cot_index(5, [5]) is None
        assert cot_index(5, []) is None

    def test_zero_width_range_is_none(self) -> None:
        assert cot_index(5, [5, 5, 5]) is None
