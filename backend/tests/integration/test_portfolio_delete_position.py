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

    def test_carries_entry_notes_through_to_the_closed_trade_row(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(
            client,
            ticker="AAPL",
            quantity=100,
            avg_cost_basis=195.30,
            entry_notes="Breakout above resistance, strong earnings beat.",
        )

        response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.entry_notes == "Breakout above resistance, strong earnings beat."

    def test_closed_trade_entry_notes_is_null_when_position_had_none(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="AAPL", quantity=100, avg_cost_basis=195.30)

        response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.entry_notes is None

    def test_carries_strategy_through_to_the_closed_trade_row(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(
            client,
            ticker="AAPL",
            quantity=100,
            avg_cost_basis=195.30,
            strategy="Pullback to value",
        )

        response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.strategy == "Pullback to value"

    def test_closed_trade_strategy_is_null_when_position_had_none(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="AAPL", quantity=100, avg_cost_basis=195.30)

        response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.strategy is None

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


class TestDeletePositionManualExitOverride:
    """Coverage for the backend-close-position-manual-exit task: DELETE
    /api/portfolio/positions/{id} accepts an optional exit_price/exit_date pair to backfill a
    trade that already happened in the past, bypassing the default live-price lookup -- see
    this task's `decisions` entry for why this revisits backend-trade-history-table's original
    market-price-only design."""

    def test_manual_exit_price_and_date_are_used_verbatim(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(
            client, ticker="AAPL", quantity=100, avg_cost_basis=195.30, entry_date="2026-05-14"
        )

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": 220.0, "exit_date": "2026-06-01"},
        )
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.exit_price == pytest.approx(220.0)
        assert trade.exit_date == date(2026, 6, 1)
        assert trade.realized_pnl == pytest.approx(100 * (220.0 - 195.30))
        # The live-price lookup (_StubProvider's AAPL close of 210.0) is never consulted --
        # the manual override took priority and produced a different exit_price than that
        # stub would have.
        assert trade.exit_price != pytest.approx(210.0)

    def test_manual_exit_override_does_not_touch_data_provider(self, db_session: Session) -> None:
        # A provider that raises for *any* ticker -- if the manual override path accidentally
        # still called latest_close, this test would fail with an unhandled exception instead
        # of a clean 204.
        class _AlwaysFailingProvider:
            def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
                raise TickerNotFoundError(ticker)

            def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
                raise DataProviderUnavailableError("not stubbed")

        client = _make_client(db_session, _AlwaysFailingProvider())  # type: ignore[arg-type]
        try:
            created = _add_position(client, ticker="AAPL", quantity=10, avg_cost_basis=100.0)

            response = client.delete(
                f"/api/portfolio/positions/{created['id']}",
                params={"exit_price": 150.0, "exit_date": "2026-05-20"},
            )
            assert response.status_code == 204

            [trade] = db_session.query(ClosedTradeORM).all()
            assert trade.exit_price == pytest.approx(150.0)
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

    def test_manual_exit_reason_and_price_override_combine(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="MSFT", quantity=10, avg_cost_basis=300.0)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={
                "exit_reason": "target_hit",
                "exit_price": 350.0,
                "exit_date": "2026-05-15",
            },
        )
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.exit_reason == "target_hit"
        assert trade.exit_price == pytest.approx(350.0)
        assert trade.exit_date == date(2026, 5, 15)

    def test_omitting_both_exit_price_and_date_keeps_default_live_price_behavior(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="AAPL", quantity=100, avg_cost_basis=195.30)

        response = client.delete(f"/api/portfolio/positions/{created['id']}")
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.exit_price == pytest.approx(210.0)  # _StubProvider's latest AAPL close
        assert trade.exit_date == _today()

    def test_exit_price_without_exit_date_returns_422(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": 200.0},
        )

        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], str)
        assert "exit_price" in body["detail"] and "exit_date" in body["detail"]

    def test_exit_date_without_exit_price_returns_422(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_date": "2026-05-20"},
        )

        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], str)
        assert "exit_price" in body["detail"] and "exit_date" in body["detail"]

    def test_exit_date_before_entry_date_returns_422(self, client: TestClient) -> None:
        created = _add_position(client, ticker="AAPL", entry_date="2026-05-14")

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": 200.0, "exit_date": "2026-05-01"},
        )

        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], str)
        assert "entry_date" in body["detail"]

    def test_exit_date_equal_to_entry_date_is_allowed(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = _add_position(client, ticker="AAPL", entry_date="2026-05-14")

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": 200.0, "exit_date": "2026-05-14"},
        )

        assert response.status_code == 204
        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.exit_date == date(2026, 5, 14)

    def test_non_positive_exit_price_returns_422(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": 0.0, "exit_date": "2026-05-20"},
        )

        assert response.status_code == 422

    def test_negative_exit_price_returns_422(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": -5.0, "exit_date": "2026-05-20"},
        )

        assert response.status_code == 422

    def test_infinite_exit_price_returns_422(self, client: TestClient) -> None:
        created = _add_position(client)

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": "Infinity", "exit_date": "2026-05-20"},
        )

        assert response.status_code == 422

    def test_manual_exit_still_carries_entry_notes_and_feeds_six_percent_rule(
        self, client: TestClient, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.commit()
        created = _add_position(
            client,
            ticker="MSFT",
            quantity=100,
            avg_cost_basis=400.0,
            entry_date="2026-05-01",
            entry_notes="Backfilled from broker CSV export.",
        )
        # exit_date is today's actual (real, not fixture-2026) date, not the position's
        # fixture entry_date, so this manually-priced realized loss lands in "this calendar
        # month" from GET /api/portfolio/risk's own point of view -- exercising the same
        # DELETE -> closed_trades -> GET /risk wiring as
        # TestDeletePositionRealizedLossFeedsSixPercentRule, but via the manual-override path.
        today = _today()

        response = client.delete(
            f"/api/portfolio/positions/{created['id']}",
            params={"exit_price": 330.0, "exit_date": today.isoformat()},
        )
        assert response.status_code == 204

        [trade] = db_session.query(ClosedTradeORM).all()
        assert trade.entry_notes == "Backfilled from broker CSV export."
        assert trade.realized_pnl == pytest.approx(-7000.0)
        assert trade.exit_date == today

        risk_response = client.get("/api/portfolio/risk")
        assert risk_response.status_code == 200
        assert risk_response.json()["realized_losses_this_month_pct"] > 0.0
