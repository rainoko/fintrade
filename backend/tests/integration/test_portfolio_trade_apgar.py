"""Integration tests for POST /api/portfolio/trade-apgar (app/api/routers/portfolio.py),
added by the backend-trade-apgar task -- Elder ch. 58's "Trade Apgar" pre-trade go/no-go
score.

Uses a stub `DataProvider` (via a `get_data_provider` dependency override), matching the
pattern in tests/integration/test_portfolio_get.py/test_portfolio_closed_trades.py. No
database session is needed -- this endpoint reads/writes nothing.

Three hand-picked daily/weekly OHLCV shapes give real, unmocked weekly-Impulse/daily-Impulse/
price-vs-value results through the real `app.signals.engine.analyse()`/
`app.signals.impulse.evaluate_impulse` pipeline (confirmed empirically -- see this task's
`decisions` entry for why "accelerating rise" is needed for GREEN, not just any rising
series): a compounding-growth series scores GREEN + above_value, a perfectly flat series
scores RED + in_value_zone (exactly at the EMA13==EMA26==close boundary), and a compounding-
decline series scores BLUE + below_value.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_data_provider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.main import app


def _flat(n: int, freq: str) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq=freq)
    closes = pd.Series([100.0] * n, index=idx)
    return pd.DataFrame(
        {"open": closes - 0.5, "high": closes + 1.0, "low": closes - 1.0, "close": closes, "volume": [1_000.0] * n},
        index=idx,
    )


def _accelerating_decline(n: int, freq: str) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq=freq)
    closes = pd.Series([200.0 * (0.97**i) for i in range(n)], index=idx)
    return pd.DataFrame(
        {"open": closes - 0.5, "high": closes + 1.0, "low": closes - 1.0, "close": closes, "volume": [1_000.0] * n},
        index=idx,
    )


_GREEN_ABOVE_VALUE_DAILY = pd.DataFrame(
    {
        "open": [100.0 * (1.03**i) - 0.5 for i in range(40)],
        "high": [100.0 * (1.03**i) + 1.0 for i in range(40)],
        "low": [100.0 * (1.03**i) - 1.0 for i in range(40)],
        "close": [100.0 * (1.03**i) for i in range(40)],
        "volume": [1_000.0] * 40,
    },
    index=pd.bdate_range("2020-01-01", periods=40),
)
_GREEN_ABOVE_VALUE_WEEKLY = pd.DataFrame(
    {
        "open": [100.0 * (1.03**i) - 0.5 for i in range(40)],
        "high": [100.0 * (1.03**i) + 1.0 for i in range(40)],
        "low": [100.0 * (1.03**i) - 1.0 for i in range(40)],
        "close": [100.0 * (1.03**i) for i in range(40)],
        "volume": [1_000.0] * 40,
    },
    index=pd.date_range("2020-01-01", periods=40, freq="W"),
)

_RED_IN_VALUE_ZONE_DAILY = _flat(40, "B")
_RED_IN_VALUE_ZONE_WEEKLY = _flat(30, "W")

_BLUE_BELOW_VALUE_DAILY = _accelerating_decline(40, "B")
_BLUE_BELOW_VALUE_WEEKLY = _accelerating_decline(30, "W")


class _StubProvider:
    def __init__(
        self,
        *,
        daily: pd.DataFrame | None = None,
        weekly: pd.DataFrame | None = None,
        raise_daily: Exception | None = None,
        raise_weekly: Exception | None = None,
    ) -> None:
        self._daily = daily
        self._weekly = weekly
        self._raise_daily = raise_daily
        self._raise_weekly = raise_weekly

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if self._raise_daily is not None:
            raise self._raise_daily
        assert self._daily is not None
        return self._daily

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if self._raise_weekly is not None:
            raise self._raise_weekly
        assert self._weekly is not None
        return self._weekly


def _make_client(provider: _StubProvider) -> TestClient:
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


def _post(client: TestClient, **overrides: object) -> object:
    body = {
        "ticker": "AAPL",
        "false_breakout_status": "none",
        "perfection": "neither",
    }
    body.update(overrides)
    return client.post("/api/portfolio/trade-apgar", json=body)


@pytest.fixture
def teardown_overrides():
    yield
    app.dependency_overrides.pop(get_data_provider, None)


class TestTradeApgarAutoPopulatedQuestions:
    def test_accelerating_rise_scores_green_and_above_value(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_GREEN_ABOVE_VALUE_WEEKLY)
        )
        response = _post(client)
        assert response.status_code == 200
        body = response.json()
        by_key = {q["key"]: q for q in body["questions"]}
        assert by_key["weekly_impulse"] == {
            "key": "weekly_impulse",
            "label": "Weekly Impulse",
            "value": "GREEN",
            "score": 1,
            "source": "auto",
        }
        assert by_key["daily_impulse"]["value"] == "GREEN"
        assert by_key["daily_impulse"]["score"] == 1
        assert by_key["price_vs_value"]["value"] == "above_value"
        assert by_key["price_vs_value"]["score"] == 0

    def test_flat_series_scores_red_and_in_value_zone(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_RED_IN_VALUE_ZONE_DAILY, weekly=_RED_IN_VALUE_ZONE_WEEKLY)
        )
        response = _post(client)
        assert response.status_code == 200
        by_key = {q["key"]: q for q in response.json()["questions"]}
        assert by_key["weekly_impulse"]["value"] == "RED"
        assert by_key["weekly_impulse"]["score"] == 0
        assert by_key["daily_impulse"]["value"] == "RED"
        assert by_key["daily_impulse"]["score"] == 0
        assert by_key["price_vs_value"]["value"] == "in_value_zone"
        assert by_key["price_vs_value"]["score"] == 1

    def test_accelerating_decline_scores_blue_and_below_value(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_BLUE_BELOW_VALUE_DAILY, weekly=_BLUE_BELOW_VALUE_WEEKLY)
        )
        response = _post(client)
        assert response.status_code == 200
        by_key = {q["key"]: q for q in response.json()["questions"]}
        assert by_key["weekly_impulse"]["value"] == "BLUE"
        assert by_key["weekly_impulse"]["score"] == 2
        assert by_key["daily_impulse"]["value"] == "BLUE"
        assert by_key["daily_impulse"]["score"] == 2
        assert by_key["price_vs_value"]["value"] == "below_value"
        assert by_key["price_vs_value"]["score"] == 2


class TestTradeApgarManualQuestionsAndGoNoGo:
    def test_manual_inputs_are_echoed_back_and_scored(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_BLUE_BELOW_VALUE_DAILY, weekly=_BLUE_BELOW_VALUE_WEEKLY)
        )
        response = _post(client, false_breakout_status="on_the_verge", perfection="both")
        by_key = {q["key"]: q for q in response.json()["questions"]}
        assert by_key["false_breakout"] == {
            "key": "false_breakout",
            "label": "False breakout status",
            "value": "on_the_verge",
            "score": 2,
            "source": "manual",
        }
        assert by_key["perfection"]["value"] == "both"
        assert by_key["perfection"]["score"] == 2

    def test_all_favorable_totals_10_and_goes(self, teardown_overrides) -> None:
        # BLUE (2) + BLUE (2) + below_value (2) + on_the_verge (2) + both (2) = 10.
        client = _make_client(
            _StubProvider(daily=_BLUE_BELOW_VALUE_DAILY, weekly=_BLUE_BELOW_VALUE_WEEKLY)
        )
        response = _post(client, false_breakout_status="on_the_verge", perfection="both")
        body = response.json()
        assert body["total_score"] == 10
        assert body["go"] is True

    def test_one_zero_question_blocks_go_even_with_high_total(self, teardown_overrides) -> None:
        # weekly_impulse RED (0) + daily_impulse BLUE (2) + below_value (2) +
        # on_the_verge (2) + both (2) = 8 total, but weekly_impulse is 0 -> must not go.
        client = _make_client(
            _StubProvider(daily=_BLUE_BELOW_VALUE_DAILY, weekly=_RED_IN_VALUE_ZONE_WEEKLY)
        )
        response = _post(client, false_breakout_status="on_the_verge", perfection="both")
        body = response.json()
        assert body["total_score"] == 8
        by_key = {q["key"]: q for q in body["questions"]}
        assert by_key["weekly_impulse"]["score"] == 0
        assert body["go"] is False

    def test_all_unfavorable_totals_0_and_does_not_go(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_RED_IN_VALUE_ZONE_WEEKLY)
        )
        response = _post(client, false_breakout_status="none", perfection="neither")
        body = response.json()
        assert body["go"] is False

    def test_ticker_is_uppercased_in_response(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_GREEN_ABOVE_VALUE_WEEKLY)
        )
        response = _post(client, ticker="aapl")
        assert response.json()["ticker"] == "AAPL"

    def test_questions_are_always_in_book_order(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_GREEN_ABOVE_VALUE_WEEKLY)
        )
        response = _post(client)
        keys = [q["key"] for q in response.json()["questions"]]
        assert keys == ["weekly_impulse", "daily_impulse", "price_vs_value", "false_breakout", "perfection"]


class TestTradeApgarErrorCases:
    def test_unknown_ticker_returns_404(self, teardown_overrides) -> None:
        client = _make_client(_StubProvider(raise_daily=TickerNotFoundError("ZZZZ")))
        response = _post(client, ticker="ZZZZ")
        assert response.status_code == 404

    def test_insufficient_weekly_history_returns_422(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(
                daily=_GREEN_ABOVE_VALUE_DAILY,
                raise_weekly=InsufficientHistoryError("AAPL", required=26, available=5),
            )
        )
        response = _post(client)
        assert response.status_code == 422

    def test_provider_unavailable_returns_503(self, teardown_overrides) -> None:
        client = _make_client(_StubProvider(raise_daily=DataProviderUnavailableError("down")))
        response = _post(client)
        assert response.status_code == 503

    def test_empty_daily_history_returns_422(self, teardown_overrides) -> None:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        client = _make_client(_StubProvider(daily=empty, weekly=_GREEN_ABOVE_VALUE_WEEKLY))
        response = _post(client)
        assert response.status_code == 422

    def test_invalid_false_breakout_status_returns_422(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_GREEN_ABOVE_VALUE_WEEKLY)
        )
        response = _post(client, false_breakout_status="maybe")
        assert response.status_code == 422

    def test_invalid_perfection_returns_422(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_GREEN_ABOVE_VALUE_WEEKLY)
        )
        response = _post(client, perfection="lots")
        assert response.status_code == 422

    def test_blank_ticker_returns_422(self, teardown_overrides) -> None:
        client = _make_client(
            _StubProvider(daily=_GREEN_ABOVE_VALUE_DAILY, weekly=_GREEN_ABOVE_VALUE_WEEKLY)
        )
        response = _post(client, ticker="   ")
        assert response.status_code == 422
