# Testing Strategy

**Hard requirement: 90% test coverage on both backend and frontend**, enforced in CI — a build that drops below 90% fails, not just warns.

## Backend (Python)

- **Tooling:** `pytest` + `pytest-cov`, coverage measured via `coverage.py`.
- **Config** (`pyproject.toml` or `.coveragerc`):
  ```toml
  [tool.coverage.run]
  branch = true
  source = ["app"]
  omit = ["app/db/migrations/*"]

  [tool.coverage.report]
  fail_under = 90
  show_missing = true
  ```
- **CI command:** `pytest --cov=app --cov-report=term-missing --cov-fail-under=90`
- **What's excluded from the gate:** Alembic migration files only. Everything else — including API routers and DB models — counts.
- **No live network calls in any test.** Market data providers (`yfinance`, `stooq`) are always mocked (`pytest-mock` / fixture-recorded responses). This is both a reliability requirement (tests can't fail because Yahoo rate-limited CI) and a coverage requirement (network flakiness would make the gate unreliable).
- **Test types:**
  - *Unit* (`tests/unit/`): indicators against hand-computed reference values; signal engine against explicit Screen 1/2/3/Impulse combinations; risk engine (2%/6% rules, protective stop) against known position/equity scenarios.
  - *Integration* (`tests/integration/`): FastAPI `TestClient` hitting real routers with mocked data-provider layer underneath, asserting full response shapes match [API.md](API.md).

## Frontend (TypeScript)

- **Tooling:** `vitest` with its built-in `v8` coverage provider, `@testing-library/react` for component tests, `msw` to mock all API calls.
- **Config** (`vite.config.ts`):
  ```ts
  test: {
    coverage: {
      provider: 'v8',
      thresholds: {
        lines: 90,
        branches: 90,
        functions: 90,
        statements: 90,
      },
      // Without `include`, the v8 provider only instruments files a test
      // actually imports, so an entirely untested file is silently
      // excluded from both the numerator and denominator instead of
      // counting as 0% — mirroring the backend's `source = ["app"]` above,
      // which counts every file regardless of whether a test imports it.
      include: ['src/**/*.{ts,tsx}'],
    },
  }
  ```
- **CI command:** `vitest run --coverage` (fails the run automatically if thresholds aren't met, given the config above).
- **No test hits a real network endpoint.** All API interaction in tests goes through MSW handlers mirroring [API.md](API.md)'s contract, including error responses (404/422/503).
- **Test types:**
  - Component tests for chart wrappers, signal badges, portfolio tables — happy path + empty/error/loading states.
  - Hook tests for `useStockAnalysis`/`usePortfolio` (React Query hooks) against mocked responses.
  - Boundary-value tests for confidence-band thresholds (0%, 100%, and the Low/Medium/High edges from Analyse.md §6).

## CI Enforcement

Both coverage gates run on every PR. A PR that drops either side below 90% fails CI regardless of what else it changes — coverage is a merge blocker, not a follow-up task. (Exact CI platform/workflow file is a separate decision, not covered by this doc.)

## What 90% Coverage Does *Not* Guarantee

Coverage measures lines/branches executed, not correctness of the Elder methodology itself. A test that calls the MACD function and asserts only "it returns a number" contributes to coverage without validating anything meaningful. The reference-value requirement above (Backend, unit tests) exists specifically to prevent coverage from being satisfied by shallow assertions — reviewers should treat a PR that hits 90% via trivial assertions as not actually meeting this bar in spirit, even if the CI gate is green.
