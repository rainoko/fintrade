"""Integration tests for GET/PUT /api/settings/trading-mode (app/api/routers/settings.py).

No market-data provider dependency at all (pure settings persistence), so these tests only
need the shared `db_session`/`client` fixtures from tests/integration/conftest.py, same as
tests/integration/test_daily_homework.py.
"""

from fastapi.testclient import TestClient


class TestGetTradingMode:
    def test_defaults_to_swing_with_null_triple(self, client: TestClient) -> None:
        response = client.get("/api/settings/trading-mode")
        assert response.status_code == 200
        body = response.json()
        assert body == {"mode": "swing", "day_trader_timeframe_triple": None}


class TestUpdateTradingMode:
    def test_switch_to_day_trader_with_valid_triple(self, client: TestClient) -> None:
        response = client.put(
            "/api/settings/trading-mode",
            json={
                "mode": "day_trader",
                "day_trader_timeframe_triple": {
                    "long_term": "25m",
                    "intermediate": "5m",
                    "short_term": "2m",
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "day_trader"
        assert body["day_trader_timeframe_triple"]["long_term"] == "25m"
        assert body["day_trader_timeframe_triple"]["intermediate"] == "5m"
        assert body["day_trader_timeframe_triple"]["short_term"] == "2m"
        assert body["day_trader_timeframe_triple"]["factor_of_five_warnings"] == []

    def test_persists_across_requests(self, client: TestClient) -> None:
        client.put(
            "/api/settings/trading-mode",
            json={
                "mode": "day_trader",
                "day_trader_timeframe_triple": {
                    "long_term": "1w",
                    "intermediate": "1d",
                    "short_term": "120m",
                },
            },
        )
        response = client.get("/api/settings/trading-mode")
        body = response.json()
        assert body["mode"] == "day_trader"
        assert body["day_trader_timeframe_triple"]["long_term"] == "1w"

    def test_day_trader_mode_without_triple_is_rejected(self, client: TestClient) -> None:
        response = client.put("/api/settings/trading-mode", json={"mode": "day_trader"})
        assert response.status_code == 422

    def test_inverted_triple_ordering_is_rejected(self, client: TestClient) -> None:
        response = client.put(
            "/api/settings/trading-mode",
            json={
                "mode": "day_trader",
                "day_trader_timeframe_triple": {
                    "long_term": "2m",
                    "intermediate": "5m",
                    "short_term": "25m",
                },
            },
        )
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_malformed_interval_code_is_rejected(self, client: TestClient) -> None:
        response = client.put(
            "/api/settings/trading-mode",
            json={
                "mode": "day_trader",
                "day_trader_timeframe_triple": {
                    "long_term": "bogus",
                    "intermediate": "5m",
                    "short_term": "2m",
                },
            },
        )
        assert response.status_code == 422

    def test_off_guideline_ratio_warns_but_still_saves(self, client: TestClient) -> None:
        response = client.put(
            "/api/settings/trading-mode",
            json={
                "mode": "day_trader",
                "day_trader_timeframe_triple": {
                    "long_term": "10m",
                    "intermediate": "9m",
                    "short_term": "1m",
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["day_trader_timeframe_triple"]["factor_of_five_warnings"]) == 1

    def test_switch_back_to_swing_preserves_previously_configured_triple(
        self, client: TestClient
    ) -> None:
        client.put(
            "/api/settings/trading-mode",
            json={
                "mode": "day_trader",
                "day_trader_timeframe_triple": {
                    "long_term": "25m",
                    "intermediate": "5m",
                    "short_term": "2m",
                },
            },
        )
        response = client.put("/api/settings/trading-mode", json={"mode": "swing"})
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "swing"
        assert body["day_trader_timeframe_triple"]["long_term"] == "25m"

        # And it's still there for next time on a plain GET.
        get_response = client.get("/api/settings/trading-mode")
        assert get_response.json()["day_trader_timeframe_triple"]["long_term"] == "25m"
