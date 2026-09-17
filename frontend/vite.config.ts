/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The frontend's API client (src/api/client.ts) defaults to a same-origin
  // base URL ('' — every request path already includes the '/api' prefix),
  // meant for a deployment behind a single reverse proxy. In dev, "same
  // origin" is the Vite dev server's own port, which has no knowledge of
  // '/api/*' routes — proxy those through to the backend so `vite`/`npm run
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
