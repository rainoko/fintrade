import { setupServer } from 'msw/node'
import { handlers } from './handlers'

// Node-side MSW server used by the vitest setup file so that no test, on
// either side of the app, ever makes a real network call (see
// docs/architecture/Testing.md).
export const server = setupServer(...handlers)
