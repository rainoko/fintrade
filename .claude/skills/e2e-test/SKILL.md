---
name: e2e-test
description: Run the frontend's real-browser Playwright end-to-end suite (frontend/tests/e2e/*.spec.ts) against a freshly-started backend+frontend stack and report pass/fail per spec, with enough detail (trace/screenshot/HTML report) to debug a failure. Use when asked to run the e2e suite, before finishing a UI-facing change, or as the "run the persisted e2e suite" step of a PR review or task QA pass.
---

# E2E Test

`frontend/tests/e2e/` (Playwright Test, `frontend/playwright.config.ts`, added by the
`frontend-e2e-tests` task) is a real-browser, real-backend, no-mocking test category —
distinct from and complementary to the vitest/pytest suites `check-coverage` gates, and
distinct from `task-qa-reviewer`/`pr-reviewer`'s own ad hoc Playwright **MCP** browser
walkthrough (an interactive, one-off exploration of a *specific* change, driven tool-call
by tool-call). This skill instead runs the **persisted, versioned spec files** through the
actual Playwright Test **runner** — the same regression suite every contributor and CI run
shares, not a walkthrough scripted fresh each time. See "Relationship to Other
Checks" below for exactly how the two fit together.

This skill only reports; it doesn't fix a failing spec or the app code behind it (that's
ordinary implementation work). It also never loosens what a spec asserts to make it pass.

## Steps

1. **Check prerequisites before running anything:**
   - **Chromium browser binary.** `yarn playwright install chromium` inside `frontend/`
     downloads it if missing (cached at `~/.cache/ms-playwright`, already provisioned in
     this dev container's image — a fresh environment needs this once). Outside the dev
     container, its system-level dependencies also need
     `sudo yarn playwright install-deps chromium` — see README.md's "End-to-end tests"
     section. Don't skip this check and let the run fail opaquely; confirm the binary is
     present first (`ls ~/.cache/ms-playwright` or let `yarn playwright install chromium`
     itself report "already installed").
   - **Ports 8000 and 5173 free.** Playwright's `webServer` config always starts its own
     backend+frontend processes (`reuseExistingServer: false`, unconditionally) rather than
     reusing an already-running `make dev` — a manually-started stack wouldn't have
     `FINTRADE_DATA_PROVIDER_MODE=fixture`/the dedicated e2e database set, so reusing it
     would silently fall back to live market data and whatever portfolio state was already
     there. This means the suite **cannot run at the same time** as a manually-started
     `make dev`/`make backend`/`make frontend` on those same ports — check
     (`ss -ltn | grep -E '8000|5173'` or equivalent) and stop any such process first, or the
     run will fail at the `webServer` startup step, not in a spec itself.
   - **Fixture data provider / offline data.** No manual setup needed here —
     `playwright.config.ts`'s own `webServer` block already sets
     `FINTRADE_DATA_PROVIDER_MODE=fixture` and a dedicated `FINTRADE_DATABASE_URL`
     (`backend/e2e.db`, wiped before every run) for you. If a spec run ever appears to be
     hitting live yfinance/Stooq or an existing dev database instead, that's a regression in
     `playwright.config.ts` itself, not something this skill's runner needs to set — flag it.

2. **Run the suite** from the repo root:
   ```
   make e2e
   ```
   (equivalent to `cd frontend && yarn test:e2e`, i.e. `playwright test` under
   `playwright.config.ts`). This is a single, non-interactive run of every spec in
   `frontend/tests/e2e/*.spec.ts`, serially (`workers: 1`), starting its own backend+frontend
   and tearing them down afterward. Expect roughly 15-30s for the current suite size:
   4 spec files (`dashboard`, `navigation`, `portfolio`, `stock-analysis`) covering the
   dashboard, app-shell navigation, portfolio add/delete/risk-panel, and stock search +
   analysis flows end to end — see `docs/architecture/Testing.md`'s
   "End-to-end (Playwright)" section for exactly what each covers.

   For interactive debugging of a specific failure (not for a routine run/report pass),
   `yarn test:e2e:ui` opens Playwright's UI mode instead.

3. **Report pass/fail per spec file**, not just a single suite-wide verdict — list which
   `.spec.ts` files passed and which failed, with the test name for any failure (Playwright's
   own `list` reporter output already gives you this).

4. **On any failure, use the artifacts Playwright already collects** rather than re-running
   blind:
   - `frontend/playwright-report/` — the HTML report (`use: { trace: 'retain-on-failure',
     screenshot: 'only-on-failure' }` in the config means a trace + screenshot exist for
     every failed test, not just a bare log line).
   - The captured `stdout`/`stderr` of both `webServer` processes (piped per the config) —
     check these first if the failure happened at startup (a server never became healthy)
     rather than inside a spec's assertions; that's a different class of problem (environment/
     port/dependency issue) from a spec genuinely catching a regression.
   - Distinguish a **real regression** (the app's actual behavior changed and a spec's
     assertion is now correct-and-failing) from a **flake/environment issue** (a timing race,
     a port left occupied by a previous run, a missing browser binary) before concluding
     which one you're looking at — don't assume either without checking the evidence above.

5. **Don't weaken a spec to make it pass.** If a spec's assertion is outdated because the
   UI it checks legitimately changed on purpose (e.g. copy, a `data-testid`, a route), fix
   the spec to match the new correct behavior and say so explicitly in your report — don't
   silently loosen an assertion or delete a case to get green, per this project's general
   "don't fake the bar" convention (`test-90`/`check-coverage`'s same principle, applied here
   to e2e specs instead of coverage numbers).

## Relationship to Other Checks

- **`task-qa-reviewer`'s/`pr-reviewer`'s own browser walkthrough** (Playwright **MCP** tool
  calls, driven live) is an exploratory, one-off check of *this specific task/PR's* new or
  changed behavior — it can probe things no persisted spec covers yet (a brand-new page, an
  edge case unique to this change) and reacts to what it actually observes step by step. This
  skill instead re-runs the **existing, versioned** golden-path specs as a fixed regression
  check — cheap, deterministic, and catches "did this change break something *unrelated* to
  what it touched" in a way a walkthrough scoped to the change itself structurally can't. Run
  both for UI-facing work; neither substitutes for the other.
- **`check-coverage`/`static-verify`** govern the mocked vitest/pytest suites and lint/type
  tooling respectively — this suite is deliberately outside the 90% coverage gate (real
  network-free-but-unmocked HTTP round-trips through a real browser aren't what that gate
  measures) and isn't run by `make test`/`yarn test`. Run this skill as an additional,
  separate check, never as a substitute for either of those.
- If a new UI flow is added, the underlying task should also add or extend an e2e spec for
  it (that's implementation work for whichever skill governs the change, e.g.
  `add-frontend-feature` — this skill only runs what already exists, it doesn't decide
  what new coverage a change needs).

## Notes

- No live external network call is made by the suite itself (the fixture data provider is
  in-process and synthetic) — but unlike `check-coverage`'s suites, this one *does* make real
  HTTP calls between its own two local processes (frontend → backend), which is the entire
  point of this test category. That's expected, not a flake to chase down.
- If `frontend/playwright.config.ts`, `frontend/tests/e2e/`, or the `test:e2e`/`e2e` scripts
  (`frontend/package.json`, root `Makefile`) are ever removed or the `FINTRADE_DATA_PROVIDER_
  MODE=fixture` gating is ever weakened to also affect non-e2e code paths, that's a regression
  in its own right (mirrors `static-verify`'s and `architecture-review`'s "missing config is a
  finding, not silently 'nothing to check'" convention) — flag it rather than treating an
  absent suite as a trivial pass.
