import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { getIbkrStatus } from './ibkr'

describe('api/ibkr', () => {
  it('getIbkrStatus returns the default disabled state, matching the real backend default', async () => {
    const status = await getIbkrStatus()

    expect(status.state).toBe('disabled')
    expect(status.detail).not.toBeNull()
  })

  it('getIbkrStatus surfaces the available state, with a null detail', async () => {
    server.use(
      http.get('/api/ibkr/status', () =>
        HttpResponse.json({ state: 'available', detail: null }),
      ),
    )

    const status = await getIbkrStatus()

    expect(status).toEqual({ state: 'available', detail: null })
  })

  it('getIbkrStatus rejects with an ApiError on a transport-level failure', async () => {
    server.use(http.get('/api/ibkr/status', () => HttpResponse.error()))

    await expect(getIbkrStatus()).rejects.toMatchObject({ status: 0 })
  })
})
