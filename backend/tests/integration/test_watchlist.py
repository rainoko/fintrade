"""Integration tests for GET/POST/DELETE /api/watchlist (app/api/routers/watchlist.py).

Uses an isolated in-memory SQLite session (via a `get_db` dependency override) and a stub
`DataProvider` (via a `get_data_provider` dependency override), matching the pattern in
tests/integration/test_portfolio_get.py, so these tests never touch the real fintrade.db file
or a live market data provider.

The `db_session` fixture lives in tests/integration/conftest.py; this module keeps its own
`client` fixture because it additionally needs the `get_data_provider` override below.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.db.models import WatchlistItemORM
from app.db.session import get_db
from app.main import app


def _hold_daily_ohlcv() -> pd.DataFrame:
    # Flat prices -- no Wave pullback ever qualifies, so this always resolves to HOLD
    # regardless of tide direction. Copied from tests/integration/test_stocks_analysis.py's
    # identically-named fixture.
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
        },
        index=pd.date_range("2026-01-01", periods=30, freq="D", name="date"),
    )


def _hold_weekly_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
        },
        index=pd.date_range("2025-01-01", periods=30, freq="W", name="date"),
    )


class _StubProvider:
    """A minimal DataProvider stand-in: returns a fixed HOLD-shaped daily/weekly frame for
    every ticker in `computable`, or raises a fixed exception for every ticker in `failing`."""

    def __init__(self, *, computable: set[str] | None = None, failing: dict[str, Exception] | None = None) -> None:
        self._computable = computable or set()
        self._failing = failing or {}

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise self._failing[ticker]
        return _hold_daily_ohlcv()

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise self._failing[ticker]
        return _hold_weekly_ohlcv()


def _make_client(db_session: Session, provider: _StubProvider) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


@pytest.fixture
def client(db_session: Session):
    test_client = _make_client(db_session, _StubProvider(computable={"AAPL"}))
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)


def _client_with_provider(db_session: Session, provider: _StubProvider) -> TestClient:
    return _make_client(db_session, provider)


class TestGetWatchlistEmpty:
    def test_empty_watchlist_returns_empty_items(self, client: TestClient) -> None:
        response = client.get("/api/watchlist")

        assert response.status_code == 200
        assert response.json() == {"items": []}


class TestAddWatchlistItem:
    def test_add_ticker_returns_201_with_null_signal_fields(self, client: TestClient) -> None:
        response = client.post("/api/watchlist", json={"ticker": "AAPL"})

        assert response.status_code == 201
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["signal"] is None
        assert body["confidence"] is None
        assert body["confidence_band"] is None
        assert body["added_at"]

    def test_ticker_is_normalized_to_uppercase(self, client: TestClient) -> None:
        response = client.post("/api/watchlist", json={"ticker": "aapl"})

        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    def test_ticker_with_surrounding_whitespace_is_stripped_and_uppercased(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/watchlist", json={"ticker": " aapl "})

        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    def test_blank_ticker_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/watchlist", json={"ticker": "   "})

        assert response.status_code == 422

    def test_duplicate_add_is_a_no_op_and_keeps_original_added_at(self, client: TestClient) -> None:
        first = client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert first.status_code == 201
        original_added_at = first.json()["added_at"]

        second = client.post("/api/watchlist", json={"ticker": "AAPL"})

        assert second.status_code == 201
        assert second.json()["added_at"] == original_added_at

        listed = client.get("/api/watchlist")
        assert len(listed.json()["items"]) == 1


class TestGetWatchlistWithSignal:
    def test_list_annotates_computable_ticker_with_signal(self, db_session: Session) -> None:
        db_session.add(WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        db_session.commit()
        test_client = _client_with_provider(db_session, _StubProvider(computable={"AAPL"}))

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["ticker"] == "AAPL"
        assert items[0]["signal"] == "HOLD"
        assert items[0]["confidence"] == 0
        assert items[0]["confidence_band"] == "Low"

    def test_list_nulls_out_signal_for_a_ticker_whose_fetch_fails(self, db_session: Session) -> None:
        db_session.add(WatchlistItemORM(ticker="ZZZZ", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        db_session.commit()
        provider = _StubProvider(failing={"ZZZZ": TickerNotFoundError("ZZZZ")})
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["ticker"] == "ZZZZ"
        assert item["signal"] is None
        assert item["confidence"] is None
        assert item["confidence_band"] is None

    def test_list_nulls_out_signal_for_a_ticker_with_insufficient_history(
        self, db_session: Session
    ) -> None:
        # Spot-test for InsufficientHistoryError specifically (a recent-IPO-shaped 422 from
        # the provider) -- TickerNotFoundError and DataProviderUnavailableError are covered
        # above; _compute_signal catches all three via the shared DataProviderError base, but
        # exercising each concrete subclass documents that every one of them nulls the entry
        # out rather than only the two already covered.
        db_session.add(WatchlistItemORM(ticker="IPOX", added_at=pd.Timestamp("2026-01-01").to_pydatetime()))
        db_session.commit()
        provider = _StubProvider(
            failing={"IPOX": InsufficientHistoryError("IPOX", available=5, required=26)}
        )
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["ticker"] == "IPOX"
        assert item["signal"] is None
        assert item["confidence"] is None
        assert item["confidence_band"] is None

    def test_list_with_a_mix_of_computable_and_failing_tickers(self, db_session: Session) -> None:
        db_session.add_all(
            [
                WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()),
                WatchlistItemORM(ticker="ZZZZ", added_at=pd.Timestamp("2026-01-02").to_pydatetime()),
            ]
        )
        db_session.commit()
        provider = _StubProvider(
            computable={"AAPL"},
            failing={"ZZZZ": DataProviderUnavailableError("provider down")},
        )
        test_client = _client_with_provider(db_session, provider)

        response = test_client.get("/api/watchlist")

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["ticker"] for item in items] == ["AAPL", "ZZZZ"]
        assert items[0]["signal"] == "HOLD"
        assert items[1]["signal"] is None

    def test_list_is_ordered_by_added_at_oldest_first(self, db_session: Session) -> None:
        db_session.add_all(
            [
                WatchlistItemORM(ticker="MSFT", added_at=pd.Timestamp("2026-02-01").to_pydatetime()),
                WatchlistItemORM(ticker="AAPL", added_at=pd.Timestamp("2026-01-01").to_pydatetime()),
            ]
        )
        db_session.commit()
        test_client = _client_with_provider(
            db_session, _StubProvider(computable={"MSFT", "AAPL"})
        )

        response = test_client.get("/api/watchlist")

        assert [item["ticker"] for item in response.json()["items"]] == ["AAPL", "MSFT"]


class TestDeleteWatchlistItem:
    def test_delete_existing_item_returns_204(self, client: TestClient) -> None:
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        response = client.delete("/api/watchlist/AAPL")

        assert response.status_code == 204
        assert response.content == b""

    def test_deleted_item_no_longer_appears_in_list(self, client: TestClient) -> None:
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        client.delete("/api/watchlist/AAPL")

        assert client.get("/api/watchlist").json() == {"items": []}

    def test_delete_ticker_is_normalized_to_uppercase(self, client: TestClient) -> None:
        client.post("/api/watchlist", json={"ticker": "AAPL"})

        response = client.delete("/api/watchlist/aapl")

        assert response.status_code == 204

    def test_delete_unknown_ticker_returns_404(self, client: TestClient) -> None:
        response = client.delete("/api/watchlist/ZZZZ")

        assert response.status_code == 404
        assert "ZZZZ" in response.json()["detail"]
