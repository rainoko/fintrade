# fintrade frontend

TypeScript/React/Vite dashboard for the fintrade app. See
[docs/architecture/Frontend.md](../docs/architecture/Frontend.md) for the
module layout, state-management rules, and chart/indicator display notes,
and [docs/architecture/Testing.md](../docs/architecture/Testing.md) for the
coverage gate.

## Scripts

| Script                            | Purpose                                                                                                       |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `npm run dev`                     | Vite dev server                                                                                               |
| `npm run build`                   | Type-check (`tsc -b`) + production build                                                                      |
| `npm run preview`                 | Preview a production build locally                                                                            |
| `npm run lint`                    | ESLint                                                                                                        |
| `npm run format` / `format:check` | Prettier write / check                                                                                        |
| `npm run test`                    | Run the vitest suite once                                                                                     |
| `npm run test:coverage`           | Run the suite with coverage, enforcing the 90% lines/branches/functions/statements gate from `vite.config.ts` |
| `npm run storybook`               | Storybook dev server for `src/components/common/*`                                                            |
| `npm run build-storybook`         | Static Storybook build                                                                                        |

## Testing

`vitest` + `@testing-library/react`, with `msw` (`tests/mocks/`) mocking
every backend call — no test hits a real network endpoint. Coverage
thresholds are enforced by `vitest run --coverage` itself (see
`vite.config.ts`'s `test.coverage.thresholds`); a PR that drops any of
lines/branches/functions/statements below 90% fails that command with a
non-zero exit code, the same as CI would treat it as a merge blocker.
