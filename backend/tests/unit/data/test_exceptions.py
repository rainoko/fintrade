"""Tests for app.data.exceptions — the typed hierarchy the API layer maps to
404/422/503 (see this task's `decisions` entry on
docs/tasks/data-provider-yfinance.json).
"""

import pytest

from app.data.exceptions import (
    DataProviderError,
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)


class TestTickerNotFoundError:
    def test_is_a_data_provider_error(self) -> None:
        assert issubclass(TickerNotFoundError, DataProviderError)

    def test_carries_ticker_and_readable_message(self) -> None:
        exc = TickerNotFoundError("NOPE")

        assert exc.ticker == "NOPE"
        assert "NOPE" in str(exc)


class TestInsufficientHistoryError:
    def test_is_a_data_provider_error(self) -> None:
        assert issubclass(InsufficientHistoryError, DataProviderError)

    def test_carries_counts_and_readable_message(self) -> None:
        exc = InsufficientHistoryError("NEWCO", available=10, required=26)

        assert exc.ticker == "NEWCO"
        assert exc.available == 10
        assert exc.required == 26
        assert "10" in str(exc)
        assert "26" in str(exc)


class TestDataProviderUnavailableError:
    def test_is_a_data_provider_error(self) -> None:
        assert issubclass(DataProviderUnavailableError, DataProviderError)

    def test_is_raisable_with_a_plain_message(self) -> None:
        with pytest.raises(DataProviderUnavailableError, match="rate-limited"):
            raise DataProviderUnavailableError("rate-limited")
