"""Integration tests for DELETE /api/portfolio/positions/{id} (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override), matching the
pattern in tests/integration/test_portfolio_positions.py, so these tests never touch the real
fintrade.db file and don't depend on the db-migrations task's Alembic setup having run.
"""

from typing import Any

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


def _add_position(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload = {
        "ticker": "AAPL",
        "quantity": 100,
        "avg_cost_basis": 195.30,
        "entry_date": "2026-05-14",
    }
    payload.update(overrides)
    response = client.post("/api/portfolio/positions", json=payload)
    assert response.status_code == 201
    return response.json()


class TestDeletePosition:
    def test_delete_existing_position_returns_204(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(f"/api/portfolio/positions/{created['id']}")

        assert response.status_code == 204
        assert response.content == b""

    def test_deleted_position_no_longer_appears_in_get_portfolio(self, client: TestClient) -> None:
        created = _add_position(client)

        delete_response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert delete_response.status_code == 204

        portfolio = client.get("/api/portfolio")
        assert portfolio.status_code == 200
        ids = [p["id"] for p in portfolio.json()["positions"]]
        assert created["id"] not in ids

    def test_delete_unknown_id_returns_404(self, client: TestClient) -> None:
        response = client.delete("/api/portfolio/positions/pos_doesnotexist")

        assert response.status_code == 404
        body = response.json()
        assert isinstance(body["detail"], str)

    def test_delete_only_removes_the_targeted_position(self, client: TestClient) -> None:
        aapl = _add_position(client, ticker="AAPL")
        msft = _add_position(client, ticker="MSFT")

        response = client.delete(f"/api/portfolio/positions/{aapl['id']}")
        assert response.status_code == 204

        portfolio = client.get("/api/portfolio")
        ids = [p["id"] for p in portfolio.json()["positions"]]
        assert aapl["id"] not in ids
        assert msft["id"] in ids

    def test_delete_same_id_twice_returns_404_on_second_call(self, client: TestClient) -> None:
        created = _add_position(client)

        first = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert first.status_code == 204

        second = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert second.status_code == 404
