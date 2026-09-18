---
name: add-frontend-feature
description: Add or change a frontend page, component, or hook (React/TypeScript/MUI) — decide common/ vs feature-specific placement, wire a TanStack Query hook, keep Storybook and tests aligned with docs/architecture/Frontend.md. Use when asked to add a new frontend page/component/hook, or to change how one fetches or displays data.
---

# Add Frontend Feature

Frontend work follows `docs/architecture/Frontend.md` in full — its module layout (§3), state rules (§2: TanStack Query only, Redux/MobX/Zustand/Recoil/Jotai are never allowed), Storybook requirement (§4), and the chart/indicator constraint (§5). Read it before starting if this is the first time touching `frontend/src/`.

## Steps

1. **Check `docs/architecture/API.md` and `docs/architecture/Frontend.md` first.** Confirm the endpoint(s) this feature needs already exist in the committed `backend/openapi.json` snapshot and are documented in API.md. If they aren't, that's an `add-api-endpoint` task, not this one — don't invent a shape here.

2. **Decide component placement: `components/common/` vs `features/<domain>/components/`.** This is not optional and not a formality — for every new component, explicitly ask whether it references a domain concept (a position, a ticker, a signal, a confidence score) or is purely presentational, taking only generic props. Domain-agnostic → `components/common/`. Anything that knows what a "position" is → `features/<domain>/components/`. Before building a new component, also check whether something close enough already exists under `components/common/` or in another `features/*/components/` folder — a near-duplicate should be consolidated into one shared `common/` component instead of copy-pasted, unless there's a genuine reason the two need to diverge (record that reason as a `decisions` entry if it's not obvious). `pr-reviewer` checks this placement explicitly at review time regardless of which skill governed the task (see its own instructions) — get it right up front rather than relying on review to catch it.

3. **Data layer: one hook per API concern.** Add/update a hook under `features/<domain>/hooks/` wrapping exactly one `useQuery` or `useMutation` call from `@tanstack/react-query`, built on the typed functions in `api/stocks.ts`/`api/portfolio.ts` (never a raw `fetch()` inside a component). A mutation invalidates every query it affects (e.g. adding/deleting a position invalidates both the portfolio and portfolio-risk queries) — an omitted invalidation is a stale-UI bug, not a style nit.

4. **Component implementation.** One component per file, matching the file name, default-exported. Pages (`pages/*.tsx`) stay thin: composition of hooks + components + layout, no fetch calls, no business logic — if a page file is doing real work, that work belongs in a `features/<domain>/` hook or component instead (Frontend.md §3).

5. **`components/common/` components need a colocated test *and* a Storybook story before they're done** (Frontend.md §4) — covering the component's meaningful variants/states, not just a default render. A `common/` component with a test but no story (or vice versa) is incomplete, not just missing polish.

6. **Testing.** Every component/hook that touches API data is tested against MSW-mocked responses (`tests/mocks/handlers.ts`), covering every documented error case from API.md's "Error Cases to Cover in Tests" that applies to the endpoint(s) this feature uses — not just the happy path. Boundary-value tests (0%, 100%, confidence-band edges per Analyse.md §6) apply to anything displaying a percentage or confidence value.

7. **No client-state library, ever.** If you find yourself reaching for Redux/MobX/Zustand/Recoil/Jotai to solve a state problem, that's a signal to stop and re-read Frontend.md §2 — the answer is TanStack Query (server state) or React Context (rare, genuinely cross-cutting UI state), not a new dependency.

8. **Record any judgment call.** Non-obvious placement decisions (step 2), a state-location choice that isn't purely mechanical, or any other genuine ambiguity Frontend.md/API.md doesn't fully pin down — append an entry to this task's `decisions` array in its task JSON (`decision` + `rationale`, including what you rejected and why). A checklist item phrased as "decide X" is not satisfied by code that implicitly picks a behavior with no record.

9. **Run coverage before finishing** — use the `check-coverage`/`test-90` skills, or `yarn test:coverage` directly, to confirm the new code doesn't drop the frontend below the 90% gate (`docs/architecture/Testing.md`).

## Common Mistakes to Avoid

- Building a component under `features/<domain>/components/` that turns out to take only generic props and reference no domain concept — it belongs in `components/common/` instead, and should have been recognized as such at step 2, not caught later in review.
- Building a second near-identical component in a different feature instead of promoting the first one to `components/common/` — this is the specific kind of duplication `pr-reviewer` is required to check for.
- Adding a `components/common/` component without a Storybook story, or a story that only covers the default state.
- A raw `fetch()`/`axios` call inside a component or page instead of going through a `features/<domain>/hooks/` hook.
- A mutation that doesn't invalidate every query its change actually affects, leaving stale data on screen after a successful write.
- Reaching for a state-management library "just for this one case" — see step 7.
- A page file that fetches data or contains business logic directly, instead of composing hooks/components.
