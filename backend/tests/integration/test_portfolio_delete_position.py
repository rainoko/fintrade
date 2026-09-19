"""Integration tests for DELETE /api/portfolio/positions/{id} (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override), matching the
pattern in tests/integration/test_portfolio_positions.py, so these tests never touch the real
fintrade.db file and don't depend on the db-migrations task's Alembic setup having run.

Unlike test_portfolio_positions.py, this module does *not* reuse the shared `client` fixture
from tests/integration/conftest.py: since the backend-trade-history-table task, DELETE also
fetches today's latest close (`app.portfolio.pricing.latest_close`) to price the closed_trades
row it records, so a `get_data_provider` override is needed here too (same reasoning as
test_portfolio_get.py/test_portfolio_risk.py) -- without one, these tests would exercise the
real live-network-backed provider, violating docs/architecture/Testing.md's "no test makes a
live network call" rule. The `db_session` fixture still comes from conftest.py.
"""

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.data.exceptions import DataProviderUnavailableError, TickerNotFoundError
from app.db.models import AccountORM, ClosedTradeORM
from app.db.session import get_db
from app.main import app
from app.portfolio.models import ExitReason


def _today() -> date:
    """Matches `app.api.routers.portfolio._today()` exactly (UTC-derived, not local
    `date.today()`) -- see this task's `decisions` entry for why: a test asserting against
    local `date.today()` would intermittently disagree with the UTC-based production value
    outside a UTC-local-timezone runner, even though dev container/CI both run in UTC today."""
    return datetime.now(UTC).date()


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([f"2026-01-{i + 1:02d}" for i in range(len(closes))], name="date")
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000.0 for _ in closes],
        },
        index=idx,
    )


class _StubProvider:
    """Returns a fixed latest close per ticker (AAPL/MSFT, the tickers `_add_position` below
    creates), or raises `TickerNotFoundError` for any ticker in `failing` -- used to exercise
    both the "price fetch succeeds, closed_trades row recorded" and "price fetch fails, no row
    recorded" paths."""

    def __init__(self, *, failing: set[str] | None = None) -> None:
        self._failing = failing or set()

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise TickerNotFoundError(ticker)
        return _frame({"AAPL": [195.30, 210.0], "MSFT": [300.0, 330.0]}.get(ticker, [100.0, 110.0]))

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        # These tests never assert on signal/confidence fields -- GET /api/portfolio still
        # calls this per position, though, to annotate them (app.api.routers.portfolio
        # ._compute_position_signal), so it must degrade gracefully (a DataProviderError, not
        # a bare NotImplementedError) rather than 500 the whole response.
        raise DataProviderUnavailableError("weekly history not stubbed in this test module")


def _make_client(db_session: Session, provider: _StubProvider) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


@pytest.fixture
def client(db_session: Session):
    test_client = _make_client(db_session, _StubProvider())
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)


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


class TestDeletePositionRecordsClosedTrade:
    """Coverage for the backend-trade-history-table task: DELETE /api/portfolio/positions/{id}
    should record a `closed_trades` row priced at today's latest close, unless that price
    fetch fails -- see this task's `decisions` entry."""

    def test_records_closed_trade_with_default_unspecified_exit_reason(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="AAPL", quantity=100, avg_cost_basis=195.30)

        response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.ticker == "AAPL"
        assert trade.quantity == pytest.approx(100.0)
        assert trade.entry_price == pytest.approx(195.30)
        assert trade.entry_date == date(2026, 5, 14)
        assert trade.exit_price == pytest.approx(210.0)  # _StubProvider's latest AAPL close
        assert trade.exit_date == _today()
        assert trade.realized_pnl == pytest.approx(100 * (210.0 - 195.30))
        assert trade.exit_reason == ExitReason.UNSPECIFIED.value

    def test_records_closed_trade_with_explicit_exit_reason(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="MSFT", quantity=10, avg_cost_basis=300.0)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_reason": "target_hit"},
        )
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.ticker == "MSFT"
        assert trade.exit_price == pytest.approx(330.0)
        assert trade.realized_pnl == pytest.approx(10 * (330.0 - 300.0))
        assert trade.exit_reason == "target_hit"

    def test_invalid_exit_reason_returns_422(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_reason": "not_a_real_reason"},
        )

        assert response.status_code == 422

    def test_position_still_deleted_when_price_fetch_fails_but_no_closed_trade_recorded(
        self, db_session: Session
    ) -> None:
        client = _make_client(db_session, _StubProvider(failing={"ZZZZ"}))
        try:
            created = _add_position(client, ticker="ZZZZ", quantity=5, avg_cost_basis=10.0)

            response = client.delete(f"/api/portfolio/positions/{created['id']}")
            assert response.status_code == 204

            portfolio = client.get("/api/portfolio")
            assert created["id"] not in [p["id"] for p in portfolio.json()["positions"]]
            assert db_session.query(ClosedTradeORM).all() == []
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

    def test_deleting_two_positions_records_two_independent_closed_trades(
        self, client: TestClient, db_session: Session
    ) -> None:
        aapl = _add_position(client, ticker="AAPL", quantity=100, avg_cost_basis=195.30)
        msft = _add_position(client, ticker="MSFT", quantity=10, avg_cost_basis=300.0)

        assert client.delete(f"/api/portfolio/positions/{aapl['id']}").status_code == 204
        assert client.delete(f"/api/portfolio/positions/{msft['id']}").status_code == 204

        trades = db_session.query(ClosedTradeORM).order_by(ClosedTradeORM.ticker).all()
        assert [t.ticker for t in trades] == ["AAPL", "MSFT"]
        assert trades[0].id != trades[1].id


class TestDeletePositionRealizedLossFeedsSixPercentRule:
    """A closed losing trade recorded just now (this calendar month, by construction) must
    already count towards GET /api/portfolio/risk's 6% Rule total on the very next call --
    confirms the DELETE -> closed_trades -> GET /risk wiring end to end, complementing the
    lower-level realized-losses tests in test_portfolio_risk.py (which insert ClosedTradeORM
    rows directly rather than going through DELETE)."""

    def test_a_realized_loss_from_delete_shows_up_in_get_risk_immediately(
        self, client: TestClient, db_session: Session
    ) -> None:
        # AAPL bought at 195.30, "sold" (via DELETE) at the stub's 210.0 -- a *gain*, not a
        # loss, with this ticker/provider combination, so use a custom stub priced below
        # avg_cost_basis instead to produce a realized loss.
        client = _make_client(db_session, _StubProvider())
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.commit()
        created = _add_position(client, ticker="MSFT", quantity=100, avg_cost_basis=400.0)
        # _StubProvider's MSFT latest close (330.0) is below the 400.0 entry price -- a real
        # realized loss of 100 * (330.0 - 400.0) = -7000.0.

        delete_response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert delete_response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.realized_pnl == pytest.approx(-7000.0)
        assert trade.exit_date == _today()

        risk_response = client.get("/api/portfolio/risk")
        assert risk_response.status_code == 200
        body = risk_response.json()
        assert body["realized_losses_this_month_pct"] > 0.0

        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)
