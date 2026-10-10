import path from 'node:path'

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
//
// Extracted into this standalone module (rather than left inline in
// `eslint.config.js`, where every prior fix to this predicate lived) so a
// vitest table test (`no-restricted-src-import.test.ts`, same directory) can
// import and exercise it directly -- see
// `frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups-followups`'s
// `decisions` entry for why: five rounds of fixes to this one predicate
// (directory allowlist -> default-deny regex -> path-traversal normalize fix
// -> bare-utils-barrel false positive -> bare-package false positive -> a
// root-absolute-specifier regression introduced by that last fix) had each
// been verified only by writing a throwaway probe file, running it through
// `yarn eslint`, and deleting it before commit -- nothing in the repo could
// catch a regression in any of the cases already found. Deliberately kept as
// plain JS with JSDoc types (matching `eslint.config.js`'s own pre-extraction
// style) rather than converted to TypeScript: ESLint's flat-config loader
// transpiles the *entry* config file on the fly when it's named
// `eslint.config.ts`, but does not extend that transpilation to a module the
// entry file merely imports, so a sibling `.ts` file here would fail to load
// under plain Node ESM when `eslint.config.js` imports it directly (verified
// empirically: `yarn lint` with this file renamed to `.ts` throws a syntax
// error at the type-annotation tokens before any rule runs).
export const BLOCKED_SRC_VALUE_IMPORT = /(^|\/)src\/(?!utils(?:\/|$))/

/**
 * Whether a static import/export AST node is entirely type-only (mirrors
 * `no-restricted-imports`'s own `isTypeOnlyImport`/`isTypeOnlyExport`
 * helpers): either the declaration itself is `import type`/`export type`,
 * or every individual specifier carries an inline `type` modifier.
 * @param {import('estree').Node} node ImportDeclaration, ExportNamedDeclaration, or ExportAllDeclaration
 * @returns {boolean}
 */
export function isTypeOnlyDeclaration(node) {
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
 *
 * Only a specifier that could plausibly resolve against *this* project's
 * `src/` tree is even considered: a *relative* specifier (one starting with
 * `.`, e.g. `./x` or `../x`) or a *root-absolute* one (starting with `/`,
 * e.g. `/src/pages/x` -- Vite's own dev-server resolver does resolve a
 * leading-`/` specifier against the project root, confirmed via a throwaway
 * `server.pluginContainer.resolveId('/src/utils/format')` probe during
 * `frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups-followups`'s
 * review of this rule). A bare npm package specifier (`my-package/src/foo`,
 * `@scope/pkg/src/foo`) never starts with `.` or `/` per Node/bundler module
 * resolution semantics, so checking the raw source's leading character
 * before normalizing rules those out up front, rather than letting
 * `BLOCKED_SRC_VALUE_IMPORT`'s `(^|/)src\/` anchor match a literal `src/`
 * segment that happens to appear inside an unrelated package name (a false
 * positive the six-directory glob-allowlist version of this rule didn't
 * have, introduced when that allowlist was replaced by this default-deny
 * regex -- see
 * `frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups`'s
 * `decisions` entry). PR #417 fixed that false positive by requiring a
 * leading `.`, but that also exempted a root-absolute specifier that main's
 * pre-#417 rule *did* flag -- this function now admits both leading shapes
 * instead of only `.`, closing that regression while still exempting bare
 * and `@scoped` package specifiers (neither of which starts with `.` or
 * `/`). A leading `~` (a webpack/some-bundler-specific alias convention) is
 * deliberately left unhandled: nothing in this project's actual Vite/
 * Playwright toolchain was verified to resolve it against `src/`, unlike the
 * `/`-rooted case above, so treating it as blocked would be speculative
 * rather than evidence-based.
 *
 * The check is against the *raw* (pre-normalize) source specifically:
 * normalizing a single-dot-relative specifier like `./src/foo` strips the
 * leading `./` (`path.posix.normalize('./src/foo') === 'src/foo'`), which
 * would make it indistinguishable from a bare package specifier if the
 * leading-character check ran after normalization instead of before. A `..`
 * traversal specifier (`../../src/utils/../api/homework`) still starts with
 * `.`, and a root-absolute one (`/src/utils/../api/homework`) still starts
 * with `/`, so both still reach the normalize-then-test step below
 * unaffected.
 * @param {string} rawSource the literal import source, before normalization
 * @returns {boolean}
 */
export function isBlockedSrcSource(rawSource) {
  if (!rawSource.startsWith('.') && !rawSource.startsWith('/')) return false
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
export const noRestrictedSrcImportRule = {
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
