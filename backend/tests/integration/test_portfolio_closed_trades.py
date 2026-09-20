"""Integration tests for GET /api/portfolio/closed-trades (app/api/routers/portfolio.py),
added by the backend-trade-grading task.

Uses an isolated in-memory SQLite session (via a get_db dependency override) and a stub
DataProvider (via a get_data_provider dependency override), matching the pattern in
tests/integration/test_portfolio_delete_position.py -- `closed_trades` rows are inserted
directly rather than produced via DELETE, so each test controls its own entry/exit
price+date fixtures precisely.
"""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.routers.portfolio as portfolio_router
from app.api.dependencies import get_data_provider
from app.data.exceptions import TickerNotFoundError
from app.db.models import ClosedTradeORM
from app.db.session import get_db
from app.indicators.autoenvelope import autoenvelope
from app.main import app
from app.portfolio.models import ExitReason


def _frame(n: int, *, start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    closes = [100.0 + i * 0.1 for i in range(n)]
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


_FRAME = _frame(150)
_ENTRY_TS, _EXIT_TS = _FRAME.index[120], _FRAME.index[130]
_ENTRY_DATE, _EXIT_DATE = _ENTRY_TS.date(), _EXIT_TS.date()


class _StubProvider:
    """Returns `_FRAME` for AAPL (regardless of exact requested range -- `get_daily_ohlcv`
    takes no date argument, per the `DataProvider` protocol), or raises `TickerNotFoundError`
    for any ticker in `failing`."""

    def __init__(self, *, failing: set[str] | None = None) -> None:
        self._failing = failing or set()

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing:
            raise TickerNotFoundError(ticker)
        return _FRAME

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:  # pragma: no cover - unused here
        raise NotImplementedError("GET /api/portfolio/closed-trades never fetches weekly data")


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


def _add_closed_trade(db_session: Session, *, id: str = "default", **overrides: object) -> ClosedTradeORM:
    defaults: dict[str, object] = dict(
        id=f"trade_{id}",
        ticker="AAPL",
        quantity=10.0,
        entry_price=101.0,
        entry_date=_ENTRY_DATE,
        exit_price=103.0,
        exit_date=_EXIT_DATE,
        realized_pnl=20.0,
        exit_reason=ExitReason.TARGET_HIT.value,
    )
    defaults.update(overrides)
    row = ClosedTradeORM(**defaults)
    db_session.add(row)
    db_session.commit()
    return row


class TestGetClosedTradesEmpty:
    def test_no_closed_trades_returns_empty_list(self, client: TestClient) -> None:
        response = client.get("/api/portfolio/closed-trades")
        assert response.status_code == 200
        assert response.json() == {"items": []}


class TestGetClosedTradesFields:
    def test_returns_all_recorded_fields(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="a")

        response = client.get("/api/portfolio/closed-trades")
        assert response.status_code == 200
        [item] = response.json()["items"]
        assert item["ticker"] == "AAPL"
        assert item["quantity"] == pytest.approx(10.0)
        assert item["entry_price"] == pytest.approx(101.0)
        assert item["entry_date"] == _ENTRY_DATE.isoformat()
        assert item["exit_price"] == pytest.approx(103.0)
        assert item["exit_date"] == _EXIT_DATE.isoformat()
        assert item["realized_pnl"] == pytest.approx(20.0)
        assert item["exit_reason"] == "target_hit"
        # No entry_notes was passed to _add_closed_trade above -- defaults to null, not an
        # empty string or omitted field.
        assert item["entry_notes"] is None

    def test_entry_notes_is_carried_through_when_present(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", entry_notes="Breakout above resistance.")

        response = client.get("/api/portfolio/closed-trades")
        [item] = response.json()["items"]
        assert item["entry_notes"] == "Breakout above resistance."

    def test_grades_match_the_formulas_applied_to_the_fixture_frame(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", entry_price=101.0, exit_price=103.0)

        response = client.get("/api/portfolio/closed-trades")
        [item] = response.json()["items"]

        entry_high, entry_low = float(_FRAME.loc[_ENTRY_TS, "high"]), float(_FRAME.loc[_ENTRY_TS, "low"])
        exit_high, exit_low = float(_FRAME.loc[_EXIT_TS, "high"]), float(_FRAME.loc[_EXIT_TS, "low"])
        channel = autoenvelope(_FRAME["close"])
        channel_upper, channel_lower = (
            float(channel.loc[_ENTRY_TS, "upper"]),
            float(channel.loc[_ENTRY_TS, "lower"]),
        )

        expected_buy_grade = (entry_high - 101.0) / (entry_high - entry_low) * 100.0
        expected_sell_grade = (103.0 - exit_low) / (exit_high - exit_low) * 100.0
        expected_trade_grade = (103.0 - 101.0) / (channel_upper - channel_lower) * 100.0

        assert item["buy_grade_pct"] == pytest.approx(expected_buy_grade)
        assert item["sell_grade_pct"] == pytest.approx(expected_sell_grade)
        assert item["trade_grade_pct"] == pytest.approx(expected_trade_grade)


class TestGetClosedTradesOrdering:
    def test_most_recently_exited_trade_first(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="older", exit_date=date(2020, 1, 1))
        _add_closed_trade(db_session, id="newer", exit_date=date(2020, 6, 1))

        response = client.get("/api/portfolio/closed-trades")
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == ["trade_newer", "trade_older"]

    def test_same_day_exits_tiebroken_by_id_descending(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", exit_date=_EXIT_DATE)
        _add_closed_trade(db_session, id="b", exit_date=_EXIT_DATE)

        response = client.get("/api/portfolio/closed-trades")
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == ["trade_b", "trade_a"]


class TestGetClosedTradesGradingDegradesGracefully:
    def test_null_grades_when_ticker_history_fetch_fails(self, db_session: Session) -> None:
        client = _make_client(db_session, _StubProvider(failing={"ZZZZ"}))
        try:
            _add_closed_trade(db_session, id="a", ticker="ZZZZ")

            response = client.get("/api/portfolio/closed-trades")
            assert response.status_code == 200
            [item] = response.json()["items"]
            assert item["ticker"] == "ZZZZ"
            assert item["buy_grade_pct"] is None
            assert item["sell_grade_pct"] is None
            assert item["trade_grade_pct"] is None
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

    def test_null_grades_when_entry_date_not_in_fetched_history(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", entry_date=date(1999, 1, 1))

        response = client.get("/api/portfolio/closed-trades")
        [item] = response.json()["items"]
        assert item["buy_grade_pct"] is None
        assert item["sell_grade_pct"] is None
        assert item["trade_grade_pct"] is None
        # The row itself is still fully present -- ungradeable is not the same as unlisted.
        assert item["entry_date"] == "1999-01-01"

    def test_one_ticker_fetch_failure_does_not_affect_another_tickers_grades(
        self, db_session: Session
    ) -> None:
        client = _make_client(db_session, _StubProvider(failing={"ZZZZ"}))
        try:
            _add_closed_trade(db_session, id="ok", ticker="AAPL")
            _add_closed_trade(db_session, id="bad", ticker="ZZZZ")

            response = client.get("/api/portfolio/closed-trades")
            items = {item["id"]: item for item in response.json()["items"]}
            assert items["trade_ok"]["trade_grade_pct"] is not None
            assert items["trade_bad"]["trade_grade_pct"] is None
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)


class TestGetClosedTradesSharesOneFetchPerTicker:
    def test_two_trades_same_ticker_only_fetch_once(
        self, db_session: Session
    ) -> None:
        call_count = 0
        base_provider = _StubProvider()

        class _CountingProvider(_StubProvider):
            def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
                nonlocal call_count
                call_count += 1
                return base_provider.get_daily_ohlcv(ticker)

        client = _make_client(db_session, _CountingProvider())
        try:
            _add_closed_trade(db_session, id="a", ticker="AAPL")
            _add_closed_trade(db_session, id="b", ticker="AAPL", exit_date=date(2020, 1, 2))

            response = client.get("/api/portfolio/closed-trades")
            assert response.status_code == 200
            assert call_count == 1
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

    def test_two_trades_same_ticker_only_filter_and_channel_once(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`backend-trade-grading-followups`: `drop_malformed_daily_bars`/`autoenvelope` --
        the two more expensive per-ticker derivations `grade_closed_trade` used to redo once
        per row -- must also be shared across every closed-trade row for the same ticker, not
        just the underlying `get_daily_ohlcv` fetch (already covered above).

        Note on what a regression would actually look like here (docs/tasks/backend-trade-
        grading-followups-followups.json): `drop_malformed_daily_bars`/`autoenvelope` are
        separate module-level name bindings in `app.portfolio.grading` vs.
        `app.api.routers.portfolio`, and this test's `monkeypatch.setattr(portfolio_router,
        ...)` only intercepts the router module's own binding. If `_grade_closed_trades` were
        reverted to call `grade_closed_trade` per row (the pre-fix, O(n)-per-row behavior),
        that path never calls through the router's own `drop_malformed_daily_bars`/
        `autoenvelope` bindings at all -- so the counters below would read 0, not 2 (not a
        doubled per-row count). The assertions still correctly fail on that regression
        (`assert 0 == 1`), just via a different failure than "counted twice"."""
        dropna_calls = 0
        autoenvelope_calls = 0
        real_drop_malformed = portfolio_router.drop_malformed_daily_bars
        real_autoenvelope = portfolio_router.autoenvelope

        def _counting_drop_malformed(*args: object, **kwargs: object) -> pd.DataFrame:
            nonlocal dropna_calls
            dropna_calls += 1
            return real_drop_malformed(*args, **kwargs)  # type: ignore[arg-type]

        def _counting_autoenvelope(*args: object, **kwargs: object) -> pd.DataFrame:
            nonlocal autoenvelope_calls
            autoenvelope_calls += 1
            return real_autoenvelope(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(portfolio_router, "drop_malformed_daily_bars", _counting_drop_malformed)
        monkeypatch.setattr(portfolio_router, "autoenvelope", _counting_autoenvelope)

        _add_closed_trade(db_session, id="a", ticker="AAPL")
        _add_closed_trade(db_session, id="b", ticker="AAPL", exit_date=date(2020, 1, 2))

        response = client.get("/api/portfolio/closed-trades")
        assert response.status_code == 200
        assert dropna_calls == 1
        assert autoenvelope_calls == 1
