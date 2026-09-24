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
    // entry for the reconciliation). A later bisection (same task) tried 6/8/10/12
    // workers, 5 full-suite runs each (20/20 clean, no reproduction), with wall-clock
    // dropping from ~54s at 4 workers to ~30s at 12 -- 12 was adopted as the new cap:
    // still well under the 23-worker count that reproduces the original flake on this
    // 24-core host, while recovering most of the runtime the original conservative
    // cap gave up. Revisit if the suite grows enough, or moves to a much
    // lower-core-count CI host, for this tradeoff to shift again.
    maxWorkers: 12,
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
