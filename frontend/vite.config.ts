/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      // Matches docs/architecture/Testing.md exactly: the frontend coverage
      // gate is 90% on all four dimensions, enforced by vitest itself (a
      // `vitest run --coverage` that drops below any threshold exits non-zero).
      thresholds: {
        lines: 90,
        branches: 90,
        functions: 90,
        statements: 90,
      },
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
