"""Real-concurrency reproduction of the same-ticker merge lost-update race
(backend-position-watchlist-race-condition-followups) that `test_portfolio_positions.py`'s
`TestAddPositionMergeLostUpdateRace` demonstrates with a single extra session racing
`db_session`'s own commit.

This module goes one step further: real OS threads, each with its own SQLAlchemy session
bound to its own connection against a shared temp-file SQLite database (not the in-memory
`StaticPool`-backed `db_session` fixture most of this suite uses, which shares one underlying
connection and so can't model two genuinely independent writers), issuing two real concurrent
HTTP requests through `TestClient` -- as close to the real two-process/two-connection
production shape as a test can get without actually spawning two server processes.

A `threading.Barrier` forces the two requests to both have already read the same pre-commit
`existing` row before either is allowed to proceed to merge + commit, guaranteeing a genuine
interleaving rather than one request trivially completing before the other starts (without
this, the test would prove nothing about the race -- Python's GIL and typical scheduling would
otherwise very likely just run the two requests back-to-back).

This is the "genuine mutation-testing" reproduction backend-position-watchlist-race-condition-
followups's task description asked for: manually reverting `PositionORM.version`/
`_merge_and_commit`'s retry loop during development and re-running this test confirmed it
fails (final quantity reflects only one of the two concurrent requests, and/or one request's
response is lost in a way the test's own assertions catch) -- see this task's `decisions`
entry.
"""

import threading
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.api.routers.portfolio as portfolio
from app.api.dependencies import get_data_provider
from app.data.exceptions import DataProviderUnavailableError
from app.db.models import Base, PositionORM
from app.db.session import get_db
from app.main import app


class _StubProvider:
    """Mirrors test_portfolio_positions.py's `_StubProvider`, duplicated here (rather than
    imported across test modules, which this codebase has no existing precedent for) since
    this module's whole point is being a self-contained, from-scratch reproduction -- every
    ticker degrades gracefully (no live network call), matching
    docs/architecture/Testing.md's "no test makes a live network call" rule."""

    def get_daily_ohlcv(self, ticker: str) -> Any:
        raise DataProviderUnavailableError(f"{ticker} not stubbed in this test module")

    def get_weekly_ohlcv(self, ticker: str) -> Any:
        raise DataProviderUnavailableError("weekly history not stubbed in this test module")


@pytest.fixture
def file_db_sessionmaker(tmp_path: Any) -> Any:
    """A real file-backed SQLite engine (not `:memory:`/`StaticPool`) -- each `Session()` this
    sessionmaker produces gets its own connection from the pool, exactly like
    `app.db.session.SessionLocal` does in production, so two sessions can genuinely hold
    independent, concurrently-open transactions against the same database."""
    db_path = tmp_path / "lost_update_race.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    try:
        yield TestingSessionLocal
    finally:
        engine.dispose()


class TestConcurrentMergeRaceRealHTTPConcurrency:
    def test_two_real_concurrent_requests_for_the_same_existing_ticker_lose_no_update(
        self, file_db_sessionmaker: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Seed the pre-existing row directly, through its own throwaway session.
        seed_db: Session = file_db_sessionmaker()
        seed_db.add(
            PositionORM(
                id="pos_1",
                ticker="AAPL",
                quantity=10.0,
                avg_cost_basis=100.0,
                entry_date=date(2026, 1, 1),
            )
        )
        seed_db.commit()
        seed_db.close()

        def override_get_db() -> Any:
            db = file_db_sessionmaker()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_data_provider] = lambda: _StubProvider()

        # Forces both requests to have already loaded their own (identical, stale) `existing`
        # row before either is allowed to proceed into `_merge_position` for real -- the exact
        # interleaving that causes the lost-update race. Each thread only waits on its OWN
        # first call (tracked by `threading.get_ident()`), so `_merge_and_commit`'s later
        # retry call(s) for the losing thread proceed immediately rather than deadlocking on a
        # barrier whose other party has already finished.
        barrier = threading.Barrier(2, timeout=10)
        released_once: set[int] = set()
        released_lock = threading.Lock()
        original_merge_position = portfolio._merge_position

        def _merge_position_with_barrier(
            existing: PositionORM, position: Any, provider: Any
        ) -> PositionORM:
            tid = threading.get_ident()
            with released_lock:
                first_call_for_this_thread = tid not in released_once
                released_once.add(tid)
            if first_call_for_this_thread:
                barrier.wait()
            return original_merge_position(existing, position, provider)

        monkeypatch.setattr(portfolio, "_merge_position", _merge_position_with_barrier)

        results: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}

        def _post(key: str, quantity: float, avg_cost_basis: float) -> None:
            try:
                client = TestClient(app)
                results[key] = client.post(
                    "/api/portfolio/positions",
                    json={
                        "ticker": "AAPL",
                        "quantity": quantity,
                        "avg_cost_basis": avg_cost_basis,
                        "entry_date": "2026-02-01",
                    },
                )
            except BaseException as exc:  # pragma: no cover -- surfaced via `errors` below
                errors[key] = exc

        thread_a = threading.Thread(target=_post, args=("a", 5.0, 150.0))
        thread_b = threading.Thread(target=_post, args=("b", 7.0, 200.0))
        try:
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=15)
            thread_b.join(timeout=15)
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert not errors, f"Unexpected exception(s) in request thread(s): {errors}"
        assert not thread_a.is_alive(), "thread_a did not finish within the timeout"
        assert not thread_b.is_alive(), "thread_b did not finish within the timeout"

        assert "a" in results and "b" in results
        assert results["a"].status_code == 201, results["a"].text
        assert results["b"].status_code == 201, results["b"].text

        verify_db: Session = file_db_sessionmaker()
        try:
            row = verify_db.query(PositionORM).filter_by(ticker="AAPL").one()
        finally:
            verify_db.close()

        # The crux of this whole reproduction: BOTH concurrent requests' own quantities must
        # be reflected in the final row -- 10 (original) + 5 (thread_a) + 7 (thread_b) = 22,
        # never just 15 or 17 (either of which would mean one request's real, user-submitted
        # data was silently dropped by the lost-update race this task's fix closes).
        assert row.quantity == pytest.approx(22.0)
        expected_avg_cost_basis = (10.0 * 100.0 + 5.0 * 150.0 + 7.0 * 200.0) / 22.0
        assert row.avg_cost_basis == pytest.approx(expected_avg_cost_basis, abs=1e-6)
        # `version` must have advanced exactly twice (once per successful merge commit) --
        # not once, which would mean one request's commit silently clobbered the other's
        # without the version check ever tripping.
        assert row.version == 3  # 1 (insert) + 1 (thread_a's or thread_b's merge) + 1 (retry)
