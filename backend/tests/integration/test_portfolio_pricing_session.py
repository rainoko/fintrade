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

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data.cache import CachedDataProvider
from app.db.models import Base, PositionORM
from app.portfolio.pricing import enrich_positions_with_price
from tests.integration.conftest import _count_position_selects, _StubDailyProvider


def _make_session(*, expire_on_commit: bool) -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=expire_on_commit
    )
    return TestingSessionLocal()


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

            provider = CachedDataProvider(_StubDailyProvider(), _StubDailyProvider(), session)

            select_count = _count_position_selects(
                session.get_bind(), lambda: enrich_positions_with_price(rows, provider)
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

            provider = CachedDataProvider(_StubDailyProvider(), _StubDailyProvider(), session)

            select_count = _count_position_selects(
                session.get_bind(), lambda: enrich_positions_with_price(rows, provider)
            )

            assert select_count > 0
        finally:
            session.close()
