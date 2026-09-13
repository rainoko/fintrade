"""Integration tests for POST /api/portfolio/positions (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override), matching the
pattern in tests/unit/test_db_models.py, so these tests never touch the real fintrade.db file
and don't depend on the db-migrations task's Alembic setup having run.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def db_session():
    # StaticPool keeps a single connection alive for the whole engine, which is required for
    # an in-memory SQLite database to be visible across threads — TestClient runs requests on
    # a separate thread from the one that created the tables below.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


class TestAddPosition:
    def test_create_new_position_returns_201(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["quantity"] == 100
        assert body["avg_cost_basis"] == 195.30
        assert body["entry_date"] == "2026-05-14"
        assert body["current_price"] is None
        assert body["unrealized_pnl_pct"] is None
        assert body["id"].startswith("pos_")

    def test_ticker_is_normalized_to_uppercase(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "aapl", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    def test_duplicate_ticker_merges_quantity_and_weighted_avg_cost(self, client: TestClient) -> None:
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 100.0, "entry_date": "2026-05-14"},
        )
        assert first.status_code == 201
        first_id = first.json()["id"]

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 50, "avg_cost_basis": 130.0, "entry_date": "2026-06-01"},
        )

        assert second.status_code == 201
        body = second.json()
        # Merged into the same row, not a new one.
        assert body["id"] == first_id
        assert body["quantity"] == 150
        # Weighted average: (100*100 + 50*130) / 150 = 110.0
        assert body["avg_cost_basis"] == pytest.approx(110.0)
        # Earlier of the two entry dates is kept.
        assert body["entry_date"] == "2026-05-14"

    def test_duplicate_ticker_lowercase_still_merges(self, client: TestClient) -> None:
        client.post(
            "/api/portfolio/positions",
            json={"ticker": "MSFT", "quantity": 10, "avg_cost_basis": 300.0, "entry_date": "2026-02-01"},
        )
        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "msft", "quantity": 5, "avg_cost_basis": 320.0, "entry_date": "2026-01-01"},
        )

        assert second.status_code == 201
        body = second.json()
        assert body["ticker"] == "MSFT"
        assert body["quantity"] == 15
        assert body["entry_date"] == "2026-01-01"

    def test_duplicate_ticker_merge_keeps_later_entry_date_when_existing_is_earlier(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={"ticker": "TSLA", "quantity": 1, "avg_cost_basis": 200.0, "entry_date": "2026-01-01"},
        )
        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "TSLA", "quantity": 1, "avg_cost_basis": 250.0, "entry_date": "2026-03-01"},
        )

        assert second.status_code == 201
        # existing entry_date (2026-01-01) is earlier than the new one, so it's kept.
        assert second.json()["entry_date"] == "2026-01-01"

    def test_different_tickers_create_separate_positions(self, client: TestClient) -> None:
        aapl = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )
        msft = client.post(
            "/api/portfolio/positions",
            json={"ticker": "MSFT", "quantity": 5, "avg_cost_basis": 300.0, "entry_date": "2026-01-01"},
        )

        assert aapl.status_code == 201
        assert msft.status_code == 201
        assert aapl.json()["id"] != msft.json()["id"]

    def test_invalid_body_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100},
        )

        assert response.status_code == 422
