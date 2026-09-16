"""Regression test for the N+1 query pattern flagged on PR #30 and tracked on the
api-portfolio-get-followups task: a request-scoped SQLAlchemy `Session` shared between a
route handler's position query and `CachedDataProvider` (app/data/cache.py) used to expire
every already-loaded `PositionORM` row on the cache's mid-loop `_upsert()` commit (the
SQLAlchemy `expire_on_commit=True` default), turning each subsequent row-attribute access
during `enrich_positions_with_price`'s loop (app/portfolio/pricing.py) into its own re-SELECT.

Fixed by app/db/session.py's `SessionLocal` passing `expire_on_commit=False` -- this test
builds its own sessionmaker with that same setting (mirroring the pattern in
tests/unit/data/test_cache.py's `session` fixture) and counts SQL SELECTs issued against the
`positions` table across a two-position enrichment loop that includes a real cache-miss
commit partway through, to prove the fix actually avoids the re-query rather than just
asserting the config flag in isolation (tests/unit/test_db_session.py does that part).
"""

from datetime import date

import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.data.cache import CachedDataProvider
from app.db.models import Base, PositionORM
from app.portfolio.pricing import enrich_positions_with_price


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


class _NetworkStub:
    """A minimal primary DataProvider: always returns a fixed daily frame, never used as the
    fallback (no test here exercises a fallback path), so every ticker is a guaranteed cache
    miss the first time -- CachedDataProvider._upsert() commits on the shared session as a
    result, which is the exact mid-loop commit this test is reproducing."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        return _frame([100.0, 110.0])

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:  # pragma: no cover - unused here
        raise NotImplementedError


def _make_session(*, expire_on_commit: bool) -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=expire_on_commit
    )
    return TestingSessionLocal()


def _count_position_selects(session: Session, fn) -> int:
    select_count = 0

    def _listener(conn, cursor, statement, parameters, context, executemany):
        nonlocal select_count
        upper = statement.strip().upper()
        if upper.startswith("SELECT") and "POSITIONS" in upper:
            select_count += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _listener)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _listener)
    return select_count


class TestNoNPlusOneOnMidLoopCacheCommit:
    def test_expire_on_commit_false_avoids_reselecting_positions_after_cache_write(self) -> None:
        session = _make_session(expire_on_commit=False)
        try:
            session.add(
                PositionORM(
                    id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1)
                )
            )
            session.add(
                PositionORM(
                    id="pos_2", ticker="MSFT", quantity=5.0, avg_cost_basis=200.0, entry_date=date(2026, 1, 1)
                )
            )
            session.commit()
            rows = session.query(PositionORM).order_by(PositionORM.id).all()

            provider = CachedDataProvider(_NetworkStub(), _NetworkStub(), session)

            select_count = _count_position_selects(
                session, lambda: enrich_positions_with_price(rows, provider)
            )

            # Both cache misses (AAPL then MSFT) commit on the shared session; with
            # expire_on_commit=False neither commit re-expires the already-loaded rows, so
            # enrich_positions_with_price's attribute access (row.ticker, row.quantity, etc.)
            # for the *second* row never re-issues a SELECT against positions.
            assert select_count == 0
        finally:
            session.close()

    def test_expire_on_commit_true_reproduces_the_n_plus_one(self) -> None:
        """Sanity check for the test above: confirms the query-counting technique itself is
        sensitive to this bug by reproducing it under the pre-fix SQLAlchemy default, so the
        `select_count == 0` assertion above isn't vacuously true regardless of configuration.
        """
        session = _make_session(expire_on_commit=True)
        try:
            session.add(
                PositionORM(
                    id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1)
                )
            )
            session.add(
                PositionORM(
                    id="pos_2", ticker="MSFT", quantity=5.0, avg_cost_basis=200.0, entry_date=date(2026, 1, 1)
                )
            )
            session.commit()
            rows = session.query(PositionORM).order_by(PositionORM.id).all()

            provider = CachedDataProvider(_NetworkStub(), _NetworkStub(), session)

            select_count = _count_position_selects(
                session, lambda: enrich_positions_with_price(rows, provider)
            )

            assert select_count > 0
        finally:
            session.close()
