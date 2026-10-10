import { Linter } from 'eslint'
import tseslint from 'typescript-eslint'
import { describe, expect, it } from 'vitest'

import eslintConfig from '../eslint.config.js'
import { isBlockedSrcSource, noRestrictedSrcImportRule } from './no-restricted-src-import.js'

// This is the persisted test the `e2e-import-guard/no-restricted-src-import`
// rule has never had -- every edge case below was previously found (and
// re-found, when a later fix regressed an earlier one) only by writing a
// throwaway probe file, running it through `yarn eslint`, and deleting it
// before commit. See
// `frontend-daily-homework-history-followups-followups-followups-followups-followups-followups-followups-followups`'s
// `decisions` entry for the full rationale. Anyone changing
// `isBlockedSrcSource`/`BLOCKED_SRC_VALUE_IMPORT`
// (`eslint-rules/no-restricted-src-import.js`) should add a row to the table
// below rather than hand-probing again.
describe('isBlockedSrcSource', () => {
  const cases: Array<[label: string, source: string, blocked: boolean]> = [
    // Bare / scoped npm package specifiers -- never start with `.` or `/`,
    // so a literal `src/` segment inside the package name must not trip the
    // gate (PR #417's fix; the regression it introduced is covered below).
    ['bare package specifier containing a literal src/ segment', 'my-package/src/foo', false],
    ['@scoped package specifier containing a literal src/ segment', '@scope/pkg/src/foo', false],

    // Root-absolute specifiers -- Vite's dev-server resolver resolves a
    // leading-`/` specifier against the project root (verified via
    // `server.pluginContainer.resolveId`), so these must be treated the same
    // as a relative specifier, not exempted the way a bare package
    // specifier is. This is the regression PR #417 introduced and this
    // task's item 1 fixes.
    ['root-absolute non-utils src/ import (pages)', '/src/pages/Something', true],
    ['root-absolute non-utils src/ import (api)', '/src/api/x', true],
    ['root-absolute src/utils/ import', '/src/utils/format', false],

    // Relative specifiers into blocked directories.
    ['relative src/features import', '../../src/features/x', true],
    ['relative src/hooks import', '../../src/hooks/useX', true],
    ['relative src/api import', '../../src/api/y', true],

    // Path traversal that resolves (post-normalize) into a blocked
    // directory despite the raw string containing `src/utils/`.
    ['relative src/utils/.. path-traversal into src/api', '../../src/utils/../api/homework', true],

    // Relative specifiers into src/utils/ (the one allowed value-import
    // path), including the barrel-import and nested-file shapes.
    ['relative src/utils/ file import', '../../src/utils/format', false],
    ['relative nested src/utils/ file import', '../../src/utils/sub/thing', false],
    ['relative bare src/utils barrel import (no trailing slash)', '../../src/utils', false],
  ]

  it.each(cases)('%s -> %s', (_label, source, blocked) => {
    expect(isBlockedSrcSource(source)).toBe(blocked)
  })
})

// A predicate test alone can't see the one failure mode that matters just as
// much: the predicate being correct while the rule itself is no longer
// registered against `tests/e2e/**/*.ts`, or registered at a severity other
// than 'error'. These tests exercise the *actual* flat config array
// `eslint.config.js` exports (not a hand-rewritten copy of it) through
// ESLint's own `Linter`, so a change that silently drops or detunes the
// wiring -- not just the matching logic -- fails here too.
describe('e2e-import-guard/no-restricted-src-import wiring', () => {
  const e2eConfigEntry = eslintConfig.find(
    (entry): entry is { files: string[]; plugins: Record<string, unknown>; rules: Record<string, unknown> } =>
      Array.isArray(entry.files) && entry.files.includes('tests/e2e/**/*.ts'),
  )

  it('is present in the flat config array eslint.config.js exports', () => {
    expect(e2eConfigEntry).toBeDefined()
  })

  it('registers exactly the extracted rule object, at "error" severity', () => {
    const plugin = e2eConfigEntry?.plugins['e2e-import-guard'] as { rules: Record<string, unknown> } | undefined
    expect(plugin?.rules['no-restricted-src-import']).toBe(noRestrictedSrcImportRule)
    expect(e2eConfigEntry?.rules['e2e-import-guard/no-restricted-src-import']).toBe('error')
  })

  function lintAsE2eSpec(code: string) {
    const linter = new Linter()
    return linter.verify(
      code,
      [
        {
          files: e2eConfigEntry?.files,
          plugins: e2eConfigEntry?.plugins,
          rules: e2eConfigEntry?.rules,
          languageOptions: { ecmaVersion: 2023, sourceType: 'module', parser: tseslint.parser },
        },
      ],
      { filename: 'tests/e2e/example.spec.ts' },
    )
  }

  it('reports a blocked static value import when linted end-to-end through the real config entry', () => {
    const messages = lintAsE2eSpec("import { Something } from '../../src/pages/Something'\n")
    expect(messages).toHaveLength(1)
    expect(messages[0].ruleId).toBe('e2e-import-guard/no-restricted-src-import')
  })

  it('reports a blocked root-absolute value import end-to-end (item 1 regression check)', () => {
    const messages = lintAsE2eSpec("import { Something } from '/src/pages/Something'\n")
    expect(messages).toHaveLength(1)
    expect(messages[0].ruleId).toBe('e2e-import-guard/no-restricted-src-import')
  })

  it('reports a blocked dynamic import() end-to-end', () => {
    const messages = lintAsE2eSpec("async function load() {\n  await import('../../src/pages/Something')\n}\n")
    expect(messages).toHaveLength(1)
    expect(messages[0].ruleId).toBe('e2e-import-guard/no-restricted-src-import')
  })

  it('does not report an allowed src/utils/ value import end-to-end', () => {
    const messages = lintAsE2eSpec("import { formatDate } from '../../src/utils/format'\n")
    expect(messages).toHaveLength(0)
  })

  it('does not report a type-only import from a blocked directory end-to-end', () => {
    const messages = lintAsE2eSpec("import type { X } from '../../src/pages/Something'\n")
    expect(messages).toHaveLength(0)
  })

  it('does not report a template-literal-sourced dynamic import (documented residual gap)', () => {
    const messages = lintAsE2eSpec(
      "async function load(name: string) {\n  await import(`../../src/${name}`)\n}\n",
    )
    expect(messages).toHaveLength(0)
  })

  it('does not report a variable-sourced dynamic import (documented residual gap)', () => {
    const messages = lintAsE2eSpec('async function load(p: string) {\n  await import(p)\n}\n')
    expect(messages).toHaveLength(0)
  })
})
