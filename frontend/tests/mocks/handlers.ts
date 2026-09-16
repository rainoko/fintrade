import type { HttpHandler } from 'msw'

// Handlers mirroring docs/architecture/API.md, including every error case
// listed in API.md's "Error Cases to Cover in Tests" section (see
// Frontend.md's Testing Notes). Populated as each endpoint's frontend client
// lands (frontend-api-client and the feature tasks that follow it) — empty
// on this scaffold since there is no API client to mock yet.
export const handlers: HttpHandler[] = []
