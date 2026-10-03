"""Integration tests for GET /api/cftc/cot (docs/tasks/backend-cftc-cot-data.json,
docs/tasks/backend-cftc-cot-caching-scheduler.json).

Overrides `app.api.dependencies.get_cftc_cot_provider` directly (the same dependency-
injection seam `tests/integration/test_ibkr_status.py` exercises for IBKR) rather than
touching `CFTCCOTProvider`'s HTTP boundary -- per docs/architecture/Testing.md, no test
makes a live network call. Uses this directory's own `db_session`/`client` fixtures
(tests/integration/conftest.py, an in-memory SQLite database) rather than the plain
top-level `client` fixture, since this endpoint now reads/writes `CFTCCOTCacheORM`
(docs/tasks/backend-cftc-cot-caching-scheduler.json) -- without that override, a request
here would touch the real on-disk `backend/fintrade.db`.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_cftc_cot_provider
from app.data.cftc_cot_cache import CFTCCOTCache
from app.data.cftc_cot_provider import COT_MARKETS, CFTCCOTProvider, COTWeeklyReport
from app.data.exceptions import DataProviderUnavailableError
from app.db.models import CFTCCOTCacheORM
from app.main import app


def _report(
    *,
    report_date: str,
    name: str,
    open_interest: int = 100_000,
    comm_long: int = 40_000,
    comm_short: int = 30_000,
    noncomm_long: int = 35_000,
    noncomm_short: int = 45_000,
    nonrept_long: int = 10_000,
    nonrept_short: int = 12_000,
) -> COTWeeklyReport:
    return COTWeeklyReport(
        report_date=date.fromisoformat(report_date),
        market_and_exchange_name=name,
        open_interest=open_interest,
        commercial_long=comm_long,
        commercial_short=comm_short,
        large_speculator_long=noncomm_long,
        large_speculator_short=noncomm_short,
        small_speculator_long=nonrept_long,
        small_speculator_short=nonrept_short,
    )


class _StubCFTCCOTProvider:
    """Stands in for `CFTCCOTProvider`, exposing only the one method this endpoint calls."""

    def __init__(self, reports_by_market: dict[str, list[COTWeeklyReport]] | None = None, error: Exception | None = None) -> None:
        self._reports_by_market = reports_by_market
        self._error = error

    def get_all_recent(self) -> dict[str, list[COTWeeklyReport]]:
        if self._error is not None:
            raise self._error
        assert self._reports_by_market is not None
        return self._reports_by_market


@pytest.fixture(autouse=True)
def _clear_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_cftc_cot_provider, None)


def test_returns_one_entry_per_fixed_market(client: TestClient) -> None:
    reports_by_market = {
        key: [
            _report(report_date="2026-09-15", name=f"NAME-{key}"),
            _report(report_date="2026-09-08", name=f"NAME-{key}", comm_long=35_000),
        ]
        for key in COT_MARKETS
    }
    app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(reports_by_market)

    response = client.get("/api/cftc/cot")

    assert response.status_code == 200
    body = response.json()
    assert [m["market_key"] for m in body["markets"]] == list(COT_MARKETS.keys())
    gold_entry = next(m for m in body["markets"] if m["market_key"] == "gold")
    assert gold_entry["display_name"] == "NAME-gold"
    assert gold_entry["report_date"] == "2026-09-15"
    assert gold_entry["commercial_net"] == 10_000
    assert gold_entry["large_speculator_net"] == -10_000
    assert gold_entry["small_speculator_net"] == -2_000
    assert gold_entry["weeks_of_history"] == 2
    # Two distinct commercial_net values (10_000 and 5_000) over the window -> current
    # (10_000, the latest week) is the high end of its own range.
    assert gold_entry["commercial_cot_index_52w"] == 100.0


def test_single_week_of_history_has_null_cot_index(client: TestClient) -> None:
    reports_by_market = {key: [_report(report_date="2026-09-15", name=f"NAME-{key}")] for key in COT_MARKETS}
    app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(reports_by_market)

    response = client.get("/api/cftc/cot")

    assert response.status_code == 200
    gold_entry = next(m for m in response.json()["markets"] if m["market_key"] == "gold")
    assert gold_entry["weeks_of_history"] == 1
    assert gold_entry["commercial_cot_index_52w"] is None
    assert gold_entry["large_speculator_cot_index_52w"] is None
    assert gold_entry["small_speculator_cot_index_52w"] is None


def test_provider_unavailable_raises_503(client: TestClient) -> None:
    app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(
        error=DataProviderUnavailableError("CFTC COT request failed: boom")
    )

    response = client.get("/api/cftc/cot")

    assert response.status_code == 503
    assert "boom" in response.json()["detail"]


def test_malformed_cftc_row_returns_503_not_500(client: TestClient, mocker) -> None:
    """Regression test for the pr-reviewer needs_work finding on PR #270 (reproduced
    there by patching `CFTCCOTProvider._request` to return a row without a
    `cftc_contract_market_code` key and hitting this exact endpoint -> 500, not the
    documented 503). Uses the real `CFTCCOTProvider` (not `_StubCFTCCOTProvider`, which
    bypasses `get_all_recent`'s own grouping logic entirely) so the router's real
    `except DataProviderUnavailableError` handling is what's actually exercised."""
    mocker.patch(
        "app.data.cftc_cot_provider.CFTCCOTProvider._request",
        return_value=[{"market_and_exchange_names": "X"}],
    )
    app.dependency_overrides[get_cftc_cot_provider] = lambda: CFTCCOTProvider()

    response = client.get("/api/cftc/cot")

    assert response.status_code == 503


def test_real_provider_is_wired_by_default() -> None:
    """`get_cftc_cot_provider` (no override) yields a real `CFTCCOTProvider` -- confirms
    the dependency is actually wired into the app, distinct from every other test in this
    module which overrides it."""
    from app.api.dependencies import get_cftc_cot_provider as dependency

    assert isinstance(dependency(), CFTCCOTProvider)


class TestCaching:
    """docs/tasks/backend-cftc-cot-caching-scheduler.json: `GET /api/cftc/cot` reads from
    `CFTCCOTCacheORM` first, only falling back to a live CFTC fetch on a genuine cache
    miss (not all 5 fixed markets populated)."""

    def test_cache_hit_never_calls_the_provider(self, client: TestClient, db_session: Session) -> None:
        cache = CFTCCOTCache(db_session)
        cache.refresh(
            {
                key: [_report(report_date="2026-09-15", name=f"NAME-{key}")]
                for key in COT_MARKETS
            }
        )
        app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(
            error=AssertionError("provider must not be called on a cache hit")
        )

        response = client.get("/api/cftc/cot")

        assert response.status_code == 200
        gold_entry = next(m for m in response.json()["markets"] if m["market_key"] == "gold")
        assert gold_entry["display_name"] == "NAME-gold"
        assert gold_entry["report_date"] == "2026-09-15"

    def test_cold_cache_falls_back_to_live_fetch_and_populates_the_cache(
        self, client: TestClient, db_session: Session
    ) -> None:
        reports_by_market = {
            key: [_report(report_date="2026-09-15", name=f"NAME-{key}")] for key in COT_MARKETS
        }
        app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(reports_by_market)

        response = client.get("/api/cftc/cot")

        assert response.status_code == 200
        rows = db_session.query(CFTCCOTCacheORM).filter_by(report_date=date(2026, 9, 15)).all()
        assert {row.market_key for row in rows} == set(COT_MARKETS.keys())
        gold_row = next(row for row in rows if row.market_key == "gold")
        assert gold_row.display_name == "NAME-gold"

    def test_partially_populated_cache_is_still_treated_as_a_miss(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Only 4 of 5 fixed markets cached (e.g. an earlier refresh that didn't fully
        complete) must still fall back to a live fetch -- `GET /api/cftc/cot` needs every
        fixed market to build its response."""
        partial_reports = {
            key: [_report(report_date="2026-09-08", name=f"OLD-{key}")]
            for key in COT_MARKETS
            if key != "bonds"
        }
        CFTCCOTCache(db_session).refresh(partial_reports)

        fresh_reports = {
            key: [_report(report_date="2026-09-15", name=f"FRESH-{key}")] for key in COT_MARKETS
        }
        app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(fresh_reports)

        response = client.get("/api/cftc/cot")

        assert response.status_code == 200
        body = response.json()
        bonds_entry = next(m for m in body["markets"] if m["market_key"] == "bonds")
        assert bonds_entry["display_name"] == "FRESH-bonds"

    def test_cache_miss_live_fetch_failure_still_raises_503(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A genuine cache-miss (empty cache) that also fails its live CFTC fallback
        fetch must still surface as a 503, exactly like the pre-caching behavior."""
        app.dependency_overrides[get_cftc_cot_provider] = lambda: _StubCFTCCOTProvider(
            error=DataProviderUnavailableError("CFTC COT request failed: boom")
        )

        response = client.get("/api/cftc/cot")

        assert response.status_code == 503
        assert db_session.query(CFTCCOTCacheORM).count() == 0
