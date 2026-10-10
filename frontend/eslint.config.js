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
    // check, not a complete one): a type import is allowed from anywhere under
    // `src/` (erased at compile time, so it can't carry a runtime/DOM dependency
    // in regardless of which file it comes from), but a *value* import from a
    // directory that is almost certainly not a pure, side-effect-free utility —
    // components, feature modules, pages, the API client layer, the theme, or an
    // app entry point — is flagged. `src/utils/**` (the one path the convention's
    // worked example pulls a real import from) is deliberately left out of the
    // blocked group entirely, so a legitimate pure-utility import from there is
    // never flagged. This can't express "pure" itself (e.g. it won't catch a
    // memoizing or transitively-impure helper placed under `utils/`), so it's a
    // backstop for the common case, not a substitute for review.
    files: ['tests/e2e/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '**/src/components/**',
                '**/src/features/**',
                '**/src/pages/**',
                '**/src/api/**',
                '**/src/theme/**',
                '**/src/App*',
                '**/src/main*',
                '**/src/index.css',
              ],
              allowTypeImports: true,
              message:
                'An e2e spec may import a type from anywhere in src/, or a pure utility from src/utils/, but not a component/hook/context/page/API-client/theme value import -- see docs/architecture/Testing.md’s "Importing from src/ in an e2e spec" section.',
            },
          ],
        },
      ],
    },
  },
)
