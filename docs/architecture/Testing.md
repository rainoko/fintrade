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
keep. `frontend/eslint-rules/no-restricted-src-import.js` defines a local
`e2e-import-guard/no-restricted-src-import` rule (wired into `tests/e2e/**/*.ts` from
`frontend/eslint.config.js`) that mechanically catches this — a non-type **value** import whose
source is a *relative* (starts with `.`, e.g. `./x` or `../x`) or *root-absolute* (starts with
`/`, e.g. `/src/pages/x` — Vite's dev-server resolver does resolve a leading-`/` specifier
against the project root) specifier — a bare npm package specifier like `my-package/src/foo` or
`@scope/pkg/src/foo` never starts with `.` or `/` per Node/bundler module resolution semantics,
so it's ruled out before the `src/` test ever runs, regardless of whether the package name
happens to contain a literal `src/` segment — and, *after resolving any `..` path-traversal
segment* (via `path.posix.normalize()`), contains a `src/` segment not immediately followed by
`utils/` or exactly `utils` at the end of the path (covering both a file under `src/utils/` and
a bare `src/utils` barrel import, and both the relative and root-absolute specifier shapes) is
flagged, while a type import from anywhere in `src/`, any value import that normalizes to
`src/utils/...` (relative or root-absolute), and any bare package specifier are left alone. This
is a default-deny over
all of `src/`, not a directory allowlist — an earlier version of this rule listed six specific
blocked directories (`src/components/`, `src/features/`, `src/pages/`, `src/api/`,
`src/theme/`, app entry points) and silently passed a value import from any `src/`
subdirectory not on that list, most notably a `src/hooks/` or `src/contexts/` that didn't
exist in the tree yet; the regex blocks everything under `src/` except `src/utils/` by
construction rather than by name. The rule normalizes the source before testing it
specifically because matching the *raw* string — which two prior built-in-rule-based versions
of this check both did, one using ESLint core's `no-restricted-imports` `regex` option for
static imports and a paired `no-restricted-syntax` esquery selector for dynamic ones — let a
`src/utils/..` path-traversal segment bypass both: `import { x } from
'../../src/utils/../api/homework'` resolves at bundle/type-check time to `src/api/homework`
(a blocked directory), but a regex matched against the raw string only ever saw the literal
substring `src/utils/` immediately after the `src/` anchor and treated it as the exempt case,
for both a static import and a dynamic `await import('../../src/utils/../features/...')`
(verified empirically against real probe files run through `yarn eslint`, both before and
after the fix). Normalizing first — collapsing `src/utils/..` down to nothing before the
regex ever runs — makes the resolved path visible, the same way a bundler or `tsc` would see
it, closing that bypass for both the static (`ImportDeclaration`/`ExportNamedDeclaration`/
`ExportAllDeclaration`) and dynamic (`ImportExpression`) cases; a single custom rule now
covers both from one definition of the blocked-path regex, rather than hand-duplicating it
across two different built-in rules' option syntaxes (a real drift risk the two-rule version
had, since a future change to the exempt directory applied to only one of the two would have
silently reintroduced a static/dynamic mismatch with nothing to flag it). A dynamic import is
only checked when its source is a plain string literal; one built from a template literal or
a variable (e.g. `` import(`../../src/${name}`) `` or `import(path)`) parses to a
`TemplateLiteral`/`Identifier` node rather than a `Literal`, so it still bypasses the rule
(verified empirically: a template-literal-sourced dynamic import of a blocked component
produced zero eslint errors). This residual gap was left open deliberately rather than chased
further — a dynamically-constructed module path is already a conspicuous, easy-to-spot-in-
review pattern for a black-box e2e spec to contain at all, and expressing "the literal source
*or* any string this expression could evaluate to" is a data-flow question no lint rule
selector can answer without executing the code. The relative-or-root-absolute-specifier gate
above (requiring the *raw*, pre-normalize source to start with `.` or `/`) was added after the
blocked-path regex's `(^|/)src\/` anchor turned out to also match a bare npm package specifier
containing a literal `src/` segment anywhere in it (e.g. `import { x } from
'my-package/src/foo'`) — a false positive the earlier six-directory glob-allowlist version of
this rule never had, since it only ever matched specific `**/src/<dir>/**` globs, never a bare
`src/` segment inside an unrelated package name. That fix originally required the raw source to
start with `.` specifically (ruling out a root-absolute `/src/...` specifier along with the bare
package case it was meant to rule out — a regression from main's pre-fix behavior, caught and
fixed in the round that also added this rule's persisted test); it now requires `.` *or* `/`,
since a root-absolute specifier is no more a bare package specifier than a relative one is. The
check runs against the raw source rather than the normalized one specifically because
`path.posix.normalize()` strips a single-dot relative prefix (`'./src/foo'` normalizes to
`'src/foo'`), which would make a single-dot-relative specifier indistinguishable from a bare
package specifier if the leading-character check ran after normalization instead of before; a
`..`-traversal specifier still starts with `.`, and a root-absolute one still starts with `/`,
so both are unaffected and still reach the normalize-then-test step (verified empirically:
`'../../src/utils/../api/homework'` is still flagged, both as a static import and as the
dynamic `import()` equivalent). The rule is still a backstop for the obvious
violations, not a substitute for review: it can't tell a genuinely pure `src/utils/` helper
from one that's quietly grown a transitive dependency on something impure, so that one
borderline case still needs a human judgment call (see
`frontend-daily-homework-history-followups-followups-followups-followups`'s `decisions` entry
for the full reasoning on what is and isn't mechanizable here,
`frontend-daily-homework-history-followups-followups-followups-followups-followups`'s for how
the directory-allowlist and dynamic-import gaps were closed, and
`frontend-daily-homework-history-followups-followups-followups-followups-followups-followups`'s
for the path-traversal bypass and the bare-barrel false positive / hand-duplicated-pattern
fixes, and
`frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups`'s
for the bare-package-specifier false positive fix described above, and
`frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups-followups`'s
for the root-absolute-specifier regression that bare-package fix introduced, and for how this
rule finally got a persisted test). That last round also closed the structural gap behind every
fix above: five rounds in a row each found a different edge case in the same small matching
predicate, and every one of them had been verified only by writing a throwaway probe file, running
it through `yarn eslint`, and deleting it before commit — nothing in the repo could have caught a
regression in any previously-fixed case. The rule (and the `isBlockedSrcSource`/
`BLOCKED_SRC_VALUE_IMPORT` predicate it's built on) now lives in its own module,
`frontend/eslint-rules/no-restricted-src-import.js`, imported by `frontend/eslint.config.js`
rather than defined inline, specifically so `frontend/eslint-rules/no-restricted-src-import.test.ts`
can exercise it directly as a persisted vitest table test covering every case enumerated above,
plus an end-to-end check (via ESLint's own `Linter`, fed the actual flat config array
`eslint.config.js` exports) that the rule is still registered against `tests/e2e/**/*.ts` at
`'error'` severity — a predicate-only test can't see the rule being silently unregistered or
detuned, which is exactly the failure mode that check exists for. Anyone changing this rule's
matching logic should add a row to that test's table instead of hand-probing with a throwaway
file. `frontend/eslint-rules/` sits outside both `tsconfig.app.json`'s (`src`, `tests`,
`.storybook`) and `tsconfig.node.json`'s (originally just `vite.config.ts`,
`playwright.config.ts`) `include` arrays, so by default `yarn tsc -b --noEmit` never saw either
file in it — a gap `frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups-followups-followups`
closed concretely (not just by moving config lines) by adding `eslint-rules` to
`tsconfig.node.json`'s `include` (the build/tooling-code project, not the app-code one) and
turning on `allowJs` there (needed only to resolve the `.js` import specifiers
`no-restricted-src-import.test.ts` and `eslint.config.js` use to reach each other — without it,
TS can't see either module's exported shape and falls back to `any`); `checkJs` was deliberately
left off, so the rule module's own internal, loosely-AST-typed JSDoc code isn't itself
type-checked, but every real type annotation in the test file now is, against the real exported
types of both modules — proved by injecting `isBlockedSrcSource(42)` (a `number` where the
function's signature expects a `string`) and confirming `yarn tsc -b --noEmit` failed on it
(`TS2345`), then reverting and confirming clean again. A genuinely test-only need
shared across specs, or between a spec and
the mocked suites' fixtures — not a copy or thin wrapper of app logic, e.g. `isoDateWeeksAgo`
— still belongs in a `tests/`-local module (`tests/dateFixtures.ts`), not under `src/`.

## What 90% Coverage Does *Not* Guarantee

Coverage measures lines/branches executed, not correctness of the Elder methodology itself. A test that calls the MACD function and asserts only "it returns a number" contributes to coverage without validating anything meaningful. The reference-value requirement above (Backend, unit tests) exists specifically to prevent coverage from being satisfied by shallow assertions — reviewers should treat a PR that hits 90% via trivial assertions as not actually meeting this bar in spirit, even if the CI gate is green.
