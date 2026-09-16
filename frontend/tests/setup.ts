import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './mocks/server'

// Fail fast on any request that isn't explicitly mocked, so a missing MSW
// handler shows up as a test failure rather than a silent real network call.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

// jsdom doesn't implement window.matchMedia. MUI's useMediaQuery (used by
// AppShell for its responsive nav — see components/layout/AppShell.tsx)
// calls it on every render, so it needs to exist even in tests that don't
// care about responsive behavior. Default to "no match" (desktop layout);
// a test that needs the narrow-width branch overrides this with its own
// vi.spyOn(window, 'matchMedia', ...).
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList
}
