---
name: add-api-endpoint
description: Add or change a FastAPI endpoint (backend) and keep it in sync with the frontend TypeScript client, MSW mocks, and docs/architecture/API.md. Use when asked to add a new API route, change a request/response shape, or fix a frontend/backend contract mismatch.
---

# Add API Endpoint

The API contract is documented in `docs/architecture/API.md` and is meant to be the human-readable mirror of the backend's OpenAPI schema. Backend and frontend structure are in `docs/architecture/Backend.md` and `docs/architecture/Frontend.md`.

## Steps

1. **Check `docs/architecture/API.md` first.** If the endpoint or shape you need isn't documented there, decide the shape as part of this change (conventions: ISO 8601 UTC timestamps, floats not strings for money/price, `{"detail": string}` error shape, versionless `/api/...` paths) and update the doc in the same change — don't let API.md drift from what actually ships.

2. **Backend: schema + router.**
   - Define/update the Pydantic request/response models in `app/api/schemas.py`.
   - Declare the route in the relevant `app/api/routers/*.py` with its full contract: `response_model`, an explicit `operation_id` (for clean generated frontend function/type names), a `summary`, and `responses={...}` for every documented error case (404/422/503, using the `ErrorDetail` schema) — do this even if the handler body is still a stub. The contract must be complete before the logic is, so frontend work isn't blocked on it.
   - Implement (or update) the handler body. Cover the error cases listed in API.md (unknown ticker → 404, data provider unavailable → 503, insufficient history → 422, etc.) — don't let unhandled exceptions leak as raw 500s with stack traces.

3. **Backend: integration test.** Add/update a test in `tests/integration/` using FastAPI's `TestClient`, with the data-provider layer mocked underneath (per `docs/architecture/Testing.md` — no live network calls). Assert the full response shape matches what API.md documents, including error responses.

4. **Backend: regenerate the committed OpenAPI snapshot.** Run `python scripts/export_openapi.py` from `backend/` and commit the updated `backend/openapi.json` — this is the file the frontend actually builds against (see `docs/architecture/API.md` §Contract Snapshot & Parallel Development). Do this even before the handler body is fully implemented, as soon as the route's signature/schema is final, so frontend work can start immediately.

5. **Frontend: regenerate types.** `frontend/src/api/types.ts` is generated from the committed `backend/openapi.json` (not a live server, not hand-typed) — see `docs/architecture/Frontend.md` §5. Regenerate after every snapshot update so the two sides can't silently drift.

6. **Frontend: typed client function + MSW mock.** Add/update the corresponding function in `frontend/src/api/stocks.ts` or `portfolio.ts`, and the matching handler in `frontend/tests/mocks/` so component/hook tests exercise the new contract without a real network call.

7. **Frontend: hook/component tests.** If a hook (`useStockAnalysis`, `usePortfolio`) or component consumes the new/changed endpoint, add tests for its happy path and its error/empty states (per `docs/architecture/Testing.md`), not just the happy path.

8. **Run coverage on both sides** before finishing — see the `check-coverage` skill.

## Common Mistakes to Avoid

- Changing `app/api/schemas.py` or a route's signature without re-running `python scripts/export_openapi.py` — the committed `backend/openapi.json` is what the frontend actually builds against, so a stale snapshot silently breaks the parallel-work model in `docs/architecture/API.md` §Contract Snapshot & Parallel Development.
- Changing a backend response shape without regenerating frontend types from the refreshed snapshot — this is exactly the drift `docs/architecture/API.md`'s "Frontend Type Generation" note exists to prevent.
- Adding an endpoint without an error-case test (404/422/503) — API.md explicitly calls these out as required coverage, not optional.
- Hand-editing `api/types.ts` instead of regenerating it, "just this once" — this is how the two sides quietly diverge.
