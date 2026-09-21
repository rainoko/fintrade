"""Integration tests for POST /api/ibkr/breadth/snapshot (docs/tasks/
backend-market-breadth-indicators.json).

Uses the shared `db_session`/`client` fixtures from tests/integration/conftest.py (needs the
real database, unlike test_ibkr_status.py/test_ibkr_scanner.py, since this route persists one
`IBKRBreadthSnapshotORM` row per (series_key, day) and reads it back for the rolling-window
sums) plus a direct `get_ibkr_provider` override, same stub pattern as test_ibkr_scanner.py --
never touching `IBKRProvider`'s real HTTP boundary.
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_ibkr_provider
from app.data.ibkr_provider import (
    GatewayStatus,
    IBKRRateLimitedError,
    IBKRUnavailableError,
    ScannerResult,
)
from app.db.models import IBKRBreadthSnapshotORM
from app.main import app
from app.time_utils import today, utcnow

_AVAILABLE = GatewayStatus(state="available")
_SCAN_CONFIG = {"instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR"}


class _StubIBKRProvider:
    def __init__(
        self,
        *,
        status: GatewayStatus = _AVAILABLE,
        run_scanner_result: list[ScannerResult] | Exception | None = None,
    ) -> None:
        self._status = status
        self._run_scanner_result = run_scanner_result

    def get_gateway_status(self) -> GatewayStatus:
        return self._status

    def run_scanner(self, scan_config: dict) -> list[ScannerResult]:
        if isinstance(self._run_scanner_result, Exception):
            raise self._run_scanner_result
        assert self._run_scanner_result is not None
        return self._run_scanner_result


@pytest.fixture(autouse=True)
def _clear_ibkr_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_ibkr_provider, None)


def _override(provider: _StubIBKRProvider | None) -> None:
    def _dep() -> Iterator[_StubIBKRProvider | None]:
        yield provider

    app.dependency_overrides[get_ibkr_provider] = _dep


def _seed_snapshot(db_session: Session, series_key: str, days_ago: int, count: int) -> None:
    db_session.add(
        IBKRBreadthSnapshotORM(
            series_key=series_key,
            snapshot_date=today() - timedelta(days=days_ago),
            count=count,
            recorded_at=utcnow(),
        )
    )
    db_session.commit()


class TestRecordBreadthSnapshot:
    def test_disabled(self, client: TestClient) -> None:
        _override(None)

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "disabled"
        assert body["detail"] is not None
        assert body["series_key"] == "nh"
        assert body["count"] is None
        assert body["snapshot_date"] is None
        assert body["days_recorded"] == 0
        assert body["rolling_5d"] is None
        assert body["rolling_20d"] is None

    def test_gateway_unreachable(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="gateway_unreachable", detail="down"),
                run_scanner_result=IBKRUnavailableError("IBKR gateway not available (gateway_unreachable): down"),
            )
        )

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "gateway_unreachable"
        assert body["detail"] == "down"
        assert body["count"] is None

    def test_not_authenticated(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="not_authenticated", detail="please log in"),
                run_scanner_result=IBKRUnavailableError(
                    "IBKR gateway not available (not_authenticated): please log in"
                ),
            )
        )

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        assert response.json()["state"] == "not_authenticated"

    def test_transient_scanner_call_failure_with_available_gateway_returns_503(
        self, client: TestClient
    ) -> None:
        _override(
            _StubIBKRProvider(
                status=_AVAILABLE,
                run_scanner_result=IBKRUnavailableError("IBKR gateway returned HTTP 500 from /iserver/scanner/run"),
            )
        )

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 503
        assert "500" in response.json()["detail"]

    def test_rate_limited_returns_429(self, client: TestClient) -> None:
        _override(_StubIBKRProvider(run_scanner_result=IBKRRateLimitedError(retry_after=0.42)))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 429
        assert "retry" in response.json()["detail"].lower()

    def test_first_call_of_the_day_runs_the_scan_and_persists_a_row(
        self, client: TestClient, db_session: Session
    ) -> None:
        results = [ScannerResult(conid=1, symbol="AAA", company_name="A Inc", rank=1) for _ in range(7)]
        _override(_StubIBKRProvider(run_scanner_result=results))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["detail"] is None
        assert body["series_key"] == "nh"
        assert body["snapshot_date"] == today().isoformat()
        assert body["count"] == 7
        assert body["days_recorded"] == 1
        assert body["rolling_5d"] is None
        assert body["rolling_20d"] is None

        row = db_session.get(IBKRBreadthSnapshotORM, ("nh", today()))
        assert row is not None
        assert row.count == 7

    def test_second_call_same_day_is_served_from_storage_not_a_second_scan(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_snapshot(db_session, "nh", days_ago=0, count=11)
        # A scan_config that would raise if the route ever actually called run_scanner again.
        _override(_StubIBKRProvider(run_scanner_result=IBKRUnavailableError("must not be called")))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["count"] == 11

    def test_rolling_5d_null_until_five_days_recorded(
        self, client: TestClient, db_session: Session
    ) -> None:
        for days_ago in range(1, 4):
            _seed_snapshot(db_session, "nh", days_ago=days_ago, count=10)
        _override(_StubIBKRProvider(run_scanner_result=[ScannerResult(conid=1, symbol=None, company_name=None, rank=None)]))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        body = response.json()
        assert body["days_recorded"] == 4
        assert body["rolling_5d"] is None
        assert body["rolling_20d"] is None

    def test_rolling_5d_populated_once_five_days_recorded(
        self, client: TestClient, db_session: Session
    ) -> None:
        counts_by_days_ago = {1: 10, 2: 20, 3: 5, 4: 15}
        for days_ago, count in counts_by_days_ago.items():
            _seed_snapshot(db_session, "nh", days_ago=days_ago, count=count)
        today_results = [ScannerResult(conid=i, symbol=None, company_name=None, rank=None) for i in range(3)]
        _override(_StubIBKRProvider(run_scanner_result=today_results))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        body = response.json()
        assert body["count"] == 3
        assert body["days_recorded"] == 5
        assert body["rolling_5d"] == 10 + 20 + 5 + 15 + 3
        assert body["rolling_20d"] is None

    def test_rolling_20d_populated_once_twenty_days_recorded_and_older_history_excluded(
        self, client: TestClient, db_session: Session
    ) -> None:
        for days_ago in range(1, 20):
            _seed_snapshot(db_session, "nh", days_ago=days_ago, count=1)
        # 21 days ago is outside the 20-day window and must not be counted.
        _seed_snapshot(db_session, "nh", days_ago=21, count=1000)
        _override(_StubIBKRProvider(run_scanner_result=[]))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        body = response.json()
        assert body["count"] == 0
        assert body["days_recorded"] == 21
        assert body["rolling_20d"] == 19 * 1 + 0
        assert body["rolling_5d"] == 4 * 1 + 0

    def test_series_keys_are_independent(self, client: TestClient, db_session: Session) -> None:
        _seed_snapshot(db_session, "nh", days_ago=0, count=42)
        _override(_StubIBKRProvider(run_scanner_result=[ScannerResult(conid=1, symbol=None, company_name=None, rank=None)]))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nl", "scan_config": _SCAN_CONFIG}
        )

        body = response.json()
        assert body["series_key"] == "nl"
        assert body["count"] == 1
        assert body["days_recorded"] == 1

    def test_invalid_series_key_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "Not Valid!", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 422
