import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
// Also brings vitest/config's ambient module augmentation of Vite's `UserConfig.test` into
// scope (what the removed `/// <reference types="vitest/config" />` used to do on its own),
// so pulling in `configDefaults` as a real import made that triple-slash reference redundant
// -- and eslint's @typescript-eslint/triple-slash-reference rule flags exactly that.
import { configDefaults } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The frontend's API client (src/api/client.ts) defaults to a same-origin
  // base URL ('' — every request path already includes the '/api' prefix),
  // meant for a deployment behind a single reverse proxy. In dev, "same
  // origin" is the Vite dev server's own port, which has no knowledge of
  // '/api/*' routes — proxy those through to the backend so `vite`/`yarn
  // dev` works out of the box without requiring VITE_API_BASE_URL to be set.
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: true,
    // tests/e2e/*.spec.ts are Playwright specs (playwright.config.ts, `yarn test:e2e`) --
    // a real, un-mocked, separate test category (frontend-e2e-tests task) that must never
    // run under vitest (its `test`/`expect` come from '@playwright/test', not vitest) or
    // count toward this suite's 90% coverage gate (docs/architecture/Testing.md).
    exclude: [...configDefaults.exclude, 'tests/e2e/**'],
    // Root-caused the flaky `Error: Test timed out in 5000ms` failures tracked on
    // backend-cftc-cot-data-followups-followups-followups and
    // frontend-trade-journal-followup-review-followups-followups (both hitting
    // interaction-heavy MUI dialog tests in AddPositionDialog.test.tsx /
    // FollowUpReviewDialog.test.tsx): with no `maxWorkers` cap, vitest's default
    // `pool: 'forks'` spawns one forked process per test file, up to
    // `os.availableParallelism() - 1` (84 files' worth of workers observed on a
    // high-core-count host) -- reproduced 5/5 times locally on a 24-core devcontainer
    // under default settings, and again at `--maxWorkers=23` (mimicking that same
    // uncapped default) during backend-cftc-cot-data-followups-followups-followups's
    // own PR review. That many concurrent jsdom+MUI worker processes contend for real CPU
    // time, which stretches the wall-clock duration of multi-step `userEvent`-driven
    // tests (real, non-fake timers under `@testing-library/user-event`) past the
    // hardcoded 5000ms default test timeout under scheduling pressure (vs.
    // `pool: 'vmThreads'`, which shares one jsdom environment per worker and would
    // address the same root cause with even less overhead, but breaks MSW's fetch
    // interception in this suite -- `ReferenceError: TransformStream is not defined`
    // -- because a `vm` context's globals lack the Web Streams API that
    // `pool: 'forks'`/`'threads'` get for free from Node's own process/worker
    // globals). Capping at 4 workers reproduced 0/7 failures across repeated
    // full-suite runs of the committed config (corrected here from an earlier,
    // inconsistent "0/4" in this same comment -- see
    // backend-cftc-cot-data-followups-followups-followups-followups's `decisions`
    // entry for the reconciliation).
    //
    // A later bisection of *fixed absolute* worker counts (6/8/10/12, 5 full-suite
    // runs each, 20/20 clean) found 12 workers safe and much faster (~30s vs ~54s)
    // -- but only on the 24-core devcontainer that bisection ran on. pr-reviewer
    // caught that a fixed absolute count doesn't scale down to a lower-core host:
    // vitest's `maxWorkers` (once explicitly set) is used verbatim with zero
    // clamping to the host's actual core count -- the `availableParallelism() - 1`
    // fallback only applies when `maxWorkers` is left unset. Empirically, the
    // committed `maxWorkers: 12` deterministically reproduced the original timeout
    // flake (15/841 tests, 3/3 runs) under a `taskset -c 0-1` 2-core restriction,
    // while `maxWorkers: 4` passed cleanly (2/2 runs) under the same restriction.
    // This repo has no CI workflow configured and no pinned CPU count
    // (.devcontainer/devcontainer.json), so a fixed count tuned to one 24-core host
    // isn't safe to assume elsewhere.
    //
    // Switched to a percentage instead of a fixed count: vitest resolves a string
    // `maxWorkers` via `getWorkersCountByPercentage()` at run time, off
    // `os.availableParallelism()` on whatever host actually runs the suite --
    // '50%' matches the bisected-safe value of 12 workers on this 24-core
    // devcontainer (round(0.5 * 24) = 12) while also degrading proportionally on a
    // smaller host instead of holding the absolute count fixed. Re-ran the exact
    // `taskset -c 0-1` 2-core repro from pr-reviewer's finding with `maxWorkers:
    // '50%'` committed: resolves to 1 worker on a 2-core host
    // (round(0.5*2)=1), and the full suite passed cleanly 3/3 runs, no timeouts.
    // Also re-ran the unrestricted 24-core host normally (841/841 passed, ~30s,
    // matching the fixed-12 wall-clock's ~29-31s range above) to confirm no
    // regression there. Revisit if per-file overhead changes enough for 50% to
    // need retuning.
    maxWorkers: '50%',
    coverage: {
      provider: 'v8',
      // 'text' is given explicit options (not just the bare 'text' string)
      // to force `skipFull: false`. Vitest's std-env `isAgent` detection
      // (true in this dev container, since Claude Code sets CLAUDECODE)
      // otherwise silently defaults the text reporter to `skipFull: true`
      // for agent-run sessions, which hides every 100%-covered file/dir —
      // including the root "All files" summary row itself once the whole
      // suite reaches 100%, leaving a header/footer with zero rows between
      // them. That defeats the point of a by-eye per-file table when
      // investigating a future coverage regression, so this project always
      // wants the full table regardless of who's running the command.
      reporter: [['text', { skipFull: false }], 'html', 'lcov'],
      // Matches docs/architecture/Testing.md exactly: the frontend coverage
      // gate is 90% on all four dimensions, enforced by vitest itself (a
      // `vitest run --coverage` that drops below any threshold exits non-zero).
      thresholds: {
        lines: 90,
        branches: 90,
        functions: 90,
        statements: 90,
      },
      // By default vitest's v8 provider only instruments files a test
      // actually imports, so an entirely untested file is silently
      // excluded from both the numerator and denominator of the report
      // instead of counting as 0%. `include` (this version of vitest
      // removed the older `coverage.all` boolean in favor of this) makes
      // every matching file under src/ count, mirroring the backend's
      // `source = ["app"]` config which counts every file regardless of
      // whether a test imports it.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/api/types.ts', // generated from backend/openapi.json, never hand-edited
        'src/main.tsx', // app bootstrap, not meaningfully unit-testable
        '.storybook/**',
        '**/*.stories.tsx',
        'tests/**',
      ],
    },
  },
})
