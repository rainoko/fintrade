"""Integration tests for GET /api/ibkr/portfolio-preview and POST /api/ibkr/portfolio-preload
(docs/tasks/backend-ibkr-portfolio-preload.json).

Combines this module's two established test patterns: `tests/integration/conftest.py`'s
`db_session`-backed `client` fixture (an isolated in-memory SQLite database, per
test_portfolio_positions.py's own precedent) plus `test_ibkr_scanner.py`'s
`get_ibkr_provider` dependency-override stub (never touching `IBKRProvider`'s real HTTP
boundary, per docs/architecture/Testing.md's "no live network calls" rule and this
module's own no-live-gateway testing constraint).
"""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import get_ibkr_provider
from app.data.ibkr_provider import GatewayStatus, IBKRAccountPosition, IBKRUnavailableError
from app.db.models import PositionORM
from app.main import app

_AVAILABLE = GatewayStatus(state="available")


class _StubIBKRProvider:
    """Stands in for `IBKRProvider`, exposing only `get_account_positions` -- the one
    method these two routes call. `positions_result` may be either a list of
    `IBKRAccountPosition` or an `Exception` instance to raise, covering both the happy
    path and the `IBKRUnavailableError` case the handlers catch."""

    def __init__(
        self,
        *,
        status: GatewayStatus = _AVAILABLE,
        positions_result: list[IBKRAccountPosition] | Exception | None = None,
    ) -> None:
        self._status = status
        self._positions_result = positions_result

    def get_gateway_status(self) -> GatewayStatus:
        return self._status

    def get_account_positions(self) -> list[IBKRAccountPosition]:
        if isinstance(self._positions_result, Exception):
            raise self._positions_result
        assert self._positions_result is not None
        return self._positions_result


@pytest.fixture(autouse=True)
def _clear_ibkr_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_ibkr_provider, None)


def _override(provider: _StubIBKRProvider | None) -> None:
    def _dep() -> Iterator[_StubIBKRProvider | None]:
        yield provider

    app.dependency_overrides[get_ibkr_provider] = _dep


def _add_local_position(db_session: Session, ticker: str, *, quantity: float = 5.0) -> None:
    db_session.add(
        PositionORM(
            id=f"pos_{ticker.lower()}",
            ticker=ticker,
            quantity=quantity,
            avg_cost_basis=100.0,
            entry_date=date(2026, 1, 1),
        )
    )
    db_session.commit()


class TestGetPortfolioPreview:
    def test_disabled(self, client: TestClient) -> None:
        _override(None)

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "disabled"
        assert body["detail"] is not None
        assert body["positions"] is None

    def test_gateway_unreachable(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="gateway_unreachable", detail="down"),
                positions_result=IBKRUnavailableError("IBKR gateway not available (gateway_unreachable): down"),
            )
        )

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.status_code == 200
        assert response.json() == {"state": "gateway_unreachable", "detail": "down", "positions": None}

    def test_not_authenticated(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="not_authenticated", detail="please log in"),
                positions_result=IBKRUnavailableError(
                    "IBKR gateway not available (not_authenticated): please log in"
                ),
            )
        )

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.status_code == 200
        assert response.json() == {"state": "not_authenticated", "detail": "please log in", "positions": None}

    def test_transient_call_failure_with_available_gateway_returns_503(self, client: TestClient) -> None:
        """Mirrors the identical regression test on the scanner routes -- a fresh
        `get_gateway_status()` check still reporting `available` while the
        account-positions fetch itself just failed must surface as `503`, not
        `state: "available"` with `positions` left null."""
        _override(
            _StubIBKRProvider(
                status=_AVAILABLE,
                positions_result=IBKRUnavailableError(
                    "IBKR gateway returned HTTP 500 from /portfolio/DU1/positions/0"
                ),
            )
        )

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.status_code == 503
        assert "500" in response.json()["detail"]

    def test_no_conflicts(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ]
            )
        )

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["positions"] == [
            {
                "conid": 1,
                "ticker": "AAPL",
                "quantity": 10.0,
                "avg_cost": 150.0,
                "conflicts_with_existing_position": False,
            }
        ]

    def test_flags_conflict_with_existing_local_position(
        self, client: TestClient, db_session: Session
    ) -> None:
        _add_local_position(db_session, "AAPL")
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0),
                    IBKRAccountPosition(conid=2, ticker="MSFT", quantity=5.0, avg_cost=200.0),
                ]
            )
        )

        response = client.get("/api/ibkr/portfolio-preview")

        body = response.json()
        by_ticker = {p["ticker"]: p for p in body["positions"]}
        assert by_ticker["AAPL"]["conflicts_with_existing_position"] is True
        assert by_ticker["MSFT"]["conflicts_with_existing_position"] is False

    def test_position_with_no_avg_cost_is_excluded(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=None)
                ]
            )
        )

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.json()["positions"] == []

    def test_no_positions_returns_empty_list_not_null(self, client: TestClient) -> None:
        _override(_StubIBKRProvider(positions_result=[]))

        response = client.get("/api/ibkr/portfolio-preview")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["positions"] == []

    def test_makes_no_db_writes(self, client: TestClient, db_session: Session) -> None:
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ]
            )
        )

        client.get("/api/ibkr/portfolio-preview")

        assert db_session.query(PositionORM).count() == 0


class TestPreloadIbkrPortfolio:
    def test_disabled(self, client: TestClient) -> None:
        _override(None)

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "disabled"
        assert body["detail"] is not None
        assert body["imported"] is None
        assert body["skipped_conflicting_tickers"] is None

    def test_gateway_unreachable(self, client: TestClient) -> None:
        _override(
            _StubIBKRProvider(
                status=GatewayStatus(state="gateway_unreachable", detail="down"),
                positions_result=IBKRUnavailableError("IBKR gateway not available (gateway_unreachable): down"),
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 200
        assert response.json() == {
            "state": "gateway_unreachable",
            "detail": "down",
            "imported": None,
            "skipped_conflicting_tickers": None,
        }

    def test_transient_call_failure_with_available_gateway_returns_503(
        self, client: TestClient, db_session: Session
    ) -> None:
        _override(
            _StubIBKRProvider(
                status=_AVAILABLE,
                positions_result=IBKRUnavailableError(
                    "IBKR gateway returned HTTP 500 from /portfolio/DU1/positions/0"
                ),
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 503
        assert db_session.query(PositionORM).count() == 0

    def test_imports_non_conflicting_position(self, client: TestClient, db_session: Session) -> None:
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["skipped_conflicting_tickers"] == []
        assert len(body["imported"]) == 1
        imported = body["imported"][0]
        assert imported["ticker"] == "AAPL"
        assert imported["quantity"] == 10.0
        assert imported["avg_cost_basis"] == 150.0
        assert imported["entry_date"] is not None

        row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        assert row.quantity == 10.0
        assert row.avg_cost_basis == 150.0
        assert row.strategy is None
        assert row.entry_notes is not None
        assert "IBKR" in row.entry_notes

    def test_skips_ticker_still_present_locally_never_merges(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The genuinely discriminating test for requirement 3: a still-conflicting
        ticker's existing local position must be left byte-for-byte untouched, never
        merged/updated via POST /api/portfolio/positions's quantity-weighted-average
        merge path. Mutation-tested (see this task's own test-writing process): temporarily
        making the import path merge instead of skip made this assertion fail, confirming
        it actually discriminates."""
        _add_local_position(db_session, "AAPL", quantity=5.0)
        original_row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        original_quantity = original_row.quantity
        original_avg_cost_basis = original_row.avg_cost_basis
        original_entry_date = original_row.entry_date

        _override(
            _StubIBKRProvider(
                positions_result=[
                    # Same ticker, deliberately different quantity/avg_cost -- if this were
                    # merged (quantity summed, avg_cost_basis weighted-averaged) both fields
                    # below would differ from their original values.
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=999.0, avg_cost=1.0)
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 200
        body = response.json()
        assert body["imported"] == []
        assert body["skipped_conflicting_tickers"] == ["AAPL"]

        # Exactly one AAPL row still exists locally, completely unchanged.
        rows = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").all()
        assert len(rows) == 1
        assert rows[0].quantity == original_quantity
        assert rows[0].avg_cost_basis == original_avg_cost_basis
        assert rows[0].entry_date == original_entry_date

    def test_ticker_deleted_before_preload_is_no_longer_a_conflict(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Requirement 5's exact ordering: a ticker the caller already deleted (simulating
        a prior DELETE /api/portfolio/positions/{id} call) must be treated as available at
        preload time, not as a conflict."""
        _add_local_position(db_session, "AAPL", quantity=5.0)
        db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").delete()
        db_session.commit()

        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        body = response.json()
        assert body["skipped_conflicting_tickers"] == []
        assert [p["ticker"] for p in body["imported"]] == ["AAPL"]
        row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        assert row.quantity == 10.0
        assert row.avg_cost_basis == 150.0

    def test_duplicate_ticker_within_same_fetch_only_imports_first(
        self, client: TestClient, db_session: Session
    ) -> None:
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0),
                    IBKRAccountPosition(conid=2, ticker="AAPL", quantity=20.0, avg_cost=200.0),
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        body = response.json()
        assert len(body["imported"]) == 1
        assert body["skipped_conflicting_tickers"] == ["AAPL"]
        assert db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").count() == 1

    def test_position_with_no_avg_cost_is_neither_imported_nor_reported_as_skipped(
        self, client: TestClient, db_session: Session
    ) -> None:
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=None)
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        body = response.json()
        assert body["imported"] == []
        assert body["skipped_conflicting_tickers"] == []
        assert db_session.query(PositionORM).count() == 0

    def test_no_positions_returns_empty_lists(self, client: TestClient) -> None:
        _override(_StubIBKRProvider(positions_result=[]))

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 200
        body = response.json()
        assert body["imported"] == []
        assert body["skipped_conflicting_tickers"] == []

    def test_concurrent_write_conflict_on_commit_returns_503_and_rolls_back_whole_batch(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend-ibkr-portfolio-preload-followups checklist item 2: a same-ticker row
        inserted concurrently between `_existing_position_tickers` and this route's own
        `db.commit()` (e.g. an overlapping preload call, or an unrelated
        POST /api/portfolio/positions for the same ticker) raises IntegrityError on commit.
        Because the whole batch shares one commit, this must roll back and report every
        position in the same call as not imported (a clean 503), not a raw 500 -- and,
        unlike record_ibkr_breadth_snapshot's single-row fallback, there is no partial
        winner row to recover here.
        """

        def _commit_raises_integrity_error() -> None:
            db_session.rollback()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(db_session, "commit", _commit_raises_integrity_error)
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0),
                    IBKRAccountPosition(conid=2, ticker="MSFT", quantity=5.0, avg_cost=200.0),
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail == "Transient write conflict importing IBKR portfolio positions; retry."
        assert "IntegrityError" not in detail
        # Neither position landed -- the whole batch's commit was rolled back, not just
        # the colliding ticker.
        assert db_session.query(PositionORM).count() == 0

    def test_operational_error_on_commit_also_returns_503(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same handling extends to OperationalError ("database is locked" under SQLite's
        default file-level locking, app/db/session.py), the other exception in the pair
        `record_ibkr_breadth_snapshot` already catches for the identical reason."""

        def _commit_raises_operational_error() -> None:
            db_session.rollback()
            raise OperationalError("INSERT", {}, Exception("database is locked"))

        monkeypatch.setattr(db_session, "commit", _commit_raises_operational_error)
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ]
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 503
        assert db_session.query(PositionORM).count() == 0
