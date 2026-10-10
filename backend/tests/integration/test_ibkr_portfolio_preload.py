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
from app.data.ibkr_provider import (
    GatewayStatus,
    IBKRAccountPosition,
    IBKRTrade,
    IBKRUnavailableError,
)
from app.db.models import PositionORM
from app.main import app

_AVAILABLE = GatewayStatus(state="available")


class _StubIBKRProvider:
    """Stands in for `IBKRProvider`, exposing `get_account_positions` and
    `get_account_trades` -- the two methods `POST /api/ibkr/portfolio-preload` calls (the
    preview route only ever calls the former). `positions_result`/`trades_result` may each
    be either the respective result list or an `Exception` instance to raise, covering both
    the happy path and the `IBKRUnavailableError` case the handlers catch.
    `trades_result` defaults to an empty list (no trade history at all) -- the "no
    reconciliation possible" case, which is exactly this feature's original
    pre-`backend-ibkr-import-entry-date-from-trades` behavior, so every test written before
    that task keeps testing the same `entry_date`-always-today() fallback path unmodified.
    """

    def __init__(
        self,
        *,
        status: GatewayStatus = _AVAILABLE,
        positions_result: list[IBKRAccountPosition] | Exception | None = None,
        trades_result: list[IBKRTrade] | Exception | None = None,
    ) -> None:
        self._status = status
        self._positions_result = positions_result
        self._trades_result = trades_result if trades_result is not None else []

    def get_gateway_status(self) -> GatewayStatus:
        return self._status

    def get_account_positions(self) -> list[IBKRAccountPosition]:
        if isinstance(self._positions_result, Exception):
            raise self._positions_result
        assert self._positions_result is not None
        return self._positions_result

    def get_account_trades(self) -> list[IBKRTrade]:
        if isinstance(self._trades_result, Exception):
            raise self._trades_result
        return self._trades_result


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

    def test_entry_date_derived_from_fully_reconciling_trade_history(
        self, client: TestClient, db_session: Session
    ) -> None:
        """backend-ibkr-import-entry-date-from-trades: a single in-window buy whose
        quantity exactly matches the held quantity means this position's entire open
        history fits inside the trade-history window, so the buy date is trustworthy."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ],
                trades_result=[
                    IBKRTrade(conid=1, side="BUY", quantity=10.0, trade_date=date(2026, 10, 5))
                ],
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        body = response.json()
        assert body["imported"][0]["entry_date"] == "2026-10-05"
        row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        assert row.entry_date == date(2026, 10, 5)
        assert "derived" in row.entry_notes
        assert "import date, not the original" not in row.entry_notes

    def test_entry_date_derivation_picks_the_earliest_of_multiple_buys(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Checklist item 2: multiple in-window buy executions resolve to the EARLIEST
        buy date, matching PositionIn.entry_date's own same-ticker-merge precedent."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ],
                trades_result=[
                    IBKRTrade(conid=1, side="BUY", quantity=6.0, trade_date=date(2026, 10, 7)),
                    IBKRTrade(conid=1, side="BUY", quantity=4.0, trade_date=date(2026, 10, 4)),
                ],
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.json()["imported"][0]["entry_date"] == "2026-10-04"

    def test_entry_date_derivation_accounts_for_in_window_sells(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Net-of-sells reconciliation: bought 15, sold 5 in-window, held is 10 -- net
        matches exactly, so the (earliest) buy date is still trustworthy even though not
        every buy share is still held."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ],
                trades_result=[
                    IBKRTrade(conid=1, side="BUY", quantity=15.0, trade_date=date(2026, 10, 3)),
                    IBKRTrade(conid=1, side="SELL", quantity=5.0, trade_date=date(2026, 10, 6)),
                ],
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.json()["imported"][0]["entry_date"] == "2026-10-03"

    def test_entry_date_does_not_false_match_when_a_dropped_sell_would_equal_pre_window_quantity(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Regression for `backend-ibkr-import-entry-date-from-trades-followups`'s
        `pr-decision` round 2 numeric counterexample: a position's true history is
        `held = P (pre-window quantity, never touched in-window) + B (in-window buys) -
        S (in-window sells)`. Here `P=100` (implicit -- not itself a trade row, just
        quantity already held before the trade-history window started), `B=250`
        (one in-window buy), `S=100` (one in-window sell whose `trade_time_r` IBKR didn't
        return, so its `trade_date` is unknown/`None` -- `_parse_account_trades` now keeps
        this row rather than dropping it, per that task's fix).

        `held = 100 + 250 - 100 = 250`. The CORRECT reconciliation is
        `net_true = B - S = 250 - 100 = 150`, which does NOT equal `held` (250) -- so this
        must fall back to today(), not derive a date. Before the fix, dropping the dateless
        SELL row entirely (rather than keeping its quantity with `trade_date=None`) would
        have computed `net_computed = B - 0 = 250 == held` -- an exact FALSE positive match
        that would have wrongly derived the buy's date as `entry_date`."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=250.0, avg_cost=150.0)
                ],
                trades_result=[
                    IBKRTrade(conid=1, side="BUY", quantity=250.0, trade_date=date(2026, 10, 5)),
                    IBKRTrade(conid=1, side="SELL", quantity=100.0, trade_date=None),
                ],
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        body = response.json()
        assert body["imported"][0]["entry_date"] == date.today().isoformat()
        row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        assert "import date, not the original" in row.entry_notes

    def test_entry_date_falls_back_when_trade_history_only_shows_a_partial_top_up(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The exact failure mode the original 'not possible' research conclusion was
        worried about: a buy that's smaller than the held quantity is a top-up on an
        older position, not the whole history -- must still fall back to today(), not the
        (wrong) top-up date."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ],
                trades_result=[
                    IBKRTrade(conid=1, side="BUY", quantity=3.0, trade_date=date(2026, 10, 7))
                ],
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        body = response.json()
        assert body["imported"][0]["entry_date"] == date.today().isoformat()
        row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        assert "import date, not the original" in row.entry_notes

    def test_entry_date_falls_back_when_no_trade_history_for_this_conid(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Trade history exists, but none of it is for this position's conid (e.g. it's
        for a different held ticker) -- falls back exactly like having no trade history
        at all."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ],
                trades_result=[
                    IBKRTrade(conid=2, side="BUY", quantity=10.0, trade_date=date(2026, 10, 5))
                ],
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.json()["imported"][0]["entry_date"] == date.today().isoformat()

    def test_entry_date_falls_back_when_trade_history_endpoint_unavailable(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The whole import must not break if GET /iserver/account/trades 4xx/5xx's --
        degrade to today() for every position, exactly as if no trade history endpoint
        existed at all."""
        _override(
            _StubIBKRProvider(
                positions_result=[
                    IBKRAccountPosition(conid=1, ticker="AAPL", quantity=10.0, avg_cost=150.0)
                ],
                trades_result=IBKRUnavailableError("IBKR gateway returned HTTP 500 from /iserver/account/trades"),
            )
        )

        response = client.post("/api/ibkr/portfolio-preload")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "available"
        assert body["imported"][0]["entry_date"] == date.today().isoformat()
        row = db_session.query(PositionORM).filter(PositionORM.ticker == "AAPL").one()
        assert "import date, not the original" in row.entry_notes

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
