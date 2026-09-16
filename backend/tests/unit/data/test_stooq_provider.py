"""Tests for app.data.stooq_provider.StooqProvider (docs/Analyse.md §9,
docs/architecture/Backend.md §2).

Per docs/architecture/Testing.md ("Data provider adapters are tested against
recorded fixtures ... never live network calls"), every test here mocks
``StooqProvider._fetch_csv`` — the one method that performs the actual HTTP
GET against Stooq — and feeds it raw CSV text loaded from a fixture under
tests/fixtures/stooq/. See this task's `decisions` entry on
docs/tasks/data-provider-stooq.json for why fixtures are plain recorded CSV
text (Stooq's actual wire format) rather than a pre-parsed DataFrame.
"""

from pathlib import Path

import pandas as pd
import pytest

from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.stooq_provider import StooqProvider

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "stooq"


def _load_fixture_text(name: str) -> str:
    return (FIXTURES_DIR / f"{name}.csv").read_text()


class TestFetchCsv:
    """Direct test of the one method that performs the real HTTP GET (mocked
    at the urllib boundary here, unlike the rest of this file which mocks
    `_fetch_csv` itself) -- exercises that this method's own wiring (URL in,
    decoded text out) is correct, independent of the higher-level tests above.
    """

    def test_returns_decoded_response_body(self, mocker) -> None:
        mock_response = mocker.MagicMock()
        mock_response.read.return_value = "Date,Open,High,Low,Close,Volume\n".encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mocker.patch("app.data.stooq_provider.urllib.request.urlopen", return_value=mock_response)

        result = StooqProvider()._fetch_csv("https://stooq.com/q/d/l/?s=aapl.us&i=d")

        assert result == "Date,Open,High,Low,Close,Volume\n"


class TestGetDailyOhlcv:
    def test_returns_normalized_columns_indexed_by_date(self, mocker) -> None:
        text = _load_fixture_text("aapl_daily")
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_daily_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"
        assert len(result) == 300
        assert result.index.is_monotonic_increasing

    def test_requests_daily_interval_with_us_suffix_for_bare_ticker(self, mocker) -> None:
        text = _load_fixture_text("aapl_daily")
        mock_fetch = mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        StooqProvider().get_daily_ohlcv("AAPL")

        (url,), _ = mock_fetch.call_args
        assert "s=aapl.us" in url
        assert "i=d" in url

    def test_does_not_double_suffix_ticker_that_already_has_a_market_suffix(self, mocker) -> None:
        text = _load_fixture_text("aapl_daily")
        mock_fetch = mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        StooqProvider().get_daily_ohlcv("aapl.us")

        (url,), _ = mock_fetch.call_args
        assert "s=aapl.us" in url
        assert "s=aapl.us.us" not in url

    def test_dotted_class_share_ticker_is_hyphenated_not_treated_as_a_market_suffix(self, mocker) -> None:
        """A dotted class-share ticker like ``BRK.B`` isn't an already-suffixed
        Stooq symbol -- Stooq/yfinance both spell class shares with a hyphen
        (``brk-b``), so the '.' must become '-' and ``.us`` must still be
        appended, rather than the '.' being mistaken for an existing market
        suffix and left as ``brk.b`` (which Stooq doesn't recognize).
        """
        text = _load_fixture_text("aapl_daily")
        mock_fetch = mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        StooqProvider().get_daily_ohlcv("BRK.B")

        (url,), _ = mock_fetch.call_args
        assert "s=brk-b.us" in url

    def test_unknown_ticker_no_data_body_raises_ticker_not_found(self, mocker) -> None:
        text = _load_fixture_text("unknown_ticker")
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        with pytest.raises(TickerNotFoundError) as exc_info:
            StooqProvider().get_daily_ohlcv("NOTAREALTICKER")

        assert exc_info.value.ticker == "NOTAREALTICKER"

    def test_header_only_response_raises_ticker_not_found(self, mocker) -> None:
        mocker.patch(
            "app.data.stooq_provider.StooqProvider._fetch_csv",
            return_value="Date,Open,High,Low,Close,Volume\n",
        )

        with pytest.raises(TickerNotFoundError):
            StooqProvider().get_daily_ohlcv("NOTAREALTICKER")

    def test_transport_failure_raises_data_provider_unavailable(self, mocker) -> None:
        mocker.patch(
            "app.data.stooq_provider.StooqProvider._fetch_csv",
            side_effect=ConnectionError("boom"),
        )

        with pytest.raises(DataProviderUnavailableError):
            StooqProvider().get_daily_ohlcv("AAPL")

    def test_unparseable_response_raises_data_provider_unavailable(self, mocker) -> None:
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value="not empty")
        mocker.patch("app.data.stooq_provider.pd.read_csv", side_effect=ValueError("bad csv"))

        with pytest.raises(DataProviderUnavailableError):
            StooqProvider().get_daily_ohlcv("AAPL")


class TestGetWeeklyOhlcv:
    def test_resamples_daily_bars_into_weekly_bars(self, mocker) -> None:
        text = _load_fixture_text("aapl_daily")
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_weekly_ohlcv("AAPL")

        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "date"
        assert len(result) == 60
        # Weekly high/low must bound every daily bar that fell in that week.
        daily = pd.read_csv(FIXTURES_DIR / "aapl_daily.csv", parse_dates=["Date"]).set_index("Date")
        first_week_mask = daily.index <= result.index[0]
        assert result["high"].iloc[0] >= daily.loc[first_week_mask, "High"].max()
        assert result["low"].iloc[0] <= daily.loc[first_week_mask, "Low"].min()

    def test_requests_daily_interval_not_a_weekly_one(self, mocker) -> None:
        text = _load_fixture_text("aapl_daily")
        mock_fetch = mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        StooqProvider().get_weekly_ohlcv("AAPL")

        (url,), _ = mock_fetch.call_args
        assert "i=d" in url

    def test_unknown_ticker_raises_ticker_not_found(self, mocker) -> None:
        text = _load_fixture_text("unknown_ticker")
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        with pytest.raises(TickerNotFoundError):
            StooqProvider().get_weekly_ohlcv("NOTAREALTICKER")

    def test_fewer_than_26_weeks_raises_insufficient_history(self, mocker) -> None:
        text = _load_fixture_text("newco_daily_short")
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        with pytest.raises(InsufficientHistoryError) as exc_info:
            StooqProvider().get_weekly_ohlcv("NEWCO")

        assert exc_info.value.ticker == "NEWCO"
        assert exc_info.value.available == 2
        assert exc_info.value.required == 26

    def test_exactly_26_weeks_does_not_raise(self, mocker) -> None:
        text = _load_fixture_text("aapl_daily_exact26w")
        mocker.patch("app.data.stooq_provider.StooqProvider._fetch_csv", return_value=text)

        result = StooqProvider().get_weekly_ohlcv("AAPL")

        assert len(result) == 26

    def test_transport_failure_raises_data_provider_unavailable(self, mocker) -> None:
        mocker.patch(
            "app.data.stooq_provider.StooqProvider._fetch_csv",
            side_effect=TimeoutError("boom"),
        )

        with pytest.raises(DataProviderUnavailableError):
            StooqProvider().get_weekly_ohlcv("AAPL")
