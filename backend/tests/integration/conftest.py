"""Shared fixtures and helpers for tests/integration/*.

`db_session` and `client` were previously copy-pasted verbatim across
test_portfolio_positions.py, test_portfolio_get.py, and test_portfolio_delete_position.py; they
live here so future DB-touching route tests can reuse them instead of pasting a fourth copy.

test_portfolio_get.py additionally needs a `get_data_provider` override (a stub market-data
provider), so it keeps its own local `client` fixture that builds on the `db_session` fixture
defined here rather than using this module's `client`.

`_frame`, `_StubDailyProvider`, and `_count_position_selects` below were previously copy-pasted
near-verbatim (as `_frame`/`_NetworkStub`/`_count_position_selects` and `_frame`/`_StubProvider`/
`_count_position_selects` respectively) across test_portfolio_pricing_session.py and
test_portfolio_get_db_wiring.py -- both regression tests for the same N+1 fix
(api-portfolio-get-followups), reproducing it at different layers (a standalone sessionmaker
vs. the real `get_db` wiring). They're plain helpers rather than fixtures (a fixed OHLCV frame
and a listener-based SELECT counter don't need per-test setup/teardown), so callers import them
directly from this module instead of requesting them as fixture arguments.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def db_session():
    # StaticPool keeps a single connection alive for the whole engine, which is required for
    # an in-memory SQLite database to be visible across threads — TestClient runs requests on
    # a separate thread from the one that created the tables below.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([f"2026-01-{i + 1:02d}" for i in range(len(closes))], name="date")
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


class _StubDailyProvider:
    """A minimal DataProvider stand-in for the N+1 regression tests in
    test_portfolio_pricing_session.py and test_portfolio_get_db_wiring.py: always returns a
    fixed daily frame, so every ticker is a guaranteed cache miss on its first fetch --
    CachedDataProvider._upsert() commits mid-loop as a result, which is the exact scenario
    those tests reproduce. Never used as the fallback provider (no caller here exercises a
    fallback path). `get_weekly_ohlcv` returns a fixed flat frame -- unused by
    test_portfolio_pricing_session.py (which calls `enrich_positions_with_price` directly,
    never touching the signal engine's weekly fetch), but exercised by
    test_portfolio_get_db_wiring.py, which goes through the real GET /api/portfolio handler
    end to end and so also triggers the api-portfolio-position-signal per-position signal
    computation's own weekly fetch."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        return _frame([100.0, 110.0])

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        return _frame([100.0, 110.0])


def _count_position_selects(engine: Engine, fn) -> int:
    """Run `fn()` while counting SQL SELECTs issued against the `positions` table on `engine`.

    Takes an `Engine` rather than a `Session` -- for a session-based caller, pass
    `session.get_bind()` (SQLAlchemy sessions are always bound to an `Engine` in these tests).
    """
    select_count = 0

    def _listener(conn, cursor, statement, parameters, context, executemany):
        nonlocal select_count
        upper = statement.strip().upper()
        if upper.startswith("SELECT") and "POSITIONS" in upper:
            select_count += 1

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _listener)
    return select_count
