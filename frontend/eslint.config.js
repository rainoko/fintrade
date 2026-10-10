import js from '@eslint/js'
import eslintConfigPrettier from 'eslint-config-prettier'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import storybook from 'eslint-plugin-storybook'
import globals from 'globals'
import tseslint from 'typescript-eslint'

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
    // followups-followups-followups' decisions entry covers the two gaps this version
    // closes relative to the first one): a type import is allowed from anywhere under
    // `src/` (erased at compile time, so it can't carry a runtime/DOM dependency
    // regardless of which file it comes from), but a *value* import from anywhere
    // under `src/` other than `src/utils/` (the one path the convention's worked
    // example pulls a real import from) is flagged, as both a static import
    // declaration and a dynamic `import()` expression. This is a default-deny over
    // all of `src/`, not a directory allowlist, so a future `src/hooks/` or
    // `src/contexts/` is covered automatically without updating this file. It still
    // can't express "pure" itself (e.g. it won't catch a memoizing or
    // transitively-impure helper placed under `utils/`), so it's a backstop for the
    // common case, not a substitute for review.
    files: ['tests/e2e/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              // A default-deny `regex` pattern (not the `group` glob form): a
              // static value import whose source path contains a `src/`
              // segment not immediately followed by `utils/` is blocked,
              // everything else under `src/` is allowed. This supersedes an
              // earlier six-item directory *allowlist* (components/features/
              // pages/api/theme/entry points) that silently passed a value
              // import from any src/ subdirectory NOT on that list -- most
              // notably a future src/hooks/ or src/contexts/ (neither exists
              // today). The obvious default-deny glob, `group: ['**/src/**',
              // '!**/src/utils/**']`, was tried and empirically disproven
              // (verified against the `ignore` package directly): its
              // gitignore-style negation can't re-include a path already
              // excluded by a broader pattern. A raw regex sidesteps that --
              // it's matched with plain JS RegExp#test, not gitignore
              // semantics, so a negative lookahead works as expected.
              regex: '(^|/)src/(?!utils/)',
              allowTypeImports: true,
              message:
                'An e2e spec may import a type from anywhere in src/, or a pure utility from src/utils/, but not a component/hook/context/page/API-client/theme value import -- see docs/architecture/Testing.md’s "Importing from src/ in an e2e spec" section.',
            },
          ],
        },
      ],
      // no-restricted-imports only visits static ImportDeclaration/export
      // nodes -- it has no ImportExpression visitor, so a dynamic
      // `await import('../../src/components/...')` bypasses it entirely.
      // This no-restricted-syntax rule closes that gap by matching the same
      // blocked-path shape against a dynamic import's literal source.
      // allowTypeImports has no equivalent here because a dynamic
      // `import()` is always a value expression -- a type-only reference
      // to a module (e.g. `typeof import('./mod')` inside a type position)
      // parses to a distinct TSImportType node, not ImportExpression, so it
      // can never match this selector.
      'no-restricted-syntax': [
        'error',
        {
          selector: 'ImportExpression > Literal[value=/(^|\\/)src\\/(?!utils\\/)/]',
          message:
            'An e2e spec may not dynamically import from src/ outside src/utils/ -- see docs/architecture/Testing.md’s "Importing from src/ in an e2e spec" section.',
        },
      ],
    },
  },
)
