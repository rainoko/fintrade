"""Integration tests for GET /api/portfolio/closed-trades (app/api/routers/portfolio.py),
added by the backend-trade-grading task.

Uses an isolated in-memory SQLite session (via a get_db dependency override) and a stub
DataProvider (via a get_data_provider dependency override), matching the pattern in
tests/integration/test_portfolio_delete_position.py -- `closed_trades` rows are inserted
directly rather than produced via DELETE, so each test controls its own entry/exit
price+date fixtures precisely.
"""

from datetime import date, timedelta

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
from app.time_utils import today, utcnow


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
        # Same for strategy: not passed above, so null rather than an empty string.
        assert item["strategy"] is None
        # Same for the follow-up review fields -- unreviewed by default.
        assert item["follow_up_notes"] is None
        assert item["follow_up_reviewed_at"] is None
        # trade_letter_grade is present as a key even when null-checked elsewhere -- here it's
        # a real letter since the fixture trade is gradeable (see
        # test_grades_match_the_formulas_applied_to_the_fixture_frame for the exact value).
        assert item["trade_letter_grade"] in {"A", "B", "C", "D"}

    def test_entry_notes_is_carried_through_when_present(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", entry_notes="Breakout above resistance.")

        response = client.get("/api/portfolio/closed-trades")
        [item] = response.json()["items"]
        assert item["entry_notes"] == "Breakout above resistance."

    def test_strategy_is_carried_through_when_present(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", strategy="Pullback to value")

        response = client.get("/api/portfolio/closed-trades")
        [item] = response.json()["items"]
        assert item["strategy"] == "Pullback to value"

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
        # expected_trade_grade is well above the 30% "A" threshold for this fixture.
        assert item["trade_letter_grade"] == "A"


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
            assert item["trade_letter_grade"] is None
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
        assert item["trade_letter_grade"] is None
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
            assert items["trade_ok"]["trade_letter_grade"] is not None
            assert items["trade_bad"]["trade_grade_pct"] is None
            assert items["trade_bad"]["trade_letter_grade"] is None
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)


class TestGetClosedTradesLegacyExitReasonDegradesGracefully:
    """backend-closed-trades-legacy-exit-reason-500: a row whose `exit_reason` predates (or
    otherwise falls outside) the current `ExitReasonOut` taxonomy must not 500 the whole
    endpoint -- it's reported as `'unspecified'` instead (this app's own existing sentinel for
    "no real reason known"), and every other row in the same response is unaffected."""

    def test_out_of_taxonomy_exit_reason_reported_as_unspecified(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", exit_reason="manual")

        response = client.get("/api/portfolio/closed-trades")
        assert response.status_code == 200
        [item] = response.json()["items"]
        assert item["exit_reason"] == "unspecified"

    def test_other_rows_in_the_same_response_are_unaffected(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="legacy", exit_reason="manual")
        _add_closed_trade(db_session, id="ok", exit_reason=ExitReason.STOP_HIT.value)

        response = client.get("/api/portfolio/closed-trades")
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}
        assert items["trade_legacy"]["exit_reason"] == "unspecified"
        assert items["trade_ok"]["exit_reason"] == "stop_hit"

    def test_follow_up_review_on_a_legacy_exit_reason_trade_does_not_500(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", exit_reason="manual")

        response = client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "Legacy row, reviewed anyway."},
        )
        assert response.status_code == 200
        assert response.json()["exit_reason"] == "unspecified"

    def test_repeated_requests_with_the_same_out_of_taxonomy_value_warn_only_once(
        self,
        client: TestClient,
        db_session: Session,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """backend-closed-trades-legacy-exit-reason-500-followups checklist item 2:
        `_normalize_exit_reason`'s `logger.warning` must not repeat identically on every
        request for the same long-lived out-of-taxonomy value -- only the first sighting of
        a given distinct value logs a warning in this process's lifetime."""
        monkeypatch.setattr(portfolio_router, "_warned_exit_reason_values", set())
        _add_closed_trade(db_session, id="a", exit_reason="manual")

        with caplog.at_level("WARNING", logger="app.api.routers.portfolio"):
            first = client.get("/api/portfolio/closed-trades")
            second = client.get("/api/portfolio/closed-trades")
            third = client.get("/api/portfolio/closed-trades")

        assert first.status_code == second.status_code == third.status_code == 200
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "manual" in warning_records[0].getMessage()

    def test_a_different_out_of_taxonomy_value_still_warns_after_another_already_warned(
        self,
        client: TestClient,
        db_session: Session,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De-duplication is per distinct value, not a single global on/off switch --
        a second, different out-of-taxonomy value must still get its own first warning even
        after some other value has already been warned about."""
        monkeypatch.setattr(portfolio_router, "_warned_exit_reason_values", set())
        _add_closed_trade(db_session, id="a", exit_reason="manual")

        with caplog.at_level("WARNING", logger="app.api.routers.portfolio"):
            client.get("/api/portfolio/closed-trades")
            caplog.clear()

            _add_closed_trade(db_session, id="b", exit_reason="legacy_close", ticker="AAPL")
            client.get("/api/portfolio/closed-trades")

        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "legacy_close" in warning_records[0].getMessage()
        assert "manual" not in warning_records[0].getMessage()

    def test_a_row_that_fails_for_an_unanticipated_reason_is_skipped_not_500ed(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defense in depth beyond the exit_reason-specific fallback (this task's checklist
        item 3): any row that still fails `_to_closed_trade_out` for some other,
        unanticipated reason is dropped from the response and logged, rather than 500ing
        every other trade in the list."""
        _add_closed_trade(db_session, id="bad", ticker="AAPL")
        _add_closed_trade(db_session, id="ok", ticker="AAPL", exit_date=date(2020, 1, 2))

        real_to_closed_trade_out = portfolio_router._to_closed_trade_out

        def _flaky(row: ClosedTradeORM, grade: object) -> object:
            if row.id == "trade_bad":
                raise RuntimeError("simulated unanticipated failure")
            return real_to_closed_trade_out(row, grade)  # type: ignore[arg-type]

        monkeypatch.setattr(portfolio_router, "_to_closed_trade_out", _flaky)

        response = client.get("/api/portfolio/closed-trades")
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == ["trade_ok"]

    def test_dropped_row_produces_an_aggregate_log_line_with_count_and_ratio(
        self,
        client: TestClient,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """backend-closed-trades-legacy-exit-reason-500-followups checklist item 1: beyond
        the per-row `logger.exception`, a single aggregate `logger.error` line at the end of
        the request carries the dropped-row count/total/ratio, so a systemic failure (most/
        all rows dropped) is distinguishable from the single-bad-row case just from log
        volume/error-rate, without having to tail every per-row traceback."""
        _add_closed_trade(db_session, id="bad", ticker="AAPL")
        _add_closed_trade(db_session, id="ok", ticker="AAPL", exit_date=date(2020, 1, 2))

        real_to_closed_trade_out = portfolio_router._to_closed_trade_out

        def _flaky(row: ClosedTradeORM, grade: object) -> object:
            if row.id == "trade_bad":
                raise RuntimeError("simulated unanticipated failure")
            return real_to_closed_trade_out(row, grade)  # type: ignore[arg-type]

        monkeypatch.setattr(portfolio_router, "_to_closed_trade_out", _flaky)

        with caplog.at_level("ERROR", logger="app.api.routers.portfolio"):
            response = client.get("/api/portfolio/closed-trades")

        assert response.status_code == 200
        aggregate_records = [
            r for r in caplog.records if "GET /api/portfolio/closed-trades dropped" in r.getMessage()
        ]
        assert len(aggregate_records) == 1
        message = aggregate_records[0].getMessage()
        assert aggregate_records[0].levelname == "ERROR"
        assert "dropped 1/2" in message.lower()
        assert "50.0%" in message
        assert "trade_bad" in message

    def test_no_rows_dropped_produces_no_aggregate_log_line(
        self, client: TestClient, db_session: Session, caplog: pytest.LogCaptureFixture
    ) -> None:
        _add_closed_trade(db_session, id="ok")

        with caplog.at_level("ERROR", logger="app.api.routers.portfolio"):
            response = client.get("/api/portfolio/closed-trades")

        assert response.status_code == 200
        assert [r for r in caplog.records if r.levelname == "ERROR"] == []


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


class TestDueForFollowUpFilter:
    """`due_for_follow_up=true` (backend-trade-journal-followup-review): only unreviewed
    trades whose `exit_date` falls 8-10 weeks ago inclusive -- see this task's `decisions`
    entry for why that window."""

    def test_trade_inside_the_window_is_included(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="due", exit_date=today() - timedelta(weeks=9))

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == ["trade_due"]

    def test_trade_too_recent_is_excluded(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="recent", exit_date=today() - timedelta(weeks=3))

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert response.json()["items"] == []

    def test_trade_too_old_is_excluded(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="old", exit_date=today() - timedelta(weeks=20))

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert response.json()["items"] == []

    def test_lower_boundary_8_weeks_is_inclusive(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="lower", exit_date=today() - timedelta(weeks=8))

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == ["trade_lower"]

    def test_upper_boundary_10_weeks_is_inclusive(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="upper", exit_date=today() - timedelta(weeks=10))

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == ["trade_upper"]

    def test_just_outside_each_boundary_is_excluded(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(
            db_session, id="just_under", exit_date=today() - timedelta(weeks=8) + timedelta(days=1)
        )
        _add_closed_trade(
            db_session, id="just_over", exit_date=today() - timedelta(weeks=10) - timedelta(days=1)
        )

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert response.json()["items"] == []

    def test_already_reviewed_trade_is_excluded_even_inside_window(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(
            db_session,
            id="reviewed",
            exit_date=today() - timedelta(weeks=9),
            follow_up_reviewed_at=utcnow(),
            follow_up_notes="Already reviewed.",
        )

        response = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert response.json()["items"] == []

    def test_default_false_returns_everything_regardless_of_window(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="recent", exit_date=today() - timedelta(weeks=1))
        _add_closed_trade(db_session, id="due", exit_date=today() - timedelta(weeks=9))

        response = client.get("/api/portfolio/closed-trades")
        ids = {item["id"] for item in response.json()["items"]}
        assert ids == {"trade_recent", "trade_due"}


class TestRecordFollowUpReview:
    """POST /api/portfolio/closed-trades/{trade_id}/follow-up-review."""

    def test_sets_notes_and_reviewed_at(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="a")

        before = utcnow()
        response = client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "Sold too early -- tide was still bullish."},
        )
        after = utcnow()

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "trade_a"
        assert body["follow_up_notes"] == "Sold too early -- tide was still bullish."
        reviewed_at = body["follow_up_reviewed_at"]
        assert reviewed_at is not None
        # Naive UTC timestamp string, roughly "now" (see app.time_utils.utcnow).
        from datetime import datetime as _dt

        parsed = _dt.fromisoformat(reviewed_at)
        assert before <= parsed <= after

    def test_persists_across_a_subsequent_get(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="a")
        client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "Held on too long past the sell signal."},
        )

        response = client.get("/api/portfolio/closed-trades")
        [item] = response.json()["items"]
        assert item["follow_up_notes"] == "Held on too long past the sell signal."
        assert item["follow_up_reviewed_at"] is not None

    def test_reviewed_trade_drops_out_of_the_due_filter(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a", exit_date=today() - timedelta(weeks=9))

        due_before = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert [item["id"] for item in due_before.json()["items"]] == ["trade_a"]

        client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "Reviewed."},
        )

        due_after = client.get("/api/portfolio/closed-trades?due_for_follow_up=true")
        assert due_after.json()["items"] == []

    def test_calling_again_overwrites_the_previous_review(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a")
        client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "First pass."},
        )

        response = client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "Revised after more thought."},
        )

        assert response.status_code == 200
        assert response.json()["follow_up_notes"] == "Revised after more thought."

    def test_returns_404_for_unknown_trade_id(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/closed-trades/trade_missing/follow-up-review",
            json={"follow_up_notes": "Doesn't matter."},
        )
        assert response.status_code == 404

    def test_blank_notes_is_rejected(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="a")

        response = client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "   "},
        )
        assert response.status_code == 422

    def test_notes_are_stripped_of_surrounding_whitespace(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_closed_trade(db_session, id="a")

        response = client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "  Padded note.  "},
        )
        assert response.status_code == 200
        assert response.json()["follow_up_notes"] == "Padded note."

    def test_returns_recomputed_grades(self, client: TestClient, db_session: Session) -> None:
        _add_closed_trade(db_session, id="a", entry_price=101.0, exit_price=103.0)

        response = client.post(
            "/api/portfolio/closed-trades/trade_a/follow-up-review",
            json={"follow_up_notes": "Good trade in hindsight."},
        )
        assert response.status_code == 200
        assert response.json()["trade_letter_grade"] in {"A", "B", "C", "D"}
