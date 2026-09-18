"""Integration tests for GET /api/portfolio (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override) and a stub
DataProvider (via a get_data_provider dependency override), matching the pattern in
tests/integration/test_portfolio_positions.py and tests/unit/data/test_cache.py, so these
tests never touch the real fintrade.db file or a live market data provider.

The `db_session` fixture lives in tests/integration/conftest.py; this module keeps its own
`client` fixture because it additionally needs the get_data_provider override below.
"""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.data.exceptions import DataProviderUnavailableError, TickerNotFoundError
from app.db.models import AccountORM, PositionORM
from app.db.session import get_db
from app.main import app


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


def _hold_weekly_ohlcv() -> pd.DataFrame:
    # Flat weekly prices -- Screen 1 (Tide) degrades to NEUTRAL, which alone is enough to
    # keep the combined signal HOLD regardless of the daily side. Same fixture shape as
    # tests/integration/test_watchlist.py's identically-named helper.
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
    """A minimal DataProvider stand-in: returns a fixed close series per ticker, or raises
    a fixed exception for tickers listed in `failing`. `weekly_failing` independently governs
    `get_weekly_ohlcv` (only), so a test can exercise "price fetch succeeded, signal's extra
    weekly fetch failed" without also failing the daily/price side."""

    def __init__(
        self,
        *,
        prices: dict[str, list[float]] | None = None,
        failing: set[str] | None = None,
        weekly_failing: set[str] | None = None,
    ) -> None:
        self._prices = prices or {}
        self._failing = failing or set()
        self._weekly_failing = weekly_failing or set()

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise TickerNotFoundError(ticker)
        return _frame(self._prices[ticker])

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing or ticker in self._weekly_failing:
            raise DataProviderUnavailableError("provider down")
        return _hold_weekly_ohlcv()


def _make_client(db_session: Session, provider) -> TestClient:
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


class TestGetPortfolio:
    def test_empty_portfolio_returns_zero_equity_and_no_positions(self, client: TestClient) -> None:
        response = client.get("/api/portfolio")

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "equity": {"cash": 0.0, "positions_value": 0.0, "total": 0.0},
            "positions": [],
        }

    def test_empty_portfolio_with_cash_only(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=5000.0))
        db_session.commit()

        test_client = _make_client(db_session, _StubProvider())
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()
        assert body["equity"] == {"cash": 5000.0, "positions_value": 0.0, "total": 5000.0}
        assert body["positions"] == []

    def test_populated_portfolio_enriches_price_and_pnl(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=5000.0))
        db_session.add(
            PositionORM(
                id="pos_1",
                ticker="AAPL",
                quantity=100,
                avg_cost_basis=195.30,
                entry_date=date(2026, 5, 14),
            )
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": [220.0, 228.9]})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()

        [position] = body["positions"]
        assert position["id"] == "pos_1"
        assert position["ticker"] == "AAPL"
        assert position["quantity"] == 100
        assert position["avg_cost_basis"] == pytest.approx(195.30)
        assert position["entry_date"] == "2026-05-14"
        assert position["current_price"] == pytest.approx(228.9)
        assert position["unrealized_pnl_pct"] == pytest.approx((228.9 - 195.30) / 195.30 * 100.0)

        assert body["equity"]["cash"] == pytest.approx(5000.0)
        assert body["equity"]["positions_value"] == pytest.approx(100 * 228.9)
        assert body["equity"]["total"] == pytest.approx(5000.0 + 100 * 228.9)

    def test_multiple_positions_are_all_enriched(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="MSFT", quantity=5, avg_cost_basis=300.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": [110.0], "MSFT": [330.0]})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()
        assert len(body["positions"]) == 2
        prices = {p["ticker"]: p["current_price"] for p in body["positions"]}
        assert prices == {"AAPL": pytest.approx(110.0), "MSFT": pytest.approx(330.0)}
        assert body["equity"]["positions_value"] == pytest.approx(10 * 110.0 + 5 * 330.0)

    def test_positions_are_ordered_by_entry_date_then_id_not_insertion_order(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        # Inserted out of both entry_date and id order, so a passing assertion below can only
        # be explained by an explicit ORDER BY, not incidental SQLite row-return order.
        db_session.add(
            PositionORM(id="pos_z", ticker="GOOG", quantity=1, avg_cost_basis=100.0, entry_date=date(2026, 1, 2))
        )
        db_session.add(
            PositionORM(id="pos_b", ticker="MSFT", quantity=1, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_a", ticker="AAPL", quantity=1, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"GOOG": [1.0], "MSFT": [1.0], "AAPL": [1.0]})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()
        # pos_a and pos_b share entry_date 2026-01-01, so "pos_a" < "pos_b" breaks the tie;
        # pos_z's later entry_date sorts it last regardless of id.
        assert [p["id"] for p in body["positions"]] == ["pos_a", "pos_b", "pos_z"]

    def test_price_fetch_failure_yields_null_price_and_excludes_from_positions_value(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="ZZZZ", quantity=10, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(failing={"ZZZZ"})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()
        [position] = body["positions"]
        assert position["current_price"] is None
        assert position["unrealized_pnl_pct"] is None
        # The failed-price position doesn't contribute to positions_value/total.
        assert body["equity"]["positions_value"] == pytest.approx(0.0)
        assert body["equity"]["total"] == pytest.approx(1000.0)

    def test_empty_price_history_yields_null_price(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": []})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["current_price"] is None
        assert position["unrealized_pnl_pct"] is None

    def test_nan_latest_close_yields_null_price_not_nan_poisoned_total(self, db_session: Session) -> None:
        """Regression test for pr-reviewer's PR #30 finding: neither provider's daily
        series is guaranteed NaN-free (only the derived weekly series gets `.dropna()`),
        so a real, non-empty, non-erroring fetch whose latest close is NaN must be treated
        as a failed fetch by `_latest_close` (current_price=None, excluded from
        positions_value) rather than flowing float('nan') into the running positions_value
        total via `+=` and NaN-poisoning the WHOLE response (equity.positions_value/total
        going to null even for other, perfectly good positions)."""
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="MSFT", quantity=5, avg_cost_basis=200.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": [float("nan")], "MSFT": [250.0]})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()
        by_ticker = {p["ticker"]: p for p in body["positions"]}

        # The NaN-close position degrades exactly like a failed/empty fetch: null price,
        # null pnl, and it must not appear as NaN (which the JSON encoder would otherwise
        # -- via pydantic/FastAPI's float(nan) -> None coercion -- also render as null, but
        # for the wrong reason: today's bug is that the NaN propagates into the *sum*, not
        # just this field).
        assert by_ticker["AAPL"]["current_price"] is None
        assert by_ticker["AAPL"]["unrealized_pnl_pct"] is None

        # The good MSFT position, and equity as a whole, must NOT be null/NaN-poisoned by
        # AAPL's bad close.
        assert by_ticker["MSFT"]["current_price"] == pytest.approx(250.0)
        assert by_ticker["MSFT"]["unrealized_pnl_pct"] == pytest.approx((250.0 - 200.0) / 200.0 * 100.0)
        assert body["equity"]["positions_value"] == pytest.approx(5 * 250.0)
        assert body["equity"]["total"] == pytest.approx(1000.0 + 5 * 250.0)

    def test_mixed_success_and_failure_only_excludes_the_failed_position(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=0.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="ZZZZ", quantity=5, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": [150.0]}, failing={"ZZZZ"})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        body = response.json()
        by_ticker = {p["ticker"]: p for p in body["positions"]}
        assert by_ticker["AAPL"]["current_price"] == pytest.approx(150.0)
        assert by_ticker["ZZZZ"]["current_price"] is None
        assert body["equity"]["positions_value"] == pytest.approx(10 * 150.0)


class TestGetPortfolioSignal:
    """Covers this task's checklist item 4: a position with a computable signal, a position
    whose signal computation fails (nullable fields), and that current_price/unrealized_pnl_pct
    are unaffected either way."""

    def test_position_with_computable_signal_gets_non_null_signal_fields(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": [110.0]})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        # Flat/short daily history + flat weekly history degrades gracefully to HOLD (see
        # app.signals.engine.analyse's own docstring) -- what matters here is that a signal
        # was computed at all, not which one.
        assert position["signal"] == "HOLD"
        assert position["confidence"] == 0
        assert position["confidence_band"] == "Low"
        # current_price/unrealized_pnl_pct are unaffected by the added signal computation.
        assert position["current_price"] == pytest.approx(110.0)
        assert position["unrealized_pnl_pct"] == pytest.approx((110.0 - 100.0) / 100.0 * 100.0)

    def test_price_fetch_failure_also_nulls_signal_fields(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="ZZZZ", quantity=10, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(failing={"ZZZZ"})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["current_price"] is None
        assert position["unrealized_pnl_pct"] is None
        assert position["signal"] is None
        assert position["confidence"] is None
        assert position["confidence_band"] is None

    def test_weekly_fetch_failure_nulls_only_signal_fields_price_still_populated(
        self, db_session: Session
    ) -> None:
        """A position whose *price* fetch succeeded but whose signal-only weekly fetch failed
        still returns a fully-populated current_price/unrealized_pnl_pct -- only the
        signal/confidence/confidence_band fields go null -- since the position is never
        dropped just because its signal couldn't be computed (this task's description)."""
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(prices={"AAPL": [110.0]}, weekly_failing={"AAPL"})
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["current_price"] == pytest.approx(110.0)
        assert position["unrealized_pnl_pct"] == pytest.approx((110.0 - 100.0) / 100.0 * 100.0)
        assert position["signal"] is None
        assert position["confidence"] is None
        assert position["confidence_band"] is None

    def test_mixed_computable_and_signal_failing_positions(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="MSFT", quantity=5, avg_cost_basis=300.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(
            prices={"AAPL": [110.0], "MSFT": [330.0]}, weekly_failing={"MSFT"}
        )
        test_client = _make_client(db_session, provider)
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        by_ticker = {p["ticker"]: p for p in response.json()["positions"]}
        assert by_ticker["AAPL"]["signal"] == "HOLD"
        assert by_ticker["MSFT"]["signal"] is None
        # Both positions still contribute their known price to positions_value.
        assert by_ticker["MSFT"]["current_price"] == pytest.approx(330.0)
