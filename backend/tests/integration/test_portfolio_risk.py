"""Integration tests for GET /api/portfolio/risk (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override) and a stub
DataProvider (via a get_data_provider dependency override), same pattern as
tests/integration/test_portfolio_get.py. The `db_session` fixture lives in
tests/integration/conftest.py; this module keeps its own `client`-building helper because it
additionally needs the get_data_provider override.

Fixture math (protective stop, distance-to-stop, risk percentages) is hand-derived the same
way tests/unit/test_portfolio_risk.py's TestProtectiveStop reference-value test is: the
5-quiet-day-then-one-more-day daily series and its 98.465306 stop are reused verbatim from
there, then combined with chosen quantity/cash/price to land in a specific rule-breach
bracket. Individual exit flag conditions (stop_hit, tide_flipped_bearish, etc.) already have
exhaustive hand-computed coverage in tests/unit/test_portfolio_exits.py; these integration
tests instead focus on this route's own job -- wiring positions/prices/history together,
threshold-derived response fields (two_percent_rule_breached/six_percent_rule_breached), and
degrade-gracefully exclusion of a position whose price/history couldn't be fetched.
"""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.data.exceptions import TickerNotFoundError
from app.db.models import AccountORM, PositionORM
from app.db.session import get_db
from app.main import app
from app.portfolio.models import Position
from app.portfolio.risk import protective_stop

# The hand-computed 5-row reference series from test_portfolio_risk.py's
# TestProtectiveStop.test_reference_values_short_series, plus one more "today" row appended
# (close=110, comfortably above the resulting stop, so no position in these tests hits its
# stop unless a test specifically wants stop_hit).
_QUIET_CLOSES = [100.0, 102.0, 101.0, 103.0, 104.0, 110.0]
_QUIET_LOWS = [99.0, 100.0, 99.0, 101.0, 102.0, 109.0]
_QUIET_STOP = 98.46530612244898  # protective_stop() of the first 5 rows (today excluded)
_QUIET_DISTANCE = _QUIET_CLOSES[-1] - _QUIET_STOP

_UPTREND_CLOSES = [100.0 + i * 0.2 for i in range(16)]
_UPTREND_LOWS = [c - 0.5 for c in _UPTREND_CLOSES]

_FLAT_WEEKLY_CLOSES = [100.0] * 5


def _daily_frame(closes: list[float], lows: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": lows,
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
    )


def _weekly_frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
    )


class _StubProvider:
    """A DataProvider stand-in serving fixed daily/weekly frames per ticker, or raising a
    fixed exception for tickers listed in `failing_daily`/`failing_weekly`.

    `weekly_calls` records every ticker `get_weekly_ohlcv` was actually invoked for, in call
    order -- used to pin down that get_risk()'s protective_stop()-before-weekly-fetch
    reordering (app/api/routers/portfolio.py) really does skip the weekly round trip for a
    position already excluded on the daily side, not just that the response happens to come
    out the same either way."""

    def __init__(
        self,
        *,
        daily: dict[str, pd.DataFrame] | None = None,
        weekly: dict[str, pd.DataFrame] | None = None,
        failing_daily: set[str] | None = None,
        failing_weekly: set[str] | None = None,
    ) -> None:
        self._daily = daily or {}
        self._weekly = weekly or {}
        self._failing_daily = failing_daily or set()
        self._failing_weekly = failing_weekly or set()
        self.weekly_calls: list[str] = []

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_daily:
            raise TickerNotFoundError(ticker)
        return self._daily[ticker]

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        self.weekly_calls.append(ticker)
        if ticker in self._failing_weekly:
            raise TickerNotFoundError(ticker)
        return self._weekly[ticker]


def _make_client(db_session: Session, provider: _StubProvider) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


def _get_risk(db_session: Session, provider: _StubProvider):
    test_client = _make_client(db_session, provider)
    try:
        return test_client.get("/api/portfolio/risk")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)


class TestGetRisk:
    def test_empty_portfolio_has_zero_risk(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=10_000.0))
        db_session.commit()

        response = _get_risk(db_session, _StubProvider())

        assert response.status_code == 200
        assert response.json() == {
            "total_open_risk_pct": 0.0,
            "six_percent_rule_breached": False,
            "positions": [],
        }

    def test_clean_portfolio_has_no_breaches_or_flags(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_UPTREND_CLOSES, _UPTREND_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()
        assert body["six_percent_rule_breached"] is False
        assert body["total_open_risk_pct"] < 2.0

        [position] = body["positions"]
        assert position["id"] == "pos_1"
        assert position["ticker"] == "AAPL"
        assert position["two_percent_rule_breached"] is False

        stop = protective_stop(
            Position(
                id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0,
                entry_date=date(2026, 1, 1), current_price=_UPTREND_CLOSES[-1],
            ),
            daily.iloc[:-1],
        )
        assert position["protective_stop"] == pytest.approx(stop)

    def test_oversized_position_breaches_two_percent_rule_only(self, db_session: Session) -> None:
        # Single position: quantity/cash chosen so this position's own risk (~3.46%) clears
        # the 2% rule but the portfolio (which only holds this one position, so
        # total_open_risk_pct == this position's own risk) stays under the 6% rule.
        db_session.add(AccountORM(id=1, cash=6_700.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=30.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()

        expected_risk_pct = 30.0 * _QUIET_DISTANCE / (6_700.0 + 30.0 * 110.0) * 100.0
        assert 2.0 < expected_risk_pct < 6.0

        [position] = body["positions"]
        assert position["position_risk_pct"] == pytest.approx(expected_risk_pct)
        assert position["two_percent_rule_breached"] is True
        assert "two_percent_rule_breached" in position["exit_flags"]
        assert body["total_open_risk_pct"] == pytest.approx(expected_risk_pct)
        assert body["six_percent_rule_breached"] is False

    def test_multiple_positions_breach_six_percent_rule(self, db_session: Session) -> None:
        # Two positions, no cash: each one's own risk (~5.24%) is individually under 6% but
        # they combine to a portfolio-wide total_open_risk_pct well past the 6% rule, so both
        # positions carry 'six_percent_rule_contributor'.
        db_session.add(AccountORM(id=1, cash=0.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=30.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="MSFT", quantity=30.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(
            daily={"AAPL": daily, "MSFT": daily}, weekly={"AAPL": weekly, "MSFT": weekly}
        )

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()

        assert body["total_open_risk_pct"] > 6.0
        assert body["six_percent_rule_breached"] is True
        assert len(body["positions"]) == 2
        for position in body["positions"]:
            assert "six_percent_rule_contributor" in position["exit_flags"]

    def test_position_with_failed_price_fetch_is_excluded(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="ZZZZ", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(failing_daily={"ZZZZ"})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == []
        assert body["total_open_risk_pct"] == pytest.approx(0.0)
        assert body["six_percent_rule_breached"] is False

    def test_position_with_insufficient_daily_history_is_excluded(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        # A single daily row: enough for a current price, but too little for
        # evaluate_exit_flags's own >= 2 row requirement.
        provider = _StubProvider(daily={"AAPL": _daily_frame([100.0], [99.0])})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        assert response.json()["positions"] == []

    def test_position_with_failed_weekly_fetch_is_excluded(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        provider = _StubProvider(daily={"AAPL": daily}, failing_weekly={"AAPL"})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        assert response.json()["positions"] == []

    def test_mixed_healthy_and_excluded_positions(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="ZZZZ", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_UPTREND_CLOSES, _UPTREND_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(
            daily={"AAPL": daily}, weekly={"AAPL": weekly}, failing_daily={"ZZZZ"}
        )

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()
        [position] = body["positions"]
        assert position["ticker"] == "AAPL"

    def test_position_with_daily_frame_missing_low_column_is_excluded(self, db_session: Session) -> None:
        # Enough rows/columns for _latest_close (which only needs "close") to succeed, but
        # protective_stop's own column validation requires "low" too -- the resulting
        # ValueError must exclude the position from the response rather than propagate as an
        # unhandled 500.
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        malformed_daily = pd.DataFrame({"close": [100.0, 101.0], "open": [100.0, 101.0], "high": [101.0, 102.0], "volume": [1000.0, 1000.0]})
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": malformed_daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        assert response.json()["positions"] == []

    def test_daily_excluded_position_never_triggers_weekly_fetch(self, db_session: Session) -> None:
        # Two positions: pos_1 is excluded on the daily side (missing "low" column, same
        # shape as test_position_with_daily_frame_missing_low_column_is_excluded above), pos_2
        # is fully healthy. protective_stop() runs before the weekly fetch precisely so a
        # daily-side exclusion never pays for a weekly round trip that would just be thrown
        # away -- assert that ordering as behavior (via the stub's recorded weekly_calls)
        # rather than only via the response shape, which would pass identically even if the
        # weekly fetch were wastefully attempted for ZZZZ too.
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="ZZZZ", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_2", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        malformed_daily = pd.DataFrame({"close": [100.0, 101.0], "open": [100.0, 101.0], "high": [101.0, 102.0], "volume": [1000.0, 1000.0]})
        healthy_daily = _daily_frame(_UPTREND_CLOSES, _UPTREND_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(
            daily={"ZZZZ": malformed_daily, "AAPL": healthy_daily}, weekly={"AAPL": weekly}
        )

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["ticker"] == "AAPL"
        assert provider.weekly_calls == ["AAPL"]

    def test_position_with_weekly_frame_missing_close_column_is_excluded(self, db_session: Session) -> None:
        # protective_stop succeeds (the daily frame is well-formed), but evaluate_exit_flags's
        # own weekly-column validation raises for a weekly frame missing "close" -- must
        # exclude the position rather than propagate as an unhandled 500.
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        malformed_weekly = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "volume": [1000.0, 1000.0]})
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": malformed_weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        assert response.json()["positions"] == []

    def test_non_positive_equity_total_degrades_total_open_risk_pct_to_zero(
        self, db_session: Session
    ) -> None:
        # Cash negative enough to make account.equity.total <= 0 even with a healthy,
        # fully-computable position: total_open_risk_pct calls position_risk_pct internally
        # for every position in `stops`, which raises ValueError whenever
        # account.equity.total <= 0 -- this must degrade to total_open_risk_pct=0.0 (and no
        # six-percent breach) rather than propagate as an unhandled 500. The per-position
        # loop hits the same ValueError for the same reason and excludes the position, same
        # as any other can't-be-computed case.
        db_session.add(AccountORM(id=1, cash=-2_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()
        assert body["total_open_risk_pct"] == pytest.approx(0.0)
        assert body["six_percent_rule_breached"] is False
        assert body["positions"] == []

    def test_stop_hit_flag_surfaces_in_exit_flags(self, db_session: Session) -> None:
        # 10 quiet days establishing a stop near 98, then a sharp gap-down close today that
        # breaches it -- mirrors test_portfolio_exits.py's TestEvaluateExitFlagsEndToEnd
        # .test_real_stop_hit.
        closes = [100.0] * 10 + [80.0]
        lows = [99.0] * 10 + [78.0]
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(closes, lows)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert "stop_hit" in position["exit_flags"]
