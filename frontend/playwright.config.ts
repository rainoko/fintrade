import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const backendDir = path.resolve(__dirname, '../backend')

const BACKEND_PORT = 8000
const FRONTEND_PORT = 5173

/**
 * End-to-end test suite (frontend-e2e-tests task): real, running backend +
 * frontend, driven with a real browser — a separate, un-mocked category from
 * the vitest/pytest suites under Testing.md's 90%-coverage gate, which is
 * unaffected by this file (see `yarn test:e2e` in package.json and the
 * root Makefile's `e2e` target, neither wired into `make test`/`yarn test`).
 *
 * Decision (frontend-e2e-tests task, recorded in docs/tasks/frontend-e2e-tests.json):
 * Playwright Test, matching the Playwright MCP tooling already used for ad hoc manual
 * walkthroughs elsewhere in this project's pipeline (task-qa-reviewer, pr-reviewer) —
 * see that task's `decisions` entry for the alternatives considered (Cypress, WebdriverIO)
 * and why they were rejected.
 *
 * Both dev processes below are started fresh by Playwright itself
 * (`reuseExistingServer: false`, unconditionally, not just outside CI) rather than
 * optionally reusing an already-running `make dev` — a stack a developer started by hand
 * wouldn't have `FINTRADE_DATA_PROVIDER_MODE=fixture`/the dedicated e2e database below set,
 * so reusing it would silently fall back to live yfinance/Stooq calls and the developer's
 * real portfolio data, defeating the whole point of this fixture setup. The tradeoff: this
 * suite can't run at the same time as a manually-started `make dev` on the same ports (8000/
 * 5173) — see README.md's e2e section.
 */
export default defineConfig({
  testDir: './tests/e2e',
  // Portfolio specs add/delete real rows through the running backend and assert on the
  // resulting state — safer to serialize the whole suite than to make every spec file
  // reason about concurrent mutations of the one shared e2e database. This is a small,
  // deliberately non-exhaustive suite (golden-path coverage per flow, not a combinatorial
  // sweep), so the speed cost of serial execution is minor.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // Deletes any e2e database left over from a previous run before starting, so every
      // run begins from the same empty-portfolio state (see docs/tasks/frontend-e2e-tests.json's
      // `decisions` entry) rather than accumulating positions across runs.
      command:
        'rm -f e2e.db && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ' +
        BACKEND_PORT,
      cwd: backendDir,
      env: {
        FINTRADE_DATABASE_URL: 'sqlite:///./e2e.db',
        // Selects app.data.fixture_provider.FixtureDataProvider (app/api/dependencies.py)
        // instead of the real yfinance/Stooq-backed provider — see this task's `decisions`
        // entry for why the e2e suite needs deterministic, offline market data.
        FINTRADE_DATA_PROVIDER_MODE: 'fixture',
      },
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // No env overrides needed: vite.config.ts's dev-server proxy already forwards '/api'
      // to http://localhost:8000, matching the backend webServer above.
      command: `yarn dev --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      cwd: __dirname,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
