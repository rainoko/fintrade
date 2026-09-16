"""True end-to-end regression test for the N+1 fix (app/db/session.py's `SessionLocal`,
`expire_on_commit=False`) exercised through the *actual production wiring*: the real,
unmocked `get_db` FastAPI dependency calling the real `app.db.session.SessionLocal`.

Neither existing regression test goes through that path:

- tests/integration/test_portfolio_pricing_session.py builds its own, entirely separate
  `sessionmaker(...)` in isolation to reproduce the bug/fix behaviorally.
- tests/unit/test_db_session.py asserts the `expire_on_commit` flag directly on the real
  `SessionLocal` object, but never issues a request through it.
- tests/integration/conftest.py's shared `db_session`/`client` fixtures (used by most other
  GET /api/portfolio tests, e.g. test_portfolio_get.py) override `get_db` entirely with a
  session from a *different* sessionmaker that doesn't set `expire_on_commit=False` at all --
  so even a passing request through those fixtures says nothing about the real `get_db` ->
  `SessionLocal` wiring.

None of the three would catch a future regression that drops the `expire_on_commit=False`
kwarg from -- or introduces a second, differently-configured sessionmaker for -- the real
`SessionLocal`, since none of them actually calls it.

This module deliberately does NOT use conftest.py's `db_session`/`client` fixtures or override
`get_db` at all. Instead it monkeypatches `app.db.session.SessionLocal`/`engine` in place,
copying whatever kwargs the real `SessionLocal` was actually constructed with (so a future
kwarg regression flows straight into this test's assertion below) onto a throwaway in-memory
engine, and monkeypatches the two upstream provider classes `app/api/dependencies.py`'s
`get_data_provider` composes `CachedDataProvider` from (so no live network call happens) --
while `get_db`, `get_data_provider`, and the route handlers themselves all run completely
unmodified, production code. See the api-portfolio-get-followups-followups task's
`decisions` entry.

It does still import `_StubDailyProvider` and `_count_position_selects` from conftest.py --
plain helpers shared with test_portfolio_pricing_session.py's regression test for the same
fix, not fixtures -- see the api-portfolio-get-followups-followups-followups task's
`decisions` entry.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.dependencies as dependencies_module
import app.db.session as db_session_module
from app.db.models import AccountORM, Base, PositionORM
from app.main import app
from tests.integration.conftest import _count_position_selects, _StubDailyProvider


@pytest.fixture
def real_wiring_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Engine]]:
    """A `TestClient` with NO `app.dependency_overrides` at all: `get_db`, `get_data_provider`,
    and the route handlers all run exactly as they would in production. Only the engine
    `SessionLocal` binds to, and the two network-calling provider classes, are swapped out --
    via `monkeypatch` on the real module attributes, not FastAPI's override mechanism."""
    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(test_engine)

    # Copy *whatever* kwargs the real SessionLocal was actually constructed with (notably
    # expire_on_commit) onto a sessionmaker bound to the throwaway engine above, so a future
    # regression to the real SessionLocal's kwargs changes what this fixture builds too,
    # rather than this test hardcoding today's known-good value a second time.
    real_kw = dict(db_session_module.SessionLocal.kw)
    real_kw["bind"] = test_engine
    test_session_local = sessionmaker(**real_kw)
    monkeypatch.setattr(db_session_module, "SessionLocal", test_session_local)
    monkeypatch.setattr(db_session_module, "engine", test_engine)

    # app/api/dependencies.py's get_data_provider constructs YFinanceProvider()/StooqProvider()
    # itself (there's no dependency-injected provider to override) -- swap the classes it
    # composes CachedDataProvider from so no live network call happens, leaving
    # get_data_provider's own logic (and CachedDataProvider, and get_db) running unmodified.
    monkeypatch.setattr(dependencies_module, "YFinanceProvider", _StubDailyProvider)
    monkeypatch.setattr(dependencies_module, "StooqProvider", _StubDailyProvider)

    try:
        yield TestClient(app), test_engine
    finally:
        test_engine.dispose()


class TestRealGetDbWiringAvoidsNPlusOne:
    def test_get_portfolio_issues_no_reselects_after_cache_miss_commit(
        self, real_wiring_client: tuple[TestClient, Engine]
    ) -> None:
        client, test_engine = real_wiring_client
        seed_session = db_session_module.SessionLocal()
        try:
            seed_session.add(AccountORM(id=1, cash=1000.0))
            seed_session.add(
                PositionORM(
                    id="pos_1", ticker="AAPL", quantity=10.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1)
                )
            )
            seed_session.add(
                PositionORM(
                    id="pos_2", ticker="MSFT", quantity=5.0, avg_cost_basis=200.0, entry_date=date(2026, 1, 1)
                )
            )
            seed_session.commit()
        finally:
            seed_session.close()

        response_holder: dict = {}

        def _call() -> None:
            response_holder["response"] = client.get("/api/portfolio")

        select_count = _count_position_selects(test_engine, _call)

        response = response_holder["response"]
        assert response.status_code == 200
        body = response.json()
        by_ticker = {p["ticker"]: p for p in body["positions"]}
        assert by_ticker["AAPL"]["current_price"] == pytest.approx(110.0)
        assert by_ticker["MSFT"]["current_price"] == pytest.approx(110.0)

        # Exactly one SELECT against `positions` for the whole request: the route handler's
        # initial listing query (app/api/routers/portfolio.py's `_ordered_positions`). Each
        # ticker's price fetch is a cache miss, so CachedDataProvider commits mid-loop
        # (app/data/cache.py's `_upsert`) while the *other* row's already-loaded attributes
        # are still pending access; with the real SessionLocal's `expire_on_commit=False`
        # that commit doesn't expire either loaded row, so neither one re-triggers a SELECT
        # by primary key afterward. If a future change dropped `expire_on_commit=False` from
        # the real SessionLocal (or wired get_db to a second, default-configured
        # sessionmaker), this would regress to a higher count and this assertion would fail.
        assert select_count == 1
