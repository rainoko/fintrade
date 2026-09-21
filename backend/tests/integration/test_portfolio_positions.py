"""Integration tests for POST /api/portfolio/positions (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override), matching the
pattern in tests/unit/test_db_models.py, so these tests never touch the real fintrade.db file
and don't depend on the db-migrations task's Alembic setup having run.

The `db_session` fixture lives in tests/integration/conftest.py. This module keeps its own
local `client` fixture (shadowing conftest's) rather than reusing it directly: since
backend-trailing-profit-stop's round-2 fix, a same-ticker merge also fetches this ticker's
daily OHLCV (`app.portfolio.risk.trailing_stop_floor_before_merge`) to capture the
`trailing_stop_high_water_mark` floor before the merge overwrites `avg_cost_basis`/
`entry_date` -- so a `get_data_provider` override is needed here too now, same reasoning as
test_portfolio_delete_position.py/test_portfolio_risk.py -- without one, every merge test below
would exercise the real live-network-backed provider, violating docs/architecture/Testing.md's
"no test makes a live network call" rule. The default stub raises
`DataProviderUnavailableError` for every ticker (matching this module's original pre-fetch
behavior for every test that doesn't care about the trailing-stop floor itself): the merge
branch's own graceful-degrade contract means this never blocks a merge, just leaves any
existing floor untouched -- see TestAddPositionCapturesTrailingStopFloorAtMerge below for the
tests that stub real price history and assert on the floor itself.
"""

import json
from datetime import date
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_provider
from app.data.exceptions import DataProviderUnavailableError
from app.db.models import PositionORM
from app.db.session import get_db
from app.main import app
from app.portfolio.models import Position
from app.portfolio.risk import protective_stop, ratchet_trailing_profit_stop


def _daily_frame(closes: list[float], lows: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": lows,
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


class _StubProvider:
    """Serves a fixed daily OHLCV frame per ticker, or raises `DataProviderUnavailableError`
    for any ticker not explicitly stubbed -- see this module's own docstring for why every
    merge test needs a `get_data_provider` override now, and why "not stubbed" degrading
    gracefully (rather than raising/hanging on a real network call) is what keeps every
    pre-existing merge test in this module passing unchanged."""

    def __init__(self, *, daily: dict[str, pd.DataFrame] | None = None) -> None:
        self._daily = daily or {}

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker not in self._daily:
            raise DataProviderUnavailableError(f"{ticker} not stubbed in this test module")
        return self._daily[ticker]

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise DataProviderUnavailableError("weekly history not stubbed in this test module")


def _make_client(db_session: Session, provider: _StubProvider) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


@pytest.fixture
def client(db_session: Session) -> TestClient:
    test_client = _make_client(db_session, _StubProvider())
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_data_provider, None)


def post_position_allowing_non_finite_floats(client: TestClient, payload: dict[str, Any]):
    """httpx (used by TestClient's `json=` kwarg) refuses to serialize float('inf')/float('nan')
    client-side, which would make it impossible to even construct a request carrying them —
    that's a limitation of the test client, not something the server-side schema validation can
    rely on. `json.dumps` (stdlib, `allow_nan=True` by default) happily emits the non-standard
    but widely-accepted `Infinity`/`NaN`/`-Infinity` literals, and Python's own `json.loads`
    (what FastAPI parses the request body with) accepts them right back — so this sends the body
    as raw bytes to reach the server exactly as a real non-Python client sending those literals
    would, and exercises the schema's `allow_inf_nan=False` rejection rather than the test
    client's own serializer."""
    return client.post(
        "/api/portfolio/positions",
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


class TestAddPosition:
    def test_create_new_position_returns_201(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["quantity"] == 100
        assert body["avg_cost_basis"] == 195.30
        assert body["entry_date"] == "2026-05-14"
        assert body["current_price"] is None
        assert body["unrealized_pnl_pct"] is None
        assert body["signal"] is None
        assert body["confidence"] is None
        assert body["confidence_band"] is None
        assert body["id"].startswith("pos_")

    def test_ticker_is_normalized_to_uppercase(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "aapl", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    def test_duplicate_ticker_merges_quantity_and_weighted_avg_cost(self, client: TestClient) -> None:
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 100.0, "entry_date": "2026-05-14"},
        )
        assert first.status_code == 201
        first_id = first.json()["id"]

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 50, "avg_cost_basis": 130.0, "entry_date": "2026-06-01"},
        )

        assert second.status_code == 201
        body = second.json()
        # Merged into the same row, not a new one.
        assert body["id"] == first_id
        assert body["quantity"] == 150
        # Weighted average: (100*100 + 50*130) / 150 = 110.0
        assert body["avg_cost_basis"] == pytest.approx(110.0)
        # Earlier of the two entry dates is kept.
        assert body["entry_date"] == "2026-05-14"

    def test_duplicate_ticker_lowercase_still_merges(self, client: TestClient) -> None:
        client.post(
            "/api/portfolio/positions",
            json={"ticker": "MSFT", "quantity": 10, "avg_cost_basis": 300.0, "entry_date": "2026-02-01"},
        )
        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "msft", "quantity": 5, "avg_cost_basis": 320.0, "entry_date": "2026-01-01"},
        )

        assert second.status_code == 201
        body = second.json()
        assert body["ticker"] == "MSFT"
        assert body["quantity"] == 15
        assert body["entry_date"] == "2026-01-01"

    def test_duplicate_ticker_merge_keeps_later_entry_date_when_existing_is_earlier(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={"ticker": "TSLA", "quantity": 1, "avg_cost_basis": 200.0, "entry_date": "2026-01-01"},
        )
        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "TSLA", "quantity": 1, "avg_cost_basis": 250.0, "entry_date": "2026-03-01"},
        )

        assert second.status_code == 201
        # existing entry_date (2026-01-01) is earlier than the new one, so it's kept.
        assert second.json()["entry_date"] == "2026-01-01"

    def test_different_tickers_create_separate_positions(self, client: TestClient) -> None:
        aapl = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )
        msft = client.post(
            "/api/portfolio/positions",
            json={"ticker": "MSFT", "quantity": 5, "avg_cost_basis": 300.0, "entry_date": "2026-01-01"},
        )

        assert aapl.status_code == 201
        assert msft.status_code == 201
        assert aapl.json()["id"] != msft.json()["id"]

    def test_invalid_body_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100},
        )

        assert response.status_code == 422

    def test_schema_validation_422_detail_is_a_list_not_a_string(self, client: TestClient) -> None:
        """Regression test (PR #17 fourth review round): the route's responses={422: ...}
        override must document ordinary schema-validation failures accurately. This is
        FastAPI's default HTTPValidationError shape (`detail` is a list of per-field error
        objects), not the single-string ErrorDetail shape used by the merge-overflow guard —
        see test_merge_overflow_422_detail_is_a_string_not_a_list for the other shape."""
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100},  # missing avg_cost_basis/entry_date
        )

        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], list)
        assert all("loc" in error and "msg" in error and "type" in error for error in body["detail"])

    def test_zero_quantity_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 0, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_negative_quantity_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": -100, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_zero_avg_cost_basis_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 10, "avg_cost_basis": 0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_negative_avg_cost_basis_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 10, "avg_cost_basis": -5.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_duplicate_ticker_with_quantity_that_would_cancel_existing_returns_422_not_500(
        self, client: TestClient
    ) -> None:
        """Regression test: a negative quantity that would exactly cancel an existing position's
        quantity previously crashed the merge's weighted-avg-cost-basis division with an
        unhandled ZeroDivisionError (raw 500). quantity now has a gt=0 constraint, so this is
        rejected at the validation layer as a 422 before it ever reaches the merge arithmetic."""
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 100.0, "entry_date": "2026-05-14"},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": -100, "avg_cost_basis": 100.0, "entry_date": "2026-06-01"},
        )

        assert second.status_code == 422

    def test_infinite_quantity_returns_422_not_201(self, client: TestClient) -> None:
        """Regression test (PR #17 second review round): gt=0 alone doesn't reject Infinity
        (float('inf') > 0 is True), so quantity=Infinity used to be accepted (201) and, on a
        subsequent same-ticker merge, produced merged_quantity=inf / avg_cost_basis=nan, which
        crashed db.commit() with an unhandled sqlalchemy IntegrityError (NaN into a NOT NULL
        column). allow_inf_nan=False now rejects Infinity/NaN at the schema layer."""
        response = post_position_allowing_non_finite_floats(
            client,
            {"ticker": "AAPL", "quantity": float("inf"), "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_infinite_quantity_422_body_is_valid_json_and_echoes_input_safely(
        self, client: TestClient
    ) -> None:
        """Regression test for a second-order bug surfaced while fixing the Infinity gap:
        Pydantic's finite_number validation error echoes the raw rejected value back in its
        `input` field (e.g. `input: inf`). FastAPI's default RequestValidationError handler
        then hands that straight to Starlette's JSONResponse, which renders with
        `json.dumps(..., allow_nan=False)` — serializing a literal `inf` there raises an
        unhandled ValueError *inside the error handler*, so the client received a raw 500
        (not even a real HTTP response body) instead of a 422, even after the schema-level
        fix. app/main.py registers a RequestValidationError handler that sanitizes non-finite
        floats before responding; this asserts the response is both a real 422 and valid,
        parseable JSON that doesn't crash on decode."""
        response = post_position_allowing_non_finite_floats(
            client,
            {"ticker": "AAPL", "quantity": float("inf"), "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422
        body = response.json()  # would itself raise if the body weren't valid JSON
        [quantity_error] = [e for e in body["detail"] if e["loc"] == ["body", "quantity"]]
        assert quantity_error["type"] == "finite_number"
        # The raw non-finite float is sanitized to its string form rather than omitted, so the
        # error message stays informative without breaking JSON encoding.
        assert quantity_error["input"] == "inf"

    def test_nan_quantity_returns_422(self, client: TestClient) -> None:
        response = post_position_allowing_non_finite_floats(
            client,
            {"ticker": "AAPL", "quantity": float("nan"), "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_infinite_avg_cost_basis_returns_422(self, client: TestClient) -> None:
        response = post_position_allowing_non_finite_floats(
            client,
            {"ticker": "AAPL", "quantity": 10, "avg_cost_basis": float("inf"), "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_nan_avg_cost_basis_returns_422(self, client: TestClient) -> None:
        response = post_position_allowing_non_finite_floats(
            client,
            {"ticker": "AAPL", "quantity": 10, "avg_cost_basis": float("nan"), "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_duplicate_ticker_merge_with_finite_second_post_after_would_be_infinite_first_stays_rejected(
        self, client: TestClient
    ) -> None:
        """End-to-end regression for the exact scenario in the second review round: the first
        POST with Infinity quantity is rejected outright (422), so there's no merged row for a
        second, finite-quantity POST to corrupt via inf/nan arithmetic."""
        first = post_position_allowing_non_finite_floats(
            client,
            {"ticker": "AAPL", "quantity": float("inf"), "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )
        assert first.status_code == 422

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )
        assert second.status_code == 201
        assert second.json()["quantity"] == 10

    def test_empty_ticker_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_whitespace_only_ticker_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "   ", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_duplicate_ticker_merge_of_two_large_finite_values_returns_422_not_500(
        self, client: TestClient
    ) -> None:
        """Regression test (PR #17 third review round): quantity=avg_cost_basis=1e308 is
        individually finite and positive, so it passes schema validation cleanly (201) both
        times it's posted. But merging the two on the second POST overflows Python float64
        arithmetic -- merged_quantity = 1e308 + 1e308 overflows toward the edge of float64's
        representable range, and the weighted-average division produces a value that can't be
        represented as a finite float64 either, which previously reached db.commit() as NaN
        and crashed with an unhandled sqlalchemy.exc.IntegrityError (NOT NULL constraint
        failed) instead of a clean 422. The merge arithmetic now runs on decimal.Decimal and
        the result is checked with math.isfinite() before ever reaching the database."""
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1e308, "avg_cost_basis": 1e308, "entry_date": "2026-01-01"},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1e308, "avg_cost_basis": 1e308, "entry_date": "2026-01-02"},
        )

        assert second.status_code == 422
        assert "detail" in second.json()

    def test_merge_overflow_422_detail_is_a_string_not_a_list(self, client: TestClient) -> None:
        """Regression test (PR #17 fourth review round): the merge-overflow guard raises
        HTTPException(422, detail="...") directly, which FastAPI renders as ErrorDetail's
        single-string `detail` shape — distinct from the list-shaped `detail` that ordinary
        schema validation returns for the same status code on this route (see
        test_schema_validation_422_detail_is_a_list_not_a_string). Both shapes are documented
        via anyOf in the route's responses={422: ...} declaration and backend/openapi.json."""
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1e308, "avg_cost_basis": 1e308, "entry_date": "2026-01-01"},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1e308, "avg_cost_basis": 1e308, "entry_date": "2026-01-02"},
        )

        assert second.status_code == 422
        assert isinstance(second.json()["detail"], str)

    def test_duplicate_ticker_merge_of_two_large_finite_values_does_not_corrupt_existing_row(
        self, client: TestClient
    ) -> None:
        """The rejected merge must not partially mutate or corrupt the existing row: a
        follow-up GET-equivalent (re-triggering the same overflow via a second identical
        oversized POST) should keep failing the same way rather than succeeding after a
        broken commit, and a normal, small merge against the same ticker afterward should
        still succeed and reflect only the original (pre-overflow) quantity."""
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1e308, "avg_cost_basis": 1e308, "entry_date": "2026-01-01"},
        )
        assert first.status_code == 201

        rejected = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1e308, "avg_cost_basis": 1e308, "entry_date": "2026-01-02"},
        )
        assert rejected.status_code == 422

        small_merge = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 1e308, "entry_date": "2026-01-03"},
        )
        assert small_merge.status_code == 201
        assert small_merge.json()["quantity"] == pytest.approx(1e308 + 1)

    def test_create_position_with_entry_notes(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 195.30,
                "entry_date": "2026-05-14",
                "entry_notes": "Breakout above resistance, strong earnings beat.",
            },
        )

        assert response.status_code == 201
        assert response.json()["entry_notes"] == "Breakout above resistance, strong earnings beat."

    def test_create_position_without_entry_notes_is_null(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14"},
        )

        assert response.status_code == 201
        assert response.json()["entry_notes"] is None

    def test_merge_with_no_incoming_notes_keeps_existing_notes_unchanged(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 100.0,
                "entry_date": "2026-05-14",
                "entry_notes": "First buy: strong tide.",
            },
        )

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 50, "avg_cost_basis": 130.0, "entry_date": "2026-06-01"},
        )

        assert second.status_code == 201
        assert second.json()["entry_notes"] == "First buy: strong tide."

    def test_merge_with_incoming_notes_appends_to_existing_notes(self, client: TestClient) -> None:
        client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 100.0,
                "entry_date": "2026-05-14",
                "entry_notes": "First buy: strong tide.",
            },
        )

        second = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 50,
                "avg_cost_basis": 130.0,
                "entry_date": "2026-06-01",
                "entry_notes": "Added on pullback to value zone.",
            },
        )

        assert second.status_code == 201
        assert (
            second.json()["entry_notes"]
            == "First buy: strong tide.\n\nAdded on pullback to value zone."
        )

    def test_merge_with_incoming_notes_and_no_existing_notes_sets_notes(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 100.0, "entry_date": "2026-05-14"},
        )

        second = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 50,
                "avg_cost_basis": 130.0,
                "entry_date": "2026-06-01",
                "entry_notes": "Added on pullback to value zone.",
            },
        )

        assert second.status_code == 201
        assert second.json()["entry_notes"] == "Added on pullback to value zone."

    def test_create_position_with_empty_string_entry_notes_normalizes_to_null(
        self, client: TestClient
    ) -> None:
        """Regression test (backend-trade-journal-entry-notes-followups, PR #213 review): an
        explicit entry_notes: "" used to round-trip as "" rather than null, unlike every other
        omitted-vs-blank case on this endpoint."""
        response = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 195.30,
                "entry_date": "2026-05-14",
                "entry_notes": "",
            },
        )

        assert response.status_code == 201
        assert response.json()["entry_notes"] is None

    def test_create_position_with_whitespace_only_entry_notes_normalizes_to_null(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 195.30,
                "entry_date": "2026-05-14",
                "entry_notes": "   ",
            },
        )

        assert response.status_code == 201
        assert response.json()["entry_notes"] is None

    def test_create_position_with_explicit_null_entry_notes(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 195.30,
                "entry_date": "2026-05-14",
                "entry_notes": None,
            },
        )

        assert response.status_code == 201
        assert response.json()["entry_notes"] is None

    def test_create_position_with_padded_entry_notes_is_stripped(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 195.30,
                "entry_date": "2026-05-14",
                "entry_notes": "  Breakout above resistance.  ",
            },
        )

        assert response.status_code == 201
        assert response.json()["entry_notes"] == "Breakout above resistance."

    def test_merge_with_whitespace_only_incoming_notes_leaves_existing_notes_unchanged(
        self, client: TestClient
    ) -> None:
        """Regression test: a whitespace-only entry_notes on a merge used to be truthy under
        `if position.entry_notes:` and get appended onto the existing note verbatim (as
        whitespace). It now normalizes to None at the schema layer before the merge check runs,
        so it's treated exactly like an omitted entry_notes -- the existing note is left as is."""
        client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 100.0,
                "entry_date": "2026-05-14",
                "entry_notes": "First buy: strong tide.",
            },
        )

        second = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 50,
                "avg_cost_basis": 130.0,
                "entry_date": "2026-06-01",
                "entry_notes": "   ",
            },
        )

        assert second.status_code == 201
        assert second.json()["entry_notes"] == "First buy: strong tide."

    def test_create_position_with_strategy(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 195.30,
                "entry_date": "2026-05-14",
                "strategy": "Pullback to value",
            },
        )

        assert response.status_code == 201
        assert response.json()["strategy"] == "Pullback to value"

    def test_create_position_without_strategy_is_null(self, client: TestClient) -> None:
        response = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14"},
        )

        assert response.status_code == 201
        assert response.json()["strategy"] is None

    def test_merge_with_no_incoming_strategy_keeps_existing_strategy_unchanged(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 100.0,
                "entry_date": "2026-05-14",
                "strategy": "Pullback to value",
            },
        )

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 50, "avg_cost_basis": 130.0, "entry_date": "2026-06-01"},
        )

        assert second.status_code == 201
        assert second.json()["strategy"] == "Pullback to value"

    def test_merge_with_incoming_strategy_overwrites_existing_strategy(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 100,
                "avg_cost_basis": 100.0,
                "entry_date": "2026-05-14",
                "strategy": "Pullback to value",
            },
        )

        second = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 50,
                "avg_cost_basis": 130.0,
                "entry_date": "2026-06-01",
                "strategy": "False breakout with a divergence",
            },
        )

        assert second.status_code == 201
        # Overwritten, not appended -- unlike entry_notes, see this task's `decisions` entry.
        assert second.json()["strategy"] == "False breakout with a divergence"

    def test_merge_with_incoming_strategy_and_no_existing_strategy_sets_strategy(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 100.0, "entry_date": "2026-05-14"},
        )

        second = client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "AAPL",
                "quantity": 50,
                "avg_cost_basis": 130.0,
                "entry_date": "2026-06-01",
                "strategy": "Pullback to value",
            },
        )

        assert second.status_code == 201
        assert second.json()["strategy"] == "Pullback to value"

    def test_whitespace_padded_ticker_is_stripped_and_merges_with_existing(
        self, client: TestClient
    ) -> None:
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 100, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )
        assert first.status_code == 201
        first_id = first.json()["id"]

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": " AAPL ", "quantity": 10, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )

        assert second.status_code == 201
        body = second.json()
        assert body["id"] == first_id
        assert body["ticker"] == "AAPL"
        assert body["quantity"] == 110


class TestAddPositionCapturesTrailingStopFloorAtMerge:
    """backend-trailing-profit-stop, round 2: `PositionORM.trailing_stop_high_water_mark` (the
    persisted floor behind `GET /api/portfolio/risk`'s `RiskPosition.trailing_stop` hard
    ratchet) is now locked in HERE, on a same-ticker merge, rather than by that GET route
    itself -- see this task's `decisions` entry for the full round-2 history (an earlier
    revision had GET do the writing, reverted after review flagged it as violating HTTP GET's
    safe/idempotent contract)."""

    def test_merge_captures_the_pre_merge_ratchet_as_a_persisted_floor(
        self, db_session: Session
    ) -> None:
        """Reproduces PR #240's original merge-regression fixture end to end through the POST
        route itself: entered at $100, rallies to +15% profit (comfortably past the 10%
        breakeven trigger), then merges in a buy at $200/share (avg_cost_basis -> $150, no
        price movement) -- the floor captured by this merge must reflect the ratchet computed
        against the OLD avg_cost_basis=100, not the new, higher one."""
        rally_closes = [100.0 + 15.0 * i / 14.0 for i in range(15)]  # ends at +15% profit
        rally_lows = [c - 1.0 for c in rally_closes]
        daily = _daily_frame(rally_closes, rally_lows)
        test_client = _make_client(db_session, _StubProvider(daily={"AAPL": daily}))
        try:
            first = test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
            )
            assert first.status_code == 201
            position_id = first.json()["id"]

            second = test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 200.0, "entry_date": "2026-01-01"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert second.status_code == 201
        assert second.json()["avg_cost_basis"] == pytest.approx(150.0)

        old_position = Position(
            id=position_id, ticker="AAPL", quantity=1.0, avg_cost_basis=100.0, entry_date=date(2026, 1, 1)
        )
        expected_stop = protective_stop(old_position, daily.iloc[:-1])
        expected_floor = ratchet_trailing_profit_stop(old_position, daily, expected_stop)
        # 100 + 1/3 * (15 - 10) == 101.666... -- computed against the OLD $100 cost basis.
        assert expected_floor == pytest.approx(101.666667, abs=1e-4)

        row = db_session.get(PositionORM, position_id)
        assert row.trailing_stop_high_water_mark == pytest.approx(expected_floor)

    def test_merge_with_unstubbed_ticker_leaves_floor_none(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A merge whose price-history fetch fails (the default stub raises
        `DataProviderUnavailableError` for every ticker) must still succeed, leaving
        `trailing_stop_high_water_mark` untouched (`None`) rather than fabricating a floor from
        no data."""
        first = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
        )
        assert first.status_code == 201
        position_id = first.json()["id"]

        second = client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 200.0, "entry_date": "2026-01-01"},
        )
        assert second.status_code == 201

        row = db_session.get(PositionORM, position_id)
        assert row.trailing_stop_high_water_mark is None

    def test_merge_data_provider_failure_does_not_block_the_merge(
        self, db_session: Session
    ) -> None:
        """A `DataProviderError` fetching this ticker's daily history at merge time must
        degrade to leaving `trailing_stop_high_water_mark` untouched, never block or fail the
        merge itself -- adding a position must never depend on live market data being
        reachable."""
        test_client = _make_client(db_session, _StubProvider())  # nothing stubbed -> always fails
        try:
            first = test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "TSLA", "quantity": 1, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
            )
            assert first.status_code == 201
            position_id = first.json()["id"]

            second = test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "TSLA", "quantity": 1, "avg_cost_basis": 300.0, "entry_date": "2026-01-01"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert second.status_code == 201
        assert second.json()["avg_cost_basis"] == pytest.approx(200.0)

        row = db_session.get(PositionORM, position_id)
        assert row.trailing_stop_high_water_mark is None

    def test_second_merge_advances_an_already_persisted_floor(self, db_session: Session) -> None:
        """A second same-ticker merge, after the first already locked in a floor, must never
        lower that floor -- `trailing_stop_floor_before_merge` folds the existing persisted
        value in as its own floor (`ratchet_trailing_profit_stop`'s `persisted_high_water_mark`
        kwarg), so this is a genuine hard-ratchet property of the merge path itself, not just
        of GET /api/portfolio/risk's read. One deep downside wick is mixed into the fixture
        (matching PR #240's own regression fixture) so this genuinely exercises the persisted
        floor overriding a lower fresh recompute, rather than the floor being trivially
        satisfied by an incidentally-higher live SafeZone stop."""
        rally_closes = [100.0 + 15.0 * i / 14.0 for i in range(15)]  # ends at +15% profit
        rally_lows = [c - 1.0 for c in rally_closes]
        rally_lows[10] = 85.0
        daily = _daily_frame(rally_closes, rally_lows)
        test_client = _make_client(db_session, _StubProvider(daily={"AAPL": daily}))
        try:
            first = test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 100.0, "entry_date": "2026-01-01"},
            )
            position_id = first.json()["id"]

            # First merge: avg_cost_basis 100 -> 150, locking in ~101.667 as the floor.
            test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "AAPL", "quantity": 1, "avg_cost_basis": 200.0, "entry_date": "2026-01-01"},
            )
            floor_after_first_merge = db_session.get(PositionORM, position_id).trailing_stop_high_water_mark
            assert floor_after_first_merge == pytest.approx(101.666667, abs=1e-4)

            # Second merge: same unchanged rally_daily price history, avg_cost_basis 150 -> a
            # much higher blended value that would, computed fresh under the new cost basis
            # alone, no longer even cross the 10% trigger (mirrors PR #240's original repro).
            second = test_client.post(
                "/api/portfolio/positions",
                json={"ticker": "AAPL", "quantity": 10, "avg_cost_basis": 500.0, "entry_date": "2026-01-01"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_data_provider, None)

        assert second.status_code == 201

        row = db_session.get(PositionORM, position_id)
        assert row.trailing_stop_high_water_mark >= floor_after_first_merge
        assert row.trailing_stop_high_water_mark == pytest.approx(floor_after_first_merge)
