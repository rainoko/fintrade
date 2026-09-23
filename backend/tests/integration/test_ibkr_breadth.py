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
from sqlalchemy.exc import IntegrityError, OperationalError
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
        """`retry_after` is exposed as a structured `Retry-After` header, not just embedded in
        `detail`'s free-text sentence -- see the pr-reviewer follow-up on PR #214's mirror
        test on `test_ibkr_scanner.py::TestRunScanner`.
        """
        _override(_StubIBKRProvider(run_scanner_result=IBKRRateLimitedError(retry_after=0.42)))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 429
        assert "retry" in response.json()["detail"].lower()
        assert response.headers["retry-after"] == "1"

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

    def test_series_key_at_max_length_accepted(self, client: TestClient, db_session: Session) -> None:
        """The pattern's upper bound (`{1,40}`) is a boundary no existing test exercised --
        confirms a 40-char key (the longest still-valid length) is genuinely accepted, not
        just spaces/uppercase rejected."""
        max_length_key = "a" * 40
        _override(_StubIBKRProvider(run_scanner_result=[]))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": max_length_key, "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        assert response.json()["series_key"] == max_length_key

    def test_series_key_over_max_length_rejected(self, client: TestClient) -> None:
        """One character past the documented 1-40 bound must still be rejected -- confirms
        the bound is actually enforced, not just spaces/uppercase against the character
        class."""
        too_long_key = "a" * 41

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": too_long_key, "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 422

    def test_empty_series_key_rejected(self, client: TestClient) -> None:
        """The lower bound (`{1,40}`, i.e. at least 1 character) must reject an empty
        string, the same way the upper bound rejects a too-long one."""
        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 422

    def test_concurrent_first_population_falls_back_to_winners_row(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates the race this task's checklist flags: two concurrent first-of-the-day
        requests for the same (series_key, snapshot_date) both see `row is None` and both
        try to insert it, so the loser's `db.commit()` raises `IntegrityError` on the
        composite primary key. Unlike `CachedDataProvider`'s OHLCV cache (which can safely
        discard the loser's write), this route's response is read from the persisted row
        itself -- so it must fall back to the concurrently-committed winner's row rather
        than raising an uncaught 500 or using its own now-uncommitted `row`.
        """
        original_commit = db_session.commit

        def _commit_raises_once_then_a_winner_appears() -> None:
            monkeypatch.setattr(db_session, "commit", original_commit)
            # The loser's own attempted insert is discarded...
            db_session.rollback()
            # ...and a concurrent request "wins" the race, committing its own row for the
            # exact same (series_key, snapshot_date) first.
            db_session.add(
                IBKRBreadthSnapshotORM(
                    series_key="nh", snapshot_date=today(), count=99, recorded_at=utcnow()
                )
            )
            db_session.commit()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(db_session, "commit", _commit_raises_once_then_a_winner_appears)
        _override(_StubIBKRProvider(run_scanner_result=[ScannerResult(conid=1, symbol=None, company_name=None, rank=None)]))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        # The loser's own scan (a 1-result run) never landed -- the response reflects the
        # concurrently-committed winner's row instead.
        assert body["count"] == 99
        assert body["days_recorded"] == 1
        assert db_session.query(IBKRBreadthSnapshotORM).filter_by(series_key="nh").count() == 1

    def test_operational_error_with_no_same_key_winner_returns_503(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Narrows the `except (IntegrityError, OperationalError)` fallback's assumption
        (see this task's `decisions` entry): unlike `IntegrityError` (this table's only
        constraint is the composite PK, so it can only mean the same-key race the fallback
        is written for), SQLite's whole-file write locking can raise `OperationalError`
        ("database is locked") from *any* concurrent write anywhere in the file -- not only
        a race on this exact (series_key, snapshot_date). In that case `db.get(...)` for the
        supposed winner's row legitimately finds nothing. This must surface as a clean `503`
        (not a bare `assert`'s `AssertionError`, and not silently returning `row=None`
        under `python -O`), and must not persist anything.
        """
        original_commit = db_session.commit

        def _commit_raises_operational_error_with_no_winner() -> None:
            monkeypatch.setattr(db_session, "commit", original_commit)
            # The loser's own attempted insert is discarded, and -- unlike the IntegrityError
            # test above -- no concurrent committer ever wins this exact key; the lock
            # contention was against some unrelated write elsewhere in the file.
            db_session.rollback()
            raise OperationalError("INSERT", {}, Exception("database is locked"))

        monkeypatch.setattr(db_session, "commit", _commit_raises_operational_error_with_no_winner)
        _override(_StubIBKRProvider(run_scanner_result=[ScannerResult(conid=1, symbol=None, company_name=None, rank=None)]))

        response = client.post(
            "/api/ibkr/breadth/snapshot", json={"series_key": "nh", "scan_config": _SCAN_CONFIG}
        )

        assert response.status_code == 503
        assert "nh" in response.json()["detail"]
        assert db_session.query(IBKRBreadthSnapshotORM).filter_by(series_key="nh").count() == 0
