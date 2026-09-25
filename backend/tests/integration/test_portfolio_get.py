"""Integration tests for GET /api/portfolio (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override) and a stub
DataProvider (via a get_data_provider dependency override), matching the pattern in
tests/integration/test_portfolio_positions.py and tests/unit/data/test_cache.py, so these
tests never touch the real fintrade.db file or a live market data provider.

The `db_session` fixture lives in tests/integration/conftest.py; this module keeps its own
`client` fixture because it additionally needs the get_data_provider override below.
"""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider, get_ibkr_provider
from app.data.exceptions import DataProviderUnavailableError, TickerNotFoundError
from app.data.ibkr_provider import GatewayStatus, IBKRBar
from app.db.models import AccountORM, PositionORM
from app.db.session import get_db
from app.main import app
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


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
            "trading_mode": {"mode": "swing", "day_trader_timeframe_triple": None},
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
                entry_notes="Breakout above resistance.",
                strategy="Pullback to value",
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
        assert position["entry_notes"] == "Breakout above resistance."
        assert position["strategy"] == "Pullback to value"

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
        # No entry_notes was recorded for either position (created directly via PositionORM
        # above, not through POST /api/portfolio/positions) -- both come back null, not an
        # empty string or omitted field.
        assert all(p["entry_notes"] is None for p in body["positions"])
        assert all(p["strategy"] is None for p in body["positions"])

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
        as a failed fetch by `latest_close` (current_price=None, excluded from
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

    def test_malformed_open_high_low_on_latest_bar_nulls_signal_but_not_price(
        self, db_session: Session
    ) -> None:
        """Today's daily bar has a real `close` (110.0) but NaN `open`/`high`/`low` -- the
        "not yet settled" yfinance shape `app.portfolio.pricing.latest_close` already
        tolerates for `current_price` (it only checks `close`), same as
        test_portfolio_risk.py's `test_malformed_open_high_low_on_latest_bar_does_not_
        suppress_stop_hit`. Unlike GET /api/portfolio/risk (whose `evaluate_exit_flags` only
        ever reads the latest bar's `close`), `analyse()` reads the latest bar's open/high/low
        too (Elder-Ray/Wave/Trigger) -- so it can't safely be handed this bar with
        `require_full_ohlc_on_latest_bar=False` the way `get_risk` is. Before this test's fix,
        `_compute_position_signal` filtered with the strict default, which dropped this bar
        entirely and silently computed the signal from yesterday's bar instead, while
        `current_price` kept reflecting today's 110.0 close -- a one-day desync with no error
        and no null to flag it. The fix instead detects that the latest bar didn't survive
        filtering and returns `None`, so the signal fields go null instead of stale."""
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _frame([100.0, 105.0, 110.0])
        daily.loc[daily.index[-1], ["open", "high", "low"]] = float("nan")

        class _MalformedLatestBarProvider:
            def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
                return daily

            def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
                return _hold_weekly_ohlcv()

        test_client = _make_client(db_session, _MalformedLatestBarProvider())
        try:
            response = test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        # current_price still reflects today's real close (permissive, close-only check).
        assert position["current_price"] == pytest.approx(110.0)
        assert position["unrealized_pnl_pct"] == pytest.approx((110.0 - 100.0) / 100.0 * 100.0)
        # signal fields go null rather than silently reflecting yesterday's 105.0 bar.
        assert position["signal"] is None
        assert position["confidence"] is None
        assert position["confidence_band"] is None


def _ibkr_bars(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[float],
    *, start: datetime, step_minutes: int,
) -> list[IBKRBar]:
    # Same shape as tests/integration/test_stocks_analysis.py's/test_watchlist.py's own
    # identically-purposed helpers -- duplicated per this feature area's own established
    # per-test-file-fixture convention.
    return [
        IBKRBar(
            timestamp=start + timedelta(minutes=step_minutes * i),
            open=close, high=highs[i], low=lows[i], close=close, volume=volumes[i],
        )
        for i, close in enumerate(closes)
    ]


def _day_trader_long_term_bars() -> list[IBKRBar]:
    closes = [100 * (1.05**i) for i in range(40)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    volumes = [1_000_000.0] * 40
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60)


def _day_trader_intermediate_bars() -> list[IBKRBar]:
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    closes.append(closes[-1] - 1.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    volumes = [1_000_000.0] * 25 + [9_000_000.0, 3_000_000.0]
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10)


def _day_trader_short_term_bars() -> list[IBKRBar]:
    closes = [95.5, 99.5]
    highs = [96.0, 100.0]
    lows = [94.0, 98.5]
    volumes = [500_000.0, 500_000.0]
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2)


_FULLY_INTRADAY_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("60m"),
    intermediate=TimeframeInterval.parse("10m"),
    short_term=TimeframeInterval.parse("2m"),
)


class _StubIBKRProvider:
    """Same convention as test_stocks_analysis.py's own `_StubIBKRProvider`."""

    def __init__(
        self,
        *,
        resolve_conid_result: int | None | Exception = 999,
        get_hourly_bars_by_bar_size: dict[str, list[IBKRBar]] | None = None,
    ) -> None:
        self._resolve_conid_result = resolve_conid_result
        self._get_hourly_bars_by_bar_size = get_hourly_bars_by_bar_size or {}

    def resolve_conid(self, ticker: str) -> int | None:
        if isinstance(self._resolve_conid_result, Exception):
            raise self._resolve_conid_result
        return self._resolve_conid_result

    def get_hourly_bars(self, conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
        return self._get_hourly_bars_by_bar_size[bar_size]

    def get_gateway_status(self) -> GatewayStatus:
        return GatewayStatus(state="available")


def _all_legs_available_ibkr_provider() -> _StubIBKRProvider:
    return _StubIBKRProvider(
        get_hourly_bars_by_bar_size={
            "1h": _day_trader_long_term_bars(),
            "10min": _day_trader_intermediate_bars(),
            "2min": _day_trader_short_term_bars(),
        }
    )


class _PerTickerStubIBKRProvider:
    """Unlike `_StubIBKRProvider` above (one fixed conid/bar-set shared by every ticker in a
    request), this maps each distinct ticker to its own resolvability and bars -- so a
    multi-position `GET /api/portfolio` test can assert two genuinely different, ticker-keyed
    outcomes came back correctly matched, not just 'some day-trader outcome or other' for both
    positions (see docs/tasks/backend-day-trader-timeframe-mode-api-followups-followups.json's
    `decisions` entry, and `test_day_trader_signal.py`'s own identically-motivated
    `test_maps_each_distinct_ticker_to_its_own_outcome_not_a_shared_or_swapped_one`, whose unit
    -level coverage this integration test complements rather than duplicates -- that test mocks
    `compute_day_trader_signal` directly; this one exercises the real IBKR-provider-fetch ->
    `analyse_day_trader` pipeline for each ticker through the actual router)."""

    def __init__(self, bars_by_ticker: dict[str, dict[str, list[IBKRBar]] | None]) -> None:
        # `None` for a ticker means "this ticker can't be resolved to a conid at all" (mirrors
        # a real IBKR gateway that doesn't recognize the symbol) -> unavailable_reason set,
        # not a raised exception.
        self._bars_by_ticker = bars_by_ticker
        self._ticker_by_conid: dict[int, str] = {}
        self._next_conid = 1000

    def resolve_conid(self, ticker: str) -> int | None:
        if self._bars_by_ticker.get(ticker) is None:
            return None
        conid = self._next_conid
        self._next_conid += 1
        self._ticker_by_conid[conid] = ticker
        return conid

    def get_hourly_bars(self, conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
        ticker = self._ticker_by_conid[conid]
        bars = self._bars_by_ticker[ticker]
        assert bars is not None
        return bars[bar_size]

    def get_gateway_status(self) -> GatewayStatus:
        return GatewayStatus(state="available")


class TestDayTraderMode:
    """`GET /api/portfolio` while the global trading mode is `day_trader`
    (`backend-day-trader-timeframe-mode-api-followups`) -- `current_price`/`unrealized_pnl_pct`
    stay swing-provider-derived either way (`PortfolioResponse.trading_mode`'s own field
    description); only `signal`/`confidence`/`confidence_band` switch to IBKR-derived data."""

    def _client(self, db_session: Session, provider, ibkr_provider: object | None) -> TestClient:
        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_data_provider] = lambda: provider
        app.dependency_overrides[get_ibkr_provider] = lambda: ibkr_provider
        return TestClient(app)

    def _get(self, db_session: Session, provider, ibkr_provider: object | None):
        test_client = self._client(db_session, provider, ibkr_provider)
        try:
            return test_client.get("/api/portfolio")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)
            app.dependency_overrides.pop(get_ibkr_provider, None)

    def test_position_gets_a_real_day_trader_mode_signal_while_price_stays_swing_derived(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        # Flat swing daily/weekly (HOLD-shaped) -- deliberately NOT the fixture that would
        # itself produce a BUY under plain swing `analyse()`, so the BUY asserted below can only
        # come from the IBKR legs going through `analyse_day_trader`, not a silent swing
        # fallback (same discriminating-fixture-pairing convention as test_stocks_analysis.py's/
        # test_watchlist.py's own `TestDayTraderMode`).
        provider = _StubProvider(prices={"AAPL": [110.0]})

        response = self._get(db_session, provider, _all_legs_available_ibkr_provider())

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "day_trader"
        [position] = body["positions"]
        assert position["current_price"] == pytest.approx(110.0)
        assert position["unrealized_pnl_pct"] == pytest.approx((110.0 - 100.0) / 100.0 * 100.0)
        assert position["signal"] == "BUY"
        assert 0 <= position["confidence"] <= 100

    def test_ibkr_disabled_nulls_signal_but_price_stays_populated(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(prices={"AAPL": [110.0]})

        response = self._get(db_session, provider, ibkr_provider=None)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        # Deliberately NOT gated on the swing price fetch (this task's own decision, contrasting
        # with GET /api/stocks/{ticker}/analysis's own day-trader branch) -- current_price is
        # still populated even though signal is null for an entirely different (IBKR) reason.
        assert position["current_price"] == pytest.approx(110.0)
        assert position["signal"] is None
        assert position["confidence"] is None
        assert position["confidence_band"] is None

    def test_price_fetch_failure_does_not_suppress_an_otherwise_computable_day_trader_signal(
        self, db_session: Session
    ) -> None:
        """The reverse of the swing-mode case (test_price_fetch_failure_also_nulls_signal_fields
        above): in day-trader mode, this position's signal is computed from entirely independent
        IBKR data, so a failed swing price fetch must NOT also null out the signal -- see
        `_compute_position_signal`'s own docstring for why this is a deliberate improvement over
        GET /api/stocks/{ticker}/analysis's own day-trader branch."""
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="ZZZZ", quantity=10, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(failing={"ZZZZ"})

        response = self._get(db_session, provider, _all_legs_available_ibkr_provider())

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["current_price"] is None
        assert position["signal"] == "BUY"
        assert 0 <= position["confidence"] <= 100

    def test_two_distinct_tickers_each_get_their_own_signal_not_a_shared_or_swapped_one(
        self, db_session: Session
    ) -> None:
        """The discriminating multi-position case: `compute_day_trader_signals_concurrently`'s
        per-ticker fan-out (`app.api.day_trader_signal`) must map each position's own ticker
        to its own outcome, not the other's -- AAPL is deliberately given the full, resolvable
        bar set (`_all_legs_available_ibkr_provider`'s own fixture, already asserted elsewhere
        in this class to produce BUY) while MSFT is deliberately unresolvable (no conid), so a
        bug that mixed up which future's result lands under which ticker key (e.g. always
        returning the last-completed future's outcome for every ticker, the exact mutation
        `test_day_trader_signal.py`'s own unit-level equivalent guards against) would make
        this test fail -- either both positions would show the same signal, or they'd show
        each other's."""
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="MSFT", quantity=5, avg_cost_basis=200.0, entry_date=date(2026, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(prices={"AAPL": [110.0], "MSFT": [220.0]})
        ibkr_provider = _PerTickerStubIBKRProvider(
            {
                "AAPL": {
                    "1h": _day_trader_long_term_bars(),
                    "10min": _day_trader_intermediate_bars(),
                    "2min": _day_trader_short_term_bars(),
                },
                "MSFT": None,
            }
        )

        response = self._get(db_session, provider, ibkr_provider)

        assert response.status_code == 200
        positions_by_ticker = {p["ticker"]: p for p in response.json()["positions"]}
        assert positions_by_ticker.keys() == {"AAPL", "MSFT"}
        aapl = positions_by_ticker["AAPL"]
        msft = positions_by_ticker["MSFT"]
        # Both positions' swing-derived current_price fields are unaffected either way.
        assert aapl["current_price"] == pytest.approx(110.0)
        assert msft["current_price"] == pytest.approx(220.0)
        # AAPL's own resolvable IBKR bars produce a real BUY signal (same fixture already
        # asserted to do so elsewhere in this class).
        assert aapl["signal"] == "BUY"
        assert 0 <= aapl["confidence"] <= 100
        # MSFT's own unresolvable-conid outcome must stay MSFT's -- not swapped onto AAPL,
        # and not silently defaulted to AAPL's BUY.
        assert msft["signal"] is None
        assert msft["confidence"] is None
        assert msft["confidence_band"] is None

    def test_swing_mode_default_is_unaffected_by_a_configured_day_trader_triple(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=1000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.SWING, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(prices={"AAPL": [110.0]})

        response = self._get(db_session, provider, ibkr_provider=None)

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "swing"
        [position] = body["positions"]
        assert position["signal"] == "HOLD"
