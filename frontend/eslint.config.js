import js from '@eslint/js'
import eslintConfigPrettier from 'eslint-config-prettier'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import storybook from 'eslint-plugin-storybook'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// The `e2e-import-guard/no-restricted-src-import` rule (and the
// `isBlockedSrcSource`/`BLOCKED_SRC_VALUE_IMPORT` predicate it's built on)
// lives in its own module specifically so it can be imported and exercised
// directly by a persisted vitest test
// (`eslint-rules/no-restricted-src-import.test.ts`) -- see that module's own
// comments for the rule's full history and
// `frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups-followups`'s
// `decisions` entry for why this extraction happened now. Anyone changing
// this rule's matching logic should extend that test's table rather than
// hand-probing with a throwaway file the way every prior round did.
import { noRestrictedSrcImportRule } from './eslint-rules/no-restricted-src-import.js'

export default tseslint.config(
  { ignores: ['dist', 'storybook-static', 'coverage', '.yarn'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
  eslintConfigPrettier,
  storybook.configs['flat/recommended'],
  {
    // Mechanical approximation of the `src/`-import convention documented in
    // docs/architecture/Testing.md's "Importing from src/ in an e2e spec" section
    // (frontend-daily-homework-history-followups-followups-followups-followups'
    // decisions entry has the full rationale for why this is a deliberately partial
    // check, not a complete one; frontend-daily-homework-history-followups-followups-
    // followups-followups-followups' and ...-followups-followups-followups-followups-
    // followups-followups' decisions entries cover the gaps closed since then): a
    // type import is allowed from anywhere under `src/` (erased at compile time, so
    // it can't carry a runtime/DOM dependency regardless of which file it comes
    // from), but a *value* import from anywhere under `src/` other than `src/utils/`
    // (the one path the convention's worked example pulls a real import from) is
    // flagged, as both a static import declaration and a dynamic `import()`
    // expression, with the source normalized first so a `src/utils/..`
    // path-traversal segment can't reach a still-blocked directory unflagged. This
    // is a default-deny over all of `src/`, not a directory allowlist, so a future
    // `src/hooks/` or `src/contexts/` is covered automatically without updating this
    // file. It still can't express "pure" itself (e.g. it won't catch a memoizing or
    // transitively-impure helper placed under `utils/`), so it's a backstop for the
    // common case, not a substitute for review.
    files: ['tests/e2e/**/*.ts'],
    plugins: {
      'e2e-import-guard': { rules: { 'no-restricted-src-import': noRestrictedSrcImportRule } },
    },
    rules: {
      'e2e-import-guard/no-restricted-src-import': 'error',
    },
  },
)
