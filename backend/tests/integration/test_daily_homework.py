"""Integration tests for POST/GET /api/daily-homework, GET /api/daily-homework/today, and
GET /api/daily-homework/yesterday-trading-suggestion (app/api/routers/homework.py).

Elder ch. 57's "Am I ready to trade?" 5-question self-test (docs/ideas.md's ch. 57 entry) --
purely subjective, no market data or data-provider dependency at all, so these tests only need
the shared `db_session`/`client` fixtures from tests/integration/conftest.py (no
`get_data_provider` override, unlike most other routers' integration tests).
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ClosedTradeORM


def _today():
    return datetime.now(UTC).date()


def _post(client: TestClient, **overrides):
    body = {
        "physical_state_score": 2,
        "yesterday_trading_score": 2,
        "trade_planning_score": 2,
        "mood_score": 2,
        "schedule_score": 2,
    }
    body.update(overrides)
    return client.post("/api/daily-homework", json=body)


class TestRecordDailyHomework:
    def test_creates_entry_defaulting_to_today(self, client: TestClient) -> None:
        response = _post(client)
        assert response.status_code == 201
        body = response.json()
        assert body["date"] == _today().isoformat()
        assert body["total_score"] == 10
        assert body["band"] == "yellow"
        assert body["recorded_at"] is not None

    def test_total_score_and_band_reflect_the_five_scores(self, client: TestClient) -> None:
        response = _post(
            client,
            physical_state_score=1,
            yesterday_trading_score=1,
            trade_planning_score=1,
            mood_score=1,
            schedule_score=0,
        )
        body = response.json()
        assert body["total_score"] == 4
        assert body["band"] == "red"

    def test_green_band(self, client: TestClient) -> None:
        response = _post(
            client,
            physical_state_score=2,
            yesterday_trading_score=2,
            trade_planning_score=1,
            mood_score=1,
            schedule_score=1,
        )
        body = response.json()
        assert body["total_score"] == 7
        assert body["band"] == "green"

    def test_second_post_same_day_overwrites_rather_than_duplicating(
        self, client: TestClient
    ) -> None:
        first = _post(client, mood_score=0)
        assert first.json()["total_score"] == 8

        second = _post(client, mood_score=2)
        assert second.status_code == 201
        assert second.json()["total_score"] == 10
        assert second.json()["date"] == first.json()["date"]

        listed = client.get("/api/daily-homework").json()["items"]
        assert len(listed) == 1
        assert listed[0]["total_score"] == 10

    def test_explicit_past_date_is_recorded_under_that_date(self, client: TestClient) -> None:
        past_date = (_today() - timedelta(days=5)).isoformat()
        response = _post(client, date=past_date)
        assert response.status_code == 201
        assert response.json()["date"] == past_date

    def test_score_above_2_is_rejected(self, client: TestClient) -> None:
        response = _post(client, mood_score=3)
        assert response.status_code == 422

    def test_score_below_0_is_rejected(self, client: TestClient) -> None:
        response = _post(client, mood_score=-1)
        assert response.status_code == 422


class TestGetDailyHomeworkToday:
    def test_null_entry_when_not_yet_recorded_today(self, client: TestClient) -> None:
        response = client.get("/api/daily-homework/today")
        assert response.status_code == 200
        assert response.json() == {"entry": None}

    def test_returns_todays_entry_once_recorded(self, client: TestClient) -> None:
        _post(client, mood_score=1)
        response = client.get("/api/daily-homework/today")
        assert response.status_code == 200
        entry = response.json()["entry"]
        assert entry is not None
        assert entry["date"] == _today().isoformat()
        assert entry["total_score"] == 9

    def test_past_date_entry_does_not_count_as_today(self, client: TestClient) -> None:
        past_date = (_today() - timedelta(days=1)).isoformat()
        _post(client, date=past_date)
        response = client.get("/api/daily-homework/today")
        assert response.json() == {"entry": None}


class TestListDailyHomework:
    def test_orders_most_recent_date_first(self, client: TestClient) -> None:
        oldest = (_today() - timedelta(days=2)).isoformat()
        middle = (_today() - timedelta(days=1)).isoformat()
        newest = _today().isoformat()
        _post(client, date=oldest)
        _post(client, date=newest)
        _post(client, date=middle)

        items = client.get("/api/daily-homework").json()["items"]
        assert [item["date"] for item in items] == [newest, middle, oldest]

    def test_empty_when_nothing_recorded(self, client: TestClient) -> None:
        assert client.get("/api/daily-homework").json() == {"items": []}


class TestYesterdayTradingSuggestion:
    def _close_trade(self, db_session: Session, *, exit_date, realized_pnl: float) -> None:
        db_session.add(
            ClosedTradeORM(
                id=f"trade_{uuid.uuid4().hex[:8]}",
                ticker="AAPL",
                quantity=10,
                entry_price=100.0,
                entry_date=exit_date - timedelta(days=5),
                exit_price=100.0 + realized_pnl / 10,
                exit_date=exit_date,
                realized_pnl=realized_pnl,
                exit_reason="target_hit",
            )
        )
        db_session.commit()

    def test_no_suggestion_when_no_trades_closed_yesterday(self, client: TestClient) -> None:
        response = client.get("/api/daily-homework/yesterday-trading-suggestion")
        assert response.status_code == 200
        body = response.json()
        assert body["net_realized_pnl"] is None
        assert body["suggested_score"] is None
        assert body["as_of_date"] == (_today() - timedelta(days=1)).isoformat()

    def test_net_gain_suggests_2(self, client: TestClient, db_session: Session) -> None:
        yesterday = _today() - timedelta(days=1)
        self._close_trade(db_session, exit_date=yesterday, realized_pnl=150.0)
        response = client.get("/api/daily-homework/yesterday-trading-suggestion")
        body = response.json()
        assert body["net_realized_pnl"] == 150.0
        assert body["suggested_score"] == 2

    def test_net_loss_suggests_0(self, client: TestClient, db_session: Session) -> None:
        yesterday = _today() - timedelta(days=1)
        self._close_trade(db_session, exit_date=yesterday, realized_pnl=-75.0)
        response = client.get("/api/daily-homework/yesterday-trading-suggestion")
        body = response.json()
        assert body["net_realized_pnl"] == -75.0
        assert body["suggested_score"] == 0

    def test_breakeven_across_multiple_trades_suggests_1(
        self, client: TestClient, db_session: Session
    ) -> None:
        yesterday = _today() - timedelta(days=1)
        self._close_trade(db_session, exit_date=yesterday, realized_pnl=50.0)
        self._close_trade(db_session, exit_date=yesterday, realized_pnl=-50.0)
        response = client.get("/api/daily-homework/yesterday-trading-suggestion")
        body = response.json()
        assert body["net_realized_pnl"] == 0.0
        assert body["suggested_score"] == 1

    def test_trades_closed_today_are_not_counted_as_yesterday(
        self, client: TestClient, db_session: Session
    ) -> None:
        self._close_trade(db_session, exit_date=_today(), realized_pnl=999.0)
        response = client.get("/api/daily-homework/yesterday-trading-suggestion")
        body = response.json()
        assert body["net_realized_pnl"] is None
        assert body["suggested_score"] is None
