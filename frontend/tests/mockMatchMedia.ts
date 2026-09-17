import { vi } from 'vitest'

/**
 * The single definition of jsdom's missing `window.matchMedia` mock shape,
 * shared so the default (desktop) install in setup.ts and any per-test
 * narrow-width override (e.g. AppShell.test.tsx) can't drift out of sync
 * with each other.
 */
function createMatchMediaMock(query: string, matches: boolean): MediaQueryList {
  return {
    matches,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  } as unknown as MediaQueryList
}

/**
 * Installs `window.matchMedia` for the first time, only if jsdom (or a
 * prior call) hasn't already provided one. Used once, globally, by
 * tests/setup.ts to default every test to a "no match" (desktop) layout.
 */
export function installDefaultMatchMedia(matches = false): void {
  if (!window.matchMedia) {
    window.matchMedia = (query: string) => createMatchMediaMock(query, matches)
  }
}

/**
 * Overrides `window.matchMedia` for the current test only, via
 * `vi.spyOn` (so it composes with the module-level `vi.restoreAllMocks()`
 * every such test already runs in its own `afterEach`). Use this — not a
 * second hand-rolled mock object — whenever a test needs to force MUI's
 * `useMediaQuery` down a specific matches/doesn't-match branch (e.g.
 * AppShell's narrow-width nav).
 */
export function mockMatchMedia(matches: boolean): void {
  vi.spyOn(window, 'matchMedia').mockImplementation((query: string) =>
    createMatchMediaMock(query, matches),
  )
}
