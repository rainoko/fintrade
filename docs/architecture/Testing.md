# Testing Strategy

**Hard requirement: 90% test coverage on both backend and frontend**, enforced in CI — a build that drops below 90% fails, not just warns.

This coverage gate governs the backend (pytest) and frontend (vitest) suites described in
this document, both of which mock every external boundary (market data providers,
the API layer). It does **not** apply to the separate end-to-end suite described in
[End-to-end (Playwright)](#end-to-end-playwright) below, which deliberately does the opposite
— a real, running, un-mocked stack — and is never run as part of `make test`/`yarn test` or
counted toward either coverage number.

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

## End-to-end (Playwright)

`frontend/tests/e2e/` (`frontend/playwright.config.ts`, run via `make e2e` /
`yarn test:e2e` — see [README.md](../../README.md#end-to-end-tests)) is a distinct test
category from everything above: real browser (Chromium via Playwright), real running
backend + frontend processes, no mocking at any layer. It exists to catch the class of bug
the mocked suites structurally can't — a real HTTP round-trip through Vite's dev-server
proxy, an actual DOM render of MUI components together, a real SQLite-backed request —
without which two suites that separately mock the same contract (MSW on the frontend,
`TestClient`-level stubs on the backend) could each stay green while still disagreeing with
each other in production.

**Deterministic, offline data:** the backend is started with
`FINTRADE_DATA_PROVIDER_MODE=fixture` (`app.config.Settings.data_provider_mode`,
`app.api.dependencies.get_data_provider`), which swaps in
`app.data.fixture_provider.FixtureDataProvider` — an in-process, no-network `DataProvider`
serving a fixed set of synthetic tickers with deterministic (seeded, not wall-clock-random)
OHLCV series — instead of the real yfinance/Stooq-backed provider. This keeps the suite
fast, offline, and immune to live market data changing the Elder Triple Screen outcome
between runs. The suite also gets its own SQLite database (`backend/e2e.db`, wiped before
every run by the `webServer` command in `playwright.config.ts`), so portfolio add/delete
specs always start from a known state rather than accumulating rows across runs.

**Coverage, deliberately not exhaustive at the Elder-methodology level:** specs assert
structurally (a signal badge renders one of BUY/SELL/HOLD, a confidence score renders
0–100, a price chart has candles) rather than pinning an exact expected signal/confidence
value for the fixture data — that precision is what the backend's hand-derived-reference-
value unit tests already cover (see `verify-elder-signal`). Golden-path flows covered:
dashboard, stock search + analysis (signal/confidence/screens/indicators/chart, plus an
unknown-ticker 404), portfolio (view/add/delete a position, the risk panel, and recording a
two-months-later follow-up review on a trade due for one), and app-shell navigation between
all three pages.

**Importing from `src/` in an e2e spec:** every spec here is otherwise a pure black-box
consumer of the running app through the browser — Playwright locators driving real DOM
interactions, not component imports — which is the whole point of this suite (see above:
two mocked suites that separately stub the same contract could each stay green while still
disagreeing with each other in production, and an e2e spec that reached past the browser
into app internals would reopen that same gap). A spec may still import a **type** or a
**pure, side-effect-free utility/formatting function** directly from `src/` (the one
`tsconfig.app.json`, via its project-reference build, already covers both `src` and
`tests` in its `include`, so nothing extra needs wiring for either static type-checking or
the Playwright runner's own transpilation -- there is no separate Playwright-specific
tsconfig file; Playwright's test runner doesn't type-check specs at all, it transpiles them
via esbuild without checking types, so all static type-checking of `tests/e2e/*.spec.ts`
happens solely through the project's ordinary `yarn tsc -b --noEmit` step) when doing so
lets an assertion compare against
the exact value or format the app itself produces, rather than a hand-copied
reimplementation that can silently drift from it. `tests/e2e/daily-homework.spec.ts`
imports the `DailyHomeworkOut` type (`src/api/homework.ts`, via `import type`, so it's
erased at compile time with zero runtime coupling) and the `formatDate` helper
(`src/utils/format.ts`, a pure function of its string argument — no React, no DOM, no app
state) for exactly this reason: a prior tests-local reimplementation of `formatDate`'s
`toLocaleDateString` options had drifted out of sync with the real helper
(`frontend-daily-homework-history-followups-followups`'s fix), which is precisely the
failure mode importing the real helper prevents from recurring. Importing a React
component, hook, context, or any module with side effects/DOM/app-runtime dependencies is
**not allowed** — that would let a spec exercise app logic directly instead of through the
browser the way a real user does, which is the black-box boundary this suite exists to
keep. `frontend/eslint.config.js` has a `no-restricted-imports` override scoped to
`tests/e2e/**/*.ts` that mechanically catches the common case of this — a non-type import
from `src/components/`, `src/features/`, `src/pages/`, `src/api/`, `src/theme/`, or an app
entry point is flagged, while a type import from anywhere in `src/` and any import (type or
value) from `src/utils/` are left alone — but it's a backstop for the obvious violations,
not a substitute for review: it can't tell a genuinely pure `src/utils/` helper from one
that's quietly grown a transitive dependency on something impure, so a borderline case still
needs a human judgment call (see
`frontend-daily-homework-history-followups-followups-followups-followups`'s `decisions`
entry for the full reasoning on what is and isn't mechanizable here). A genuinely test-only
need shared across specs, or between a spec and the mocked
suites' fixtures — not a copy or thin wrapper of app logic, e.g. `isoDateWeeksAgo` — still
belongs in a `tests/`-local module (`tests/dateFixtures.ts`), not under `src/`.

## What 90% Coverage Does *Not* Guarantee

Coverage measures lines/branches executed, not correctness of the Elder methodology itself. A test that calls the MACD function and asserts only "it returns a number" contributes to coverage without validating anything meaningful. The reference-value requirement above (Backend, unit tests) exists specifically to prevent coverage from being satisfied by shallow assertions — reviewers should treat a PR that hits 90% via trivial assertions as not actually meeting this bar in spirit, even if the CI gate is green.
