"""Integration tests for GET /api/cftc/cot (docs/tasks/backend-cftc-cot-data.json).

Overrides `app.api.dependencies.get_cftc_cot_provider` directly (the same dependency-
injection seam `tests/integration/test_ibkr_status.py` exercises for IBKR) rather than
touching `CFTCCOTProvider`'s HTTP boundary -- per docs/architecture/Testing.md, no test
makes a live network call.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_cftc_cot_provider
from app.data.cftc_cot_provider import COT_MARKETS, CFTCCOTProvider, COTWeeklyReport
from app.data.exceptions import DataProviderUnavailableError
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
    from datetime import date

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


def test_real_provider_is_wired_by_default() -> None:
    """`get_cftc_cot_provider` (no override) yields a real `CFTCCOTProvider` -- confirms
    the dependency is actually wired into the app, distinct from every other test in this
    module which overrides it."""
    from app.api.dependencies import get_cftc_cot_provider as dependency

    assert isinstance(dependency(), CFTCCOTProvider)
