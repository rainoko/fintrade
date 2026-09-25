"""Integration tests for GET /api/portfolio/risk (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override) and a stub
DataProvider (via a get_data_provider dependency override), same pattern as
tests/integration/test_portfolio_get.py. The `db_session` fixture lives in
tests/integration/conftest.py; this module keeps its own `client`-building helper because it
additionally needs the get_data_provider override.

Fixture math (protective stop, distance-to-stop, risk percentages) is hand-derived the same
way tests/unit/test_portfolio_risk.py's TestProtectiveStop reference-value test is: the
5-quiet-day-then-one-more-day daily series and its 97.930612 stop are reused verbatim from
there, then combined with chosen quantity/cash/price to land in a specific rule-breach
bracket. Individual exit flag conditions (stop_hit, tide_flipped_bearish, etc.) already have
exhaustive hand-computed coverage in tests/unit/test_portfolio_exits.py; these integration
tests instead focus on this route's own job -- wiring positions/prices/history together,
threshold-derived response fields (two_percent_rule_breached/six_percent_rule_breached), and
degrade-gracefully exclusion of a position whose price/history couldn't be fetched.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider, get_ibkr_provider
from app.data.exceptions import TickerNotFoundError
from app.data.ibkr_provider import GatewayStatus, IBKRBar
from app.db.models import AccountORM, ClosedTradeORM, PositionORM
from app.db.session import get_db
from app.main import app
from app.portfolio.models import ExitReason, Position
from app.portfolio.risk import protective_stop, ratchet_trailing_profit_stop, stop_from_price_action
from app.signals.engine import analyse, drop_malformed_daily_bars
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


def _today() -> date:
    """Matches `app.time_utils.today()` exactly (UTC-derived, not local
    `date.today()`) -- see the backend-trade-history-table-followups task's `decisions`
    entry for why: a fixture built from local `date.today()` would intermittently disagree
    with the UTC-based production value outside a UTC-local-timezone runner (and, near a
    calendar-month boundary, could land a `ClosedTradeORM` fixture row in the wrong
    this-month/prior-month bucket relative to what the UTC `as_of` the route actually uses),
    even though dev container/CI both run in UTC today."""
    return datetime.now(UTC).date()


# The hand-computed 5-row reference series from test_portfolio_risk.py's
# TestProtectiveStop.test_reference_values_short_series, plus one more "today" row appended
# (close=110, comfortably above the resulting stop, so no position in these tests hits its
# stop unless a test specifically wants stop_hit).
_QUIET_CLOSES = [100.0, 102.0, 101.0, 103.0, 104.0, 110.0]
_QUIET_LOWS = [99.0, 100.0, 99.0, 101.0, 102.0, 109.0]
_QUIET_STOP = 97.93061224489796  # protective_stop() of the first 5 rows (today excluded)
_QUIET_DISTANCE = _QUIET_CLOSES[-1] - _QUIET_STOP

_UPTREND_CLOSES = [100.0 + i * 0.2 for i in range(16)]
_UPTREND_LOWS = [c - 0.5 for c in _UPTREND_CLOSES]

_FLAT_WEEKLY_CLOSES = [100.0] * 5


def _daily_frame(closes: list[float], lows: list[float]) -> pd.DataFrame:
    # A real `pd.DatetimeIndex` (matching every real data provider's own daily frame shape),
    # not the plain `RangeIndex` a bare `pd.DataFrame({...})` would default to -- needed since
    # `get_risk` now also runs `app.signals.support_resistance.detect_support_resistance_zones`
    # over this same frame for `profit_target` (backend-profit-target-open-position), which
    # computes `length_days` as a genuine `Timestamp` subtraction (`.days`) whenever a
    # multi-touch cluster forms; a `RangeIndex` int64 has no `.days` attribute and would raise
    # an unhandled `AttributeError` the moment a fixture happened to contain a real repeated-
    # price cluster (see `test_stop_hit_flag_surfaces_in_exit_flags`, whose 10 identical-close
    # rows are exactly such a cluster).
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": lows,
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


def _weekly_frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        },
        index=pd.date_range("2020-01-06", periods=len(closes), freq="W", name="date"),
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
            "trading_mode": {"mode": "swing", "day_trader_timeframe_triple": None},
            "total_open_risk_pct": 0.0,
            "realized_losses_this_month_pct": 0.0,
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
        # Single position: quantity/cash chosen so this position's own risk (~3.62%) clears
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
        # Two positions, no cash: each one's own risk (~5.49%) is individually under 6% but
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

    def test_positions_are_ordered_by_entry_date_then_id_not_insertion_order(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=1_000.0))
        # Inserted out of both entry_date and id order (same technique as
        # test_portfolio_get.py's analogous test) so a passing assertion below can only be
        # explained by the shared _ordered_positions() helper's explicit ORDER BY.
        db_session.add(
            PositionORM(id="pos_z", ticker="GOOG", quantity=1.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 2))
        )
        db_session.add(
            PositionORM(id="pos_b", ticker="MSFT", quantity=1.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.add(
            PositionORM(id="pos_a", ticker="AAPL", quantity=1.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(
            daily={"GOOG": daily, "MSFT": daily, "AAPL": daily},
            weekly={"GOOG": weekly, "MSFT": weekly, "AAPL": weekly},
        )

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()
        # pos_a and pos_b share entry_date 2026-01-01, so "pos_a" < "pos_b" breaks the tie;
        # pos_z's later entry_date sorts it last regardless of id.
        assert [p["id"] for p in body["positions"]] == ["pos_a", "pos_b", "pos_z"]

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
        # Enough rows/columns for latest_close (which only needs "close") to succeed, but
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

    def test_malformed_bar_earlier_in_history_does_not_perturb_stop_or_flags(
        self, db_session: Session
    ) -> None:
        """A malformed bar (NaN OHLC) anywhere in a position's daily history -- not just the
        very latest bar `app.portfolio.pricing.latest_close` already excludes a position
        outright for -- is dropped via `drop_malformed_daily_bars` before
        `protective_stop`/`evaluate_exit_flags` ever see it, so the response is identical to
        what it would be had that malformed bar simply never been fetched. Inserting it inside
        the `_SWING_LOW_WINDOW_BARS`/EMA(13) lookback window (rather than at the very front,
        the oldest position) of the same quiet history
        `test_oversized_position_breaches_two_percent_rule_only` uses confirms the filtered
        frame reduces to exactly that reference scenario.

        The insertion position matters for this test to actually discriminate: a malformed
        row at the very front is a structural no-op for both `Series.ewm(adjust=False).mean()`
        (pandas treats a leading NaN as "not yet started" and skips it, producing the same
        EMA(13) values as if it had simply been dropped) and for the `.min()`/`.mean()`
        aggregations `protective_stop` uses internally (both `skipna=True` by default, so a
        NaN anywhere doesn't shift them) -- so a front-inserted malformed bar would pass this
        test even with `drop_malformed_daily_bars` never called at all. Inserted after the 2nd
        row instead (still well inside the 10-day window), it genuinely perturbs every later
        EMA(13) value computed on the undropped frame (hand-verified: `protective_stop`
        evaluates to 97.9249169435216 on the undropped frame vs. the reference
        97.93061224489796 below, a difference far outside `pytest.approx`'s default
        tolerance), so this test now fails without the fix and passes with it."""
        db_session.add(AccountORM(id=1, cash=6_700.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=30.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        clean_daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        malformed_row = pd.DataFrame(
            {
                "open": [float("nan")],
                "high": [float("nan")],
                "low": [float("nan")],
                "close": [float("nan")],
                "volume": [1_000_000.0],
            }
        )
        daily_with_malformed_bar = pd.concat(
            [clean_daily.iloc[:2], malformed_row, clean_daily.iloc[2:]], ignore_index=True
        )
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily_with_malformed_bar}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()

        expected_risk_pct = 30.0 * _QUIET_DISTANCE / (6_700.0 + 30.0 * 110.0) * 100.0
        [position] = body["positions"]
        assert position["protective_stop"] == pytest.approx(_QUIET_STOP)
        assert position["position_risk_pct"] == pytest.approx(expected_risk_pct)
        assert position["two_percent_rule_breached"] is True
        assert "two_percent_rule_breached" in position["exit_flags"]

    def test_malformed_bar_that_drops_history_below_minimum_excludes_position(
        self, db_session: Session
    ) -> None:
        """A 2-row daily frame -- a malformed "yesterday" plus a real "today" -- passes
        evaluate_exit_flags's raw `len(daily_ohlcv) < 2` check *before* filtering. Without
        `drop_malformed_daily_bars` applied first, `protective_stop`'s own
        `.tail(10).min()`/`.mean()` degrade a fully-NaN window to a NaN stop rather than
        raising (NaN comparisons silently evaluate False, not an error) -- silently producing
        a NaN `protective_stop`/`position_risk_pct` and suppressing every exit flag instead of
        excluding the position. With the malformed bar dropped first, only 1 real row is left
        -- below the minimum -- so the position is excluded from the response instead, the
        same degrade-gracefully outcome `test_position_with_insufficient_daily_history_is_excluded`
        already covers for a genuinely single-row history."""
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=50.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        malformed_then_real = pd.DataFrame(
            {
                "open": [float("nan"), 100.0],
                "high": [float("nan"), 101.0],
                "low": [float("nan"), 99.0],
                "close": [float("nan"), 100.0],
                "volume": [1_000_000.0, 1_000_000.0],
            }
        )
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": malformed_then_real}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        assert response.json()["positions"] == []

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

    def test_malformed_open_high_low_on_latest_bar_does_not_suppress_stop_hit(
        self, db_session: Session
    ) -> None:
        """Same stop-hit setup as `test_stop_hit_flag_surfaces_in_exit_flags`, except today's
        bar has a real `close` (80.0, still below the ~98 stop) but NaN `open`/`high`/`low` --
        the "not yet settled" yfinance shape `app.portfolio.pricing.latest_close` already
        tolerates for `position.current_price` (it only checks `close`). Before this test's
        fix, `drop_malformed_daily_bars` required full OHLC on *every* bar including the
        latest, so this bar was dropped entirely -- `evaluate_exit_flags` then read
        yesterday's close (100.0, above the stop) instead of today's, silently losing the
        stop_hit flag despite `position.current_price` (from `latest_close`) correctly
        reflecting today's real 80.0 close. Reverting the `require_full_ohlc_on_latest_bar`
        fix (or the router's `False` argument) reproduces exactly that: `exit_flags == []`
        instead of `['stop_hit']`."""
        closes = [100.0] * 10 + [80.0]
        lows = [99.0] * 10 + [78.0]
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(closes, lows)
        daily.loc[daily.index[-1], ["open", "high", "low"]] = float("nan")
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert "stop_hit" in position["exit_flags"]


class TestTrailingStop:
    """backend-trailing-profit-stop: `RiskPosition.trailing_stop` (Elder ch. 54 "Don't Let a
    Winning Trade Turn into a Loss") wired alongside the existing `protective_stop` field."""

    def test_field_present_and_matches_the_pure_computation(self, db_session: Session) -> None:
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
        [position] = response.json()["positions"]
        expected = ratchet_trailing_profit_stop(
            Position(
                id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0,
                entry_date=date(2026, 1, 1), current_price=_UPTREND_CLOSES[-1],
            ),
            daily,
            position["protective_stop"],
        )
        assert position["trailing_stop"] == pytest.approx(expected)

    def test_never_decreases_across_successive_requests_even_as_price_pulls_back(
        self, db_session: Session
    ) -> None:
        """The book's companion rule, "Move Your Stop Only in the Direction of Your Trade":
        simulates two successive polls of the same endpoint -- the first while a rally is
        still climbing (profit well past the trigger), the second after a pullback that would,
        computed fresh from that day alone, suggest a lower trailing_stop. The second
        response's trailing_stop must not be lower than the first's."""
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)

        rally_closes = [100.0 + i for i in range(31)]  # ends at +30% profit
        rally_lows = [c - 1.0 for c in rally_closes]
        rally_daily = _daily_frame(rally_closes, rally_lows)
        rally_response = _get_risk(
            db_session, _StubProvider(daily={"AAPL": rally_daily}, weekly={"AAPL": weekly})
        )
        assert rally_response.status_code == 200
        [rally_position] = rally_response.json()["positions"]
        rally_trailing_stop = rally_position["trailing_stop"]
        assert rally_trailing_stop > 100.0  # comfortably past breakeven

        pullback_closes = rally_closes + [115.0]  # pulls back from +130 to +115 (+15% profit)
        pullback_lows = [c - 1.0 for c in pullback_closes]
        pullback_daily = _daily_frame(pullback_closes, pullback_lows)
        pullback_response = _get_risk(
            db_session, _StubProvider(daily={"AAPL": pullback_daily}, weekly={"AAPL": weekly})
        )
        assert pullback_response.status_code == 200
        [pullback_position] = pullback_response.json()["positions"]

        assert pullback_position["trailing_stop"] >= rally_trailing_stop

    def test_never_decreases_across_a_same_ticker_merge_that_raises_avg_cost_basis(
        self, db_session: Session
    ) -> None:
        """PR #240 review repro (backend-trailing-profit-stop): `POST /api/portfolio/positions`
        's same-ticker merge can raise `avg_cost_basis` (a quantity-weighted average) with NO
        further price movement at all -- before the persisted-high-water-mark fix, this
        invalidated the ratchet's own stateless recompute (the merge raises `entry_price`/
        `threshold_profit`, un-qualifying closes that used to cross the trigger) and made
        `trailing_stop` DECREASE across successive `GET /api/portfolio/risk` calls, directly
        violating this task's hard-ratchet contract. Reproduces the reviewer's exact numbers:
        entered at $100, rallies to $115 (ratchets to ~$101.667), then merges in more shares at
        $200/share (avg_cost_basis -> $150) with the price unchanged."""
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)

        # Ends at 115.0 -- +15% profit, comfortably past the 10% breakeven trigger. One deep
        # downside wick (a low far below its day's close) is mixed in deliberately, dragging
        # `protective_stop` (the SafeZone stop, i.e. `safezone_stop` in
        # `ratchet_trailing_profit_stop`'s own signature) well BELOW the $101.667 trailing_stop
        # the rally itself ratchets to -- so the merge step below genuinely exercises the
        # persisted-high-water-mark floor overriding a lower fresh recompute, rather than the
        # floor being trivially satisfied by an incidentally-higher live SafeZone stop.
        rally_closes = [100.0 + 15.0 * i / 14.0 for i in range(15)]
        rally_lows = [c - 1.0 for c in rally_closes]
        rally_lows[10] = 85.0
        rally_daily = _daily_frame(rally_closes, rally_lows)
        provider = _StubProvider(daily={"AAPL": rally_daily}, weekly={"AAPL": weekly})

        rally_response = _get_risk(db_session, provider)
        assert rally_response.status_code == 200
        [rally_position] = rally_response.json()["positions"]
        rally_trailing_stop = rally_position["trailing_stop"]
        # 100 + 1/3 * (15 - 10) == 101.666...
        assert rally_trailing_stop == pytest.approx(101.666667, abs=1e-4)

        # Merge in 1 more share at $200/share with the price frame unchanged -- weighted average
        # (1*100 + 1*200) / 2 == 150.0, exactly the reviewer's repro.
        merge_client = _make_client(db_session, provider)
        try:
            merge_response = merge_client.post(
                "/api/portfolio/positions",
                json={
                    "ticker": "AAPL",
                    "quantity": 1,
                    "avg_cost_basis": 200.0,
                    "entry_date": "2026-01-01",
                },
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)
        assert merge_response.status_code == 201
        assert merge_response.json()["avg_cost_basis"] == pytest.approx(150.0)

        post_merge_response = _get_risk(db_session, provider)
        assert post_merge_response.status_code == 200
        [post_merge_position] = post_merge_response.json()["positions"]

        # The bug (pre-fix): recomputed fresh from avg_cost_basis=150 against an unchanged
        # $115 price, this position never crosses the (now higher) 10% trigger at all, so a
        # purely stateless recompute alone collapses back to protective_stop (~$80.87, well
        # below the $101.667 already reported during the rally -- see this deep-wick fixture's
        # comment above). The fix (a persisted high-water-mark floor) must prevent that
        # regression: the reported value must not drop.
        assert post_merge_position["trailing_stop"] >= rally_trailing_stop
        assert post_merge_position["trailing_stop"] == pytest.approx(rally_trailing_stop)

    def test_get_risk_never_writes_to_the_database(self, db_session: Session) -> None:
        """Round-2 fix (PR #240): `GET /api/portfolio/risk` must be a pure read again -- the
        `trailing_stop_high_water_mark` floor is now captured only at its one write path
        (`POST /api/portfolio/positions`'s same-ticker-merge branch), never advanced/persisted
        by this GET route, restoring HTTP GET's safe/idempotent contract (including on
        ordinary TanStack Query window-refocus refetches). Proven two ways: `Session.commit`
        is never called during the request, and the ORM row's own
        `trailing_stop_high_water_mark` is still `None` afterwards even though this fixture's
        `trailing_stop` genuinely crosses the breakeven trigger in the response itself."""
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        rally_closes = [100.0 + i for i in range(31)]  # ends at +30% profit, well past the trigger
        rally_lows = [c - 1.0 for c in rally_closes]
        daily = _daily_frame(rally_closes, rally_lows)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        with patch.object(db_session, "commit", wraps=db_session.commit) as mock_commit:
            response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["trailing_stop"] > 100.0  # the ratchet DID fire (comfortably past breakeven)
        mock_commit.assert_not_called()

        refreshed = db_session.get(PositionORM, "pos_1")
        assert refreshed.trailing_stop_high_water_mark is None

    def test_below_trigger_matches_protective_stop(self, db_session: Session) -> None:
        """A position whose profit has never crossed the breakeven trigger reports the same
        trailing_stop as protective_stop -- there's no "winning trade" yet for ch. 54's
        mechanic to protect."""
        # avg_cost_basis=108 vs. _QUIET_CLOSES' final close of 110 -> ~1.85% unrealized profit,
        # comfortably under the 10% breakeven trigger for every close in this fixture's history.
        db_session.add(AccountORM(id=1, cash=6_700.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=30.0, avg_cost_basis=108.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily = _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["trailing_stop"] == pytest.approx(position["protective_stop"])


class TestProfitTarget:
    """backend-profit-target-open-position: `RiskPosition.profit_target` must still be
    computed for an already-open position even once its own live technical signal has drifted
    away from BUY -- UNLIKE `AnalysisResponse.profit_target` on GET /api/stocks/{ticker}
    /analysis, which is only ever computed for a fresh BUY signal (see that task's `decisions`
    entry, which revisits `backend-profit-target`'s original BUY-only decision for this exact
    open-position case)."""

    # A smooth, pullback-free uptrend never fires Screen 3's Trigger (no prior-high/low cross
    # following an oversold Screen 2 dip) -- confirmed HOLD below via a direct `analyse()` call
    # on this exact fixture, not just assumed.
    _DAILY_CLOSES = [100.0 + i * 0.2 for i in range(150)]
    _DAILY_LOWS = [c - 0.5 for c in _DAILY_CLOSES]
    # >=100 weeks clears the Autoenvelope's own warm-up window (`autoenvelope`'s default
    # `deviation_lookback=100`), with a periodic bump giving a real, non-degenerate channel --
    # same construction as tests/unit/test_portfolio_profit_target.py's own narrow-channel
    # fixture (`_WEEKLY_OHLCV_NARROW_CHANNEL`).
    _WEEKLY_CLOSES = [100.0 + i * 0.3 + (2.0 if i % 7 == 0 else 0.0) for i in range(120)]

    def test_signal_drifted_to_hold_still_shows_a_profit_target(self, db_session: Session) -> None:
        daily = _daily_frame(self._DAILY_CLOSES, self._DAILY_LOWS)
        weekly = _weekly_frame(self._WEEKLY_CLOSES)

        # Sanity-check the premise: this exact daily/weekly pair's own live signal (the same
        # engine GET /api/stocks/{ticker}/analysis uses for AnalysisResponse.signal) is NOT
        # BUY -- so AnalysisResponse.profit_target would be null for this ticker right now,
        # while RiskPosition.profit_target must still be non-null for an already-open position
        # on this exact same data.
        assert analyse("AAPL", daily, weekly).signal != "BUY"

        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["profit_target"] is not None
        assert position["profit_target"]["source"] == "channel"
        assert position["profit_target"]["price"] > daily["close"].iloc[-1]
        assert position["profit_target"]["reward_risk_ratio"] is not None
        assert isinstance(position["profit_target"]["meets_minimum_reward_risk"], bool)

    def test_profit_target_never_disagrees_with_this_position_s_own_protective_stop(
        self, db_session: Session
    ) -> None:
        """PR #224 review finding: `suggest_profit_target` used to recompute its OWN stop from
        the full `daily_by_id[id]` frame (today's bar included), which can genuinely differ from
        `RiskPosition.protective_stop` (deliberately computed from `daily_ohlcv.iloc[:-1]`, per
        this endpoint's own docstring, to avoid a lookahead desync). Today's bar here has an
        anomalously low `low` -- low enough to pull the FULL-frame swing low (and so its stop)
        far below the `iloc[:-1]` one -- while `close` stays on the same smooth uptrend so the
        channel-based target candidate/`current_price` are unaffected. Confirms the two really
        do diverge for this fixture (so the assertion below isn't vacuous), then confirms
        `profit_target.distance_to_stop`'s IMPLIED stop matches `protective_stop` exactly, not
        the stale full-frame one."""
        daily_lows = list(self._DAILY_LOWS)
        daily_lows[-1] = 10.0  # today's anomalous low -- excluded from protective_stop's window
        daily = _daily_frame(self._DAILY_CLOSES, daily_lows)
        weekly = _weekly_frame(self._WEEKLY_CLOSES)

        correct_stop = stop_from_price_action(daily.iloc[:-1])
        stale_full_frame_stop = stop_from_price_action(daily)
        assert correct_stop != pytest.approx(stale_full_frame_stop, rel=1e-3), (
            "fixture must actually produce two different stops, or this test proves nothing"
        )

        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["protective_stop"] == pytest.approx(correct_stop)
        assert position["profit_target"] is not None
        current_price = daily["close"].iloc[-1]
        implied_stop = current_price - position["profit_target"]["distance_to_stop"]
        assert implied_stop == pytest.approx(correct_stop)
        assert implied_stop != pytest.approx(stale_full_frame_stop, rel=1e-3)

    def test_no_qualifying_target_candidate_degrades_profit_target_to_null_not_position_exclusion(
        self, db_session: Session
    ) -> None:
        """Mirrors `suggest_profit_target`'s own
        `test_returns_none_when_no_channel_and_no_qualifying_zone` (tests/unit/test_portfolio_
        profit_target.py), wired end to end: too little weekly history for a channel and no
        qualifying support/resistance zone leaves `profit_target` null, but the position
        itself must still appear in `positions` with its other (unrelated) fields intact --
        `profit_target` degrades independently of the rest of the position, per this
        endpoint's own docstring."""
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
        [position] = response.json()["positions"]
        assert position["ticker"] == "AAPL"
        assert position["profit_target"] is None

    def test_profit_target_column_validation_failure_degrades_to_null_not_position_exclusion(
        self, db_session: Session
    ) -> None:
        """`app.signals.support_resistance.detect_support_resistance_zones` requires `volume`
        (unlike `protective_stop`/`evaluate_exit_flags`, which only need `low`/`close`) -- a
        daily frame missing it raises `ValueError` from `profit_target`'s own computation while
        every other field on this position still computes fine. Must degrade `profit_target`
        to `None` for just this position, not exclude the whole position from `positions` (the
        `AttributeError`-vs-`ValueError` distinction doesn't matter here -- this is
        specifically the *documented* `ValueError` column-validation path, not the unrelated
        `RangeIndex` artifact `_daily_frame`'s own `pd.DatetimeIndex` already guards other
        tests in this file against)."""
        db_session.add(AccountORM(id=1, cash=1_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=90.0, entry_date=date(2026, 1, 1))
        )
        db_session.commit()

        daily_no_volume = pd.DataFrame(
            {
                "open": _QUIET_CLOSES,
                "high": [c + 1.0 for c in _QUIET_CLOSES],
                "low": _QUIET_LOWS,
                "close": _QUIET_CLOSES,
            },
            index=pd.date_range("2026-01-01", periods=len(_QUIET_CLOSES), freq="D", name="date"),
        )
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily_no_volume}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        [position] = response.json()["positions"]
        assert position["ticker"] == "AAPL"
        assert position["profit_target"] is None
        # protective_stop/exit_flags are computed off only low/close, so this position's other
        # fields are entirely unaffected by profit_target's own missing-column failure.
        assert position["protective_stop"] == pytest.approx(_QUIET_STOP)


class TestRealizedLossesThisMonth:
    """Coverage for the backend-trade-history-table task: the book's actual two-part 6% Rule
    (docs/Analyse.md §7, per docs/ideas.md's ch. 51 cross-check) sums this calendar month's
    realized losses from `closed_trades` alongside open-position risk -- these tests insert
    `ClosedTradeORM` rows directly (rather than going through DELETE) to isolate the
    `GET /api/portfolio/risk` computation itself; the DELETE -> closed_trades -> GET /risk
    wiring end to end is covered separately in test_portfolio_delete_position.py."""

    def test_prior_realized_losses_this_month_push_an_individually_fine_position_over_six_percent(
        self, db_session: Session
    ) -> None:
        # A single, individually-fine open position (its own risk is a small fraction of a
        # percent -- see test_clean_portfolio_has_no_breaches_or_flags above, which uses this
        # exact same UPTREND fixture and asserts total_open_risk_pct < 2.0 on its own) plus two
        # stopped-out losses already realized earlier *this* calendar month, summing to well
        # over 6% of equity on their own -- concretely reproducing this task's own motivating
        # scenario: "a user who took three straight stopped-out losses earlier this month, then
        # opens a new, individually-fine 2%-sized position, sails right past the 6% Rule".
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        this_month = _today().replace(day=1)
        db_session.add_all(
            [
                ClosedTradeORM(
                    id="trade_1", ticker="MSFT", quantity=10.0, entry_price=100.0,
                    entry_date=date(2020, 1, 1), exit_price=67.0, exit_date=this_month,
                    realized_pnl=-3300.0, exit_reason=ExitReason.STOP_HIT.value,
                ),
                ClosedTradeORM(
                    id="trade_2", ticker="GOOG", quantity=10.0, entry_price=200.0,
                    entry_date=date(2020, 1, 1), exit_price=167.0, exit_date=this_month,
                    realized_pnl=-3300.0, exit_reason=ExitReason.STOP_HIT.value,
                ),
            ]
        )
        db_session.commit()

        daily = _daily_frame(_UPTREND_CLOSES, _UPTREND_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()

        equity_total = 100_000.0 + 1.0 * _UPTREND_CLOSES[-1]
        expected_realized_losses_pct = 6_600.0 / equity_total * 100.0
        assert body["realized_losses_this_month_pct"] == pytest.approx(expected_realized_losses_pct)
        assert expected_realized_losses_pct > 6.0  # realized losses alone already breach 6%

        [position] = body["positions"]
        assert position["two_percent_rule_breached"] is False  # individually fine
        assert body["total_open_risk_pct"] > body["realized_losses_this_month_pct"]  # open risk still added on top
        assert body["six_percent_rule_breached"] is True
        assert "six_percent_rule_contributor" in position["exit_flags"]

    def test_fresh_calendar_month_excludes_prior_months_realized_losses(
        self, db_session: Session
    ) -> None:
        # Identical setup to the test above, except both closed trades are dated the *last day
        # of the previous* calendar month -- this month's realized-losses component must be
        # 0.0, and the portfolio must not breach the 6% rule (its only real risk is the same
        # negligible open-position risk as test_clean_portfolio_has_no_breaches_or_flags).
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1))
        )
        last_day_of_prior_month = _today().replace(day=1) - timedelta(days=1)
        db_session.add_all(
            [
                ClosedTradeORM(
                    id="trade_1", ticker="MSFT", quantity=10.0, entry_price=100.0,
                    entry_date=date(2020, 1, 1), exit_price=67.0, exit_date=last_day_of_prior_month,
                    realized_pnl=-3300.0, exit_reason=ExitReason.STOP_HIT.value,
                ),
                ClosedTradeORM(
                    id="trade_2", ticker="GOOG", quantity=10.0, entry_price=200.0,
                    entry_date=date(2020, 1, 1), exit_price=167.0, exit_date=last_day_of_prior_month,
                    realized_pnl=-3300.0, exit_reason=ExitReason.STOP_HIT.value,
                ),
            ]
        )
        db_session.commit()

        daily = _daily_frame(_UPTREND_CLOSES, _UPTREND_LOWS)
        weekly = _weekly_frame(_FLAT_WEEKLY_CLOSES)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_risk(db_session, provider)

        assert response.status_code == 200
        body = response.json()
        assert body["realized_losses_this_month_pct"] == pytest.approx(0.0)
        assert body["total_open_risk_pct"] < 2.0
        assert body["six_percent_rule_breached"] is False

    def test_a_profitable_month_contributes_zero_not_a_negative_offset(
        self, db_session: Session
    ) -> None:
        # A winning closed trade this month must not *reduce* realized_losses_this_month_pct
        # below 0 -- only losing trades (realized_pnl < 0) count, per this task's `decisions`.
        db_session.add(AccountORM(id=1, cash=10_000.0))
        db_session.add(
            ClosedTradeORM(
                id="trade_1", ticker="MSFT", quantity=10.0, entry_price=100.0,
                entry_date=date(2020, 1, 1), exit_price=150.0, exit_date=_today(),
                realized_pnl=500.0, exit_reason=ExitReason.TARGET_HIT.value,
            )
        )
        db_session.commit()

        response = _get_risk(db_session, _StubProvider())

        assert response.status_code == 200
        assert response.json()["realized_losses_this_month_pct"] == pytest.approx(0.0)


def _bars_to_frame(bars: list[IBKRBar]) -> pd.DataFrame:
    """Independent re-implementation of `app.data.day_trader_intraday._bars_to_frame` for
    computing this test module's own expected values -- deliberately not importing that
    private function directly, so a bug in the production conversion itself wouldn't silently
    also corrupt the expected value these tests compare against."""
    return pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex([b.timestamp for b in bars], name="date"),
    )


def _day_trader_ibkr_bars(
    closes: list[float], *, start: datetime, step_minutes: int
) -> list[IBKRBar]:
    return [
        IBKRBar(
            timestamp=start + timedelta(minutes=step_minutes * i),
            open=close, high=close + 1.0, low=close - 1.0, close=close, volume=1_000_000.0,
        )
        for i, close in enumerate(closes)
    ]


_FULLY_INTRADAY_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("60m"),
    intermediate=TimeframeInterval.parse("10m"),
    short_term=TimeframeInterval.parse("2m"),
)

# 12 intermediate bars with a clear, identifiable swing low near the middle -- deliberately
# very different from `_QUIET_CLOSES`/`_QUIET_LOWS` above (this module's own swing-mode
# fixture), so a silent fallback to swing daily data would produce a numerically different
# (and therefore detectable) protective_stop.
_DAY_TRADER_INTERMEDIATE_CLOSES = [110.0, 109.0, 108.0, 80.0, 107.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0, 117.0]


class _StubIBKRProvider:
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
    long_term = _day_trader_ibkr_bars([100 * (1.05**i) for i in range(40)], start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60)
    intermediate = _day_trader_ibkr_bars(_DAY_TRADER_INTERMEDIATE_CLOSES, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10)
    short_term = _day_trader_ibkr_bars([95.5, 99.5], start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2)
    return _StubIBKRProvider(
        get_hourly_bars_by_bar_size={"1h": long_term, "10min": intermediate, "2min": short_term}
    )


def _get_risk_with_ibkr(db_session: Session, provider: _StubProvider, ibkr_provider: object | None):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_provider] = lambda: provider
    app.dependency_overrides[get_ibkr_provider] = lambda: ibkr_provider
    test_client = TestClient(app)
    try:
        return test_client.get("/api/portfolio/risk")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)
        app.dependency_overrides.pop(get_ibkr_provider, None)


class TestDayTraderMode:
    """`GET /api/portfolio/risk` while the global trading mode is `day_trader`
    (`backend-day-trader-timeframe-mode-api-followups`) -- `protective_stop`/`trailing_stop`/
    `exit_flags`/`profit_target` are computed from the active triple's intermediate/long-term
    legs (fetched via IBKR) instead of this ticker's ordinary daily/weekly OHLCV."""

    def test_protective_stop_uses_the_day_trader_intermediate_leg_not_swing_daily_data(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        # Flat swing daily/weekly data -- protective_stop() from this would be far higher than
        # the day-trader intermediate leg's own swing low (80.0, deliberately dipped mid-series).
        provider = _StubProvider(
            daily={"AAPL": _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)}, weekly={"AAPL": _weekly_frame(_FLAT_WEEKLY_CLOSES)}
        )

        response = _get_risk_with_ibkr(db_session, provider, _all_legs_available_ibkr_provider())

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "day_trader"
        [position] = body["positions"]

        intermediate = drop_malformed_daily_bars(
            _bars_to_frame(
                _day_trader_ibkr_bars(
                    _DAY_TRADER_INTERMEDIATE_CLOSES, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10
                )
            ),
            require_full_ohlc_on_latest_bar=False,
        )
        expected_stop = protective_stop(
            Position(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1)),
            intermediate.iloc[:-1],
        )
        swing_stop = protective_stop(
            Position(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1)),
            _daily_frame(_QUIET_CLOSES, _QUIET_LOWS).iloc[:-1],
        )
        assert expected_stop != pytest.approx(swing_stop)
        assert position["protective_stop"] == pytest.approx(expected_stop)

    def test_ibkr_unavailable_excludes_the_position(self, db_session: Session) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(
            daily={"AAPL": _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)}, weekly={"AAPL": _weekly_frame(_FLAT_WEEKLY_CLOSES)}
        )

        response = _get_risk_with_ibkr(db_session, provider, ibkr_provider=None)

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "day_trader"
        assert body["positions"] == []

    def test_swing_mode_default_is_unaffected_by_a_configured_day_trader_triple(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.SWING, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(
            daily={"AAPL": _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)}, weekly={"AAPL": _weekly_frame(_FLAT_WEEKLY_CLOSES)}
        )

        response = _get_risk_with_ibkr(db_session, provider, ibkr_provider=None)

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "swing"
        [position] = body["positions"]
        assert position["protective_stop"] == pytest.approx(_QUIET_STOP)

    def test_position_with_insufficient_intermediate_history_is_excluded(
        self, db_session: Session
    ) -> None:
        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(
            daily={"AAPL": _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)}, weekly={"AAPL": _weekly_frame(_FLAT_WEEKLY_CLOSES)}
        )
        # A single intermediate-leg bar: enough for `resolve_conid`/the fetch itself to
        # succeed, but too few for `protective_stop`'s own `.iloc[:-1]` + 2-row minimum.
        ibkr_provider = _StubIBKRProvider(
            get_hourly_bars_by_bar_size={
                "1h": _day_trader_ibkr_bars([100.0], start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60),
                "10min": _day_trader_ibkr_bars([100.0], start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10),
                "2min": _day_trader_ibkr_bars([100.0], start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2),
            }
        )

        response = _get_risk_with_ibkr(db_session, provider, ibkr_provider)

        assert response.status_code == 200
        assert response.json()["positions"] == []

    def test_position_with_intermediate_frame_missing_low_column_is_excluded(
        self, db_session: Session, mocker
    ) -> None:
        """Mirrors `TestGetRisk.test_position_with_daily_frame_missing_low_column_is_excluded`'s
        swing-mode case for the day-trader branch: `protective_stop`'s `ValueError` (a malformed
        frame, here simulated by patching the concurrent leg-fetch directly rather than
        constructing a real IBKR response missing a column `app.data.day_trader_intraday
        ._bars_to_frame` always populates) must exclude the position, not propagate as a 500."""
        from app.api.day_trader_signal import DayTraderLegsOutcome

        db_session.add(AccountORM(id=1, cash=100_000.0))
        db_session.add(
            PositionORM(id="pos_1", ticker="AAPL", quantity=10, avg_cost_basis=90.0, entry_date=date(2020, 1, 1))
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        db_session.commit()
        provider = _StubProvider(
            daily={"AAPL": _daily_frame(_QUIET_CLOSES, _QUIET_LOWS)}, weekly={"AAPL": _weekly_frame(_FLAT_WEEKLY_CLOSES)}
        )
        malformed_intermediate = pd.DataFrame(
            {"close": [100.0, 101.0]},
            index=pd.date_range("2026-01-05", periods=2, freq="10min", tz="UTC", name="date"),
        )
        mocker.patch(
            "app.api.routers.portfolio.fetch_day_trader_legs_concurrently",
            return_value={
                "AAPL": DayTraderLegsOutcome(
                    long_term_ohlcv=_daily_frame(_QUIET_CLOSES, _QUIET_LOWS),
                    intermediate_ohlcv=malformed_intermediate,
                    short_term_ohlcv=_daily_frame(_QUIET_CLOSES, _QUIET_LOWS),
                    unavailable_reason=None,
                )
            },
        )

        response = _get_risk_with_ibkr(db_session, provider, _all_legs_available_ibkr_provider())

        assert response.status_code == 200
        assert response.json()["positions"] == []
