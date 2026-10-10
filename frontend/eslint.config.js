import path from 'node:path'

import js from '@eslint/js'
import eslintConfigPrettier from 'eslint-config-prettier'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import storybook from 'eslint-plugin-storybook'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// Single source of truth for the "blocked src/ value import" shape the
// `e2e-import-guard/no-restricted-src-import` rule below enforces: a `src/`
// path segment not immediately followed by `utils/` (with a trailing slash)
// or exactly `utils` at the end of the string (a future `src/utils/index.ts`
// barrel import, e.g. `../../src/utils` with no trailing file/slash -- the
// `(?:\/|$)` alternation exempts that exact-barrel case too, closing a false
// positive the previous `(?!utils/)` lookahead had). Matched against the
// import source string *after* `path.posix.normalize()` collapses any `..`
// segment -- matching the raw string let `src/utils/../api/homework` sneak
// past the old regex (it only ever saw the literal substring `src/utils/`
// right after the anchor, never resolving what the `..` actually points at);
// normalizing first makes that `../api/homework` visible before the test
// runs, the same way a bundler/type-checker would resolve the path.
const BLOCKED_SRC_VALUE_IMPORT = /(^|\/)src\/(?!utils(?:\/|$))/

/**
 * Whether a static import/export AST node is entirely type-only (mirrors
 * `no-restricted-imports`'s own `isTypeOnlyImport`/`isTypeOnlyExport`
 * helpers): either the declaration itself is `import type`/`export type`,
 * or every individual specifier carries an inline `type` modifier.
 * @param {import('estree').Node} node ImportDeclaration, ExportNamedDeclaration, or ExportAllDeclaration
 * @returns {boolean}
 */
function isTypeOnlyDeclaration(node) {
  if (node.type === 'ImportDeclaration') {
    return (
      node.importKind === 'type' ||
      (node.specifiers.length > 0 && node.specifiers.every((specifier) => specifier.importKind === 'type'))
    )
  }
  return (
    node.exportKind === 'type' ||
    (node.specifiers?.length > 0 && node.specifiers.every((specifier) => specifier.exportKind === 'type'))
  )
}

/**
 * Whether an import source string, once `..` segments are resolved, points
 * somewhere under `src/` other than `src/utils/`.
 * @param {string} rawSource the literal import source, before normalization
 * @returns {boolean}
 */
function isBlockedSrcSource(rawSource) {
  return BLOCKED_SRC_VALUE_IMPORT.test(path.posix.normalize(rawSource))
}

/**
 * A local, single-rule replacement for the earlier pairing of ESLint core's
 * `no-restricted-imports` (regex option) + `no-restricted-syntax` (an
 * esquery selector over `ImportExpression`). Both of those matched the raw,
 * un-normalized import-source string, which a `src/utils/..` path-traversal
 * segment could exploit to reach a still-blocked directory
 * (`../../src/utils/../api/homework` resolves to `src/api/homework` but the
 * old regex only ever saw the literal substring `src/utils/` right after the
 * anchor) -- see
 * `frontend-daily-homework-history-followups-followups-followups-followups-followups`'s
 * `decisions` entry for the full history of what this rule supersedes and
 * why a custom rule, rather than another built-in-core option, was needed
 * once the gap turned out to require normalizing the path before testing it
 * (something neither `no-restricted-imports`'s `regex` option nor
 * `no-restricted-syntax`'s esquery selector can do -- both only ever see the
 * raw, unresolved source string). Handling both the static
 * (`ImportDeclaration`/`ExportNamedDeclaration`/`ExportAllDeclaration`) and
 * dynamic (`ImportExpression`) cases in one rule also means the blocked-path
 * pattern (`BLOCKED_SRC_VALUE_IMPORT` above) is defined exactly once, instead
 * of being hand-duplicated across two different rule option syntaxes/
 * escapings the way the two rules it replaces were.
 */
const noRestrictedSrcImportRule = {
  meta: {
    type: 'problem',
    docs: {
      description:
        "Disallow a static or dynamic value import from src/ outside src/utils/ in an e2e spec, including through a `..` path-traversal segment.",
    },
    schema: [],
    messages: {
      restrictedStatic:
        'An e2e spec may import a type from anywhere in src/, or a pure utility from src/utils/, but not a component/hook/context/page/API-client/theme value import -- see docs/architecture/Testing.md’s "Importing from src/ in an e2e spec" section.',
      restrictedDynamic:
        'An e2e spec may not dynamically import from src/ outside src/utils/ -- see docs/architecture/Testing.md’s "Importing from src/ in an e2e spec" section.',
    },
  },
  create(context) {
    function checkStatic(node) {
      if (!node.source || isTypeOnlyDeclaration(node)) return
      if (isBlockedSrcSource(node.source.value)) {
        context.report({ node: node.source, messageId: 'restrictedStatic' })
      }
    }

    return {
      ImportDeclaration: checkStatic,
      ExportNamedDeclaration: checkStatic,
      ExportAllDeclaration: checkStatic,
      ImportExpression(node) {
        // Only a plain string literal source can be checked statically; a
        // template literal or variable (e.g. `` import(`../../src/${name}`) ``
        // or `import(path)`) parses to a `TemplateLiteral`/`Identifier` node
        // instead of `Literal` and is left alone -- a deliberate residual
        // gap, documented in docs/architecture/Testing.md, since answering
        // "the literal source or any string this expression could evaluate
        // to" is a data-flow question no static AST check can resolve.
        if (node.source.type !== 'Literal' || typeof node.source.value !== 'string') return
        if (isBlockedSrcSource(node.source.value)) {
          context.report({ node: node.source, messageId: 'restrictedDynamic' })
        }
      },
    }
  },
}

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
