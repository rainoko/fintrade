"""Integration tests for POST /api/portfolio/positions (app/api/routers/portfolio.py).

Uses an isolated in-memory SQLite session (via a get_db dependency override), matching the
pattern in tests/unit/test_db_models.py, so these tests never touch the real fintrade.db file
and don't depend on the db-migrations task's Alembic setup having run.

The `db_session`/`client` fixtures live in tests/integration/conftest.py.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient


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
