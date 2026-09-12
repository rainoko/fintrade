---
name: architecture-review
description: Review code (a change, a module, or the whole codebase) against docs/Architecture.md and docs/architecture/{Backend,Frontend,API,Testing}.md for structural conformance — layering, module placement, dependency choices — flagging deviations from the documented design. Use when asked to review architecture, audit project structure, or before merging a change that adds a new module, dependency, or layer.
---

# Architecture Review

`docs/Architecture.md` and its sub-docs (`docs/architecture/Backend.md`, `Frontend.md`, `API.md`, `Testing.md`) are the structural source of truth. This is a structural/layering review — for a review of whether the *trading logic itself* is correct, use `verify-elder-signal` instead.

## Checklist

### Cross-Cutting (Architecture.md §3)
- No live network calls anywhere in the test suites (backend or frontend) — market data and the API boundary are always mocked in tests.
- Confidence scores and signals are computed **only** in the backend; the frontend renders them, never recomputes or adjusts them.
- OHLCV is going through the SQLite cache layer, not re-fetched from yfinance/Stooq on every request.

### Backend (Backend.md)
- Module placement matches the documented layout: `data/` adapters implement the `DataProvider` protocol (interchangeable, mockable), `indicators/` are pure functions with no I/O or global state, `signals/` only orchestrates (no indicator math inlined there), `portfolio/risk.py` and `portfolio/exits.py` stay separate from `signals/engine.py`'s fresh-entry logic.
- No new dependency added without a clear fit to the table in Backend.md §3 — if a genuinely new one is needed, the doc should be updated in the same change, not left silently stale.
- Persistence stays SQLite via SQLAlchemy + Alembic per Backend.md §7 — flag any change introducing a different DB/ORM without a documented decision to change it.
- API routers stay thin: validation/shape in `app/api/schemas.py`, business logic in `signals/`/`portfolio/`, not embedded in route handlers.

### Frontend (Frontend.md)
- Server state goes through React Query; flag any hand-rolled fetch/loading/error state that duplicates what a query hook should own.
- No Redux/Zustand or other global client-state library added without a concrete cross-page state need that React context/local state can't cover — Frontend.md is explicit this shouldn't be added preemptively.
- Chart code stays inside `components/charts/`, using `lightweight-charts` — flag any chart logic leaking into page components or a second charting library being introduced.
- `api/types.ts` is generated from the backend OpenAPI schema, not hand-maintained — flag manual edits that duplicate a backend schema instead of regenerating.

### API Contract (API.md)
- Every new/changed endpoint is reflected in `docs/architecture/API.md` — check the doc was updated in the same change, not left describing a stale shape.
- Response conventions are followed: ISO 8601 UTC timestamps, numeric (not string) money/price fields, `{"detail": string}` error shape, versionless `/api/...` paths.
- Documented error cases (404 unknown ticker, 503 provider unavailable, 422 insufficient history) are actually implemented, not just described.

### Testing (Testing.md)
- Coverage config (`pyproject.toml`/`.coveragerc` `fail_under = 90`, `vite.config.ts` thresholds) hasn't been quietly loosened or removed.
- Migration files remain the only backend exclusion from the coverage gate — check no new blanket `omit` entries have crept in to dodge coverage rather than earn it.

## If a Mismatch Is Found

Classify each finding as one of:
- **Code diverges from doc, unintentionally** — a bug/oversight; fix the code.
- **Code diverges from doc, deliberately** — a reasoned architectural change was made but the doc wasn't updated; update `docs/Architecture.md` or the relevant sub-doc in the same change.
- **Doc is ambiguous or silent** on the case in question — flag it as a gap to resolve with the user, don't guess and don't let the code and doc drift further apart.

## Output

Report findings grouped by doc section (Backend/Frontend/API/Testing/cross-cutting), each with: what the doc says, what the code does, and which of the three classifications above applies. Don't report "looks fine" without walking the checklist explicitly.
