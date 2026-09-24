import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../tests/mocks/server'
import { ApiError, request } from './client'

describe('api/client', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('resolves with the parsed JSON body on a 200 response', async () => {
    server.use(http.get('/test/ok', () => HttpResponse.json({ hello: 'world' })))

    await expect(request<{ hello: string }>('/test/ok')).resolves.toEqual({
      hello: 'world',
    })
  })

  it('sends a JSON body and resolves undefined on a 204 response (DELETE-style)', async () => {
    let receivedBody: unknown
    server.use(
      http.delete('/test/delete', async ({ request: req }) => {
        receivedBody = await req.text()
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await expect(
      request<void>('/test/delete', { method: 'DELETE' }),
    ).resolves.toBeUndefined()
    // A DELETE with no `body` option sends no request body at all.
    expect(receivedBody).toBe('')
  })

  it('sends a JSON-encoded request body on POST', async () => {
    let receivedBody: unknown
    server.use(
      http.post('/test/create', async ({ request: req }) => {
        receivedBody = await req.json()
        return HttpResponse.json({ ok: true }, { status: 201 })
      }),
    )

    await request('/test/create', { method: 'POST', body: { ticker: 'AAPL' } })

    expect(receivedBody).toEqual({ ticker: 'AAPL' })
  })

  it('maps a 404 with a single ErrorDetail body to ApiError', async () => {
    server.use(
      http.get('/test/not-found', () =>
        HttpResponse.json({ detail: 'Unknown ticker' }, { status: 404 }),
      ),
    )

    const error = await request('/test/not-found').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, detail: 'Unknown ticker' })
  })

  it('maps a 422 with a per-field HTTPValidationError body to ApiError, joining messages', async () => {
    server.use(
      http.get('/test/validation-error', () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ['query', 'range'],
                msg: 'String should match pattern',
                type: 'string_pattern_mismatch',
              },
              {
                loc: ['query', 'interval'],
                msg: 'Input should be daily or weekly',
                type: 'enum',
              },
            ],
          },
          { status: 422 },
        ),
      ),
    )

    const error = await request('/test/validation-error').catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).detail).toBe(
      'String should match pattern; Input should be daily or weekly',
    )
  })

  it('maps a 503 with a single ErrorDetail body to ApiError', async () => {
    server.use(
      http.get('/test/unavailable', () =>
        HttpResponse.json(
          { detail: 'Market data provider unavailable' },
          { status: 503 },
        ),
      ),
    )

    const error = await request('/test/unavailable').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 503,
      detail: 'Market data provider unavailable',
    })
  })

  it('falls back to a generic message when the error body has no usable detail', async () => {
    server.use(
      http.get('/test/empty-error-body', () => new HttpResponse(null, { status: 500 })),
    )

    const error = await request('/test/empty-error-body').catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(500)
    expect((error as ApiError).detail).toBe('Request failed with status 500')
  })

  it('falls back to a generic message when the error body is not valid JSON', async () => {
    server.use(
      http.get(
        '/test/non-json-error-body',
        () => new HttpResponse('<html>not json</html>', { status: 502 }),
      ),
    )

    const error = await request('/test/non-json-error-body').catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(502)
    expect((error as ApiError).detail).toBe('Request failed with status 502')
  })

  it('falls back to a generic message when detail is neither a string nor an array', async () => {
    server.use(
      http.get('/test/weird-detail-shape', () =>
        HttpResponse.json({ detail: 42 }, { status: 400 }),
      ),
    )

    const error = await request('/test/weird-detail-shape').catch(
      (caught: unknown) => caught,
    )

    expect((error as ApiError).detail).toBe('Request failed with status 400')
  })

  it('falls back to a generic message when detail is an empty validation-error list', async () => {
    server.use(
      http.get('/test/empty-detail-list', () =>
        HttpResponse.json({ detail: [] }, { status: 422 }),
      ),
    )

    const error = await request('/test/empty-detail-list').catch(
      (caught: unknown) => caught,
    )

    expect((error as ApiError).detail).toBe('Request failed with status 422')
  })

  it('parses a numeric Retry-After header into ApiError.retryAfterSeconds', async () => {
    server.use(
      http.post('/test/rate-limited', () =>
        HttpResponse.json(
          { detail: 'Rate limited' },
          { status: 429, headers: { 'Retry-After': '3' } },
        ),
      ),
    )

    const error = await request('/test/rate-limited', { method: 'POST' }).catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(429)
    expect((error as ApiError).retryAfterSeconds).toBe(3)
  })

  it('leaves retryAfterSeconds null when the response has no Retry-After header', async () => {
    server.use(
      http.get('/test/not-found', () =>
        HttpResponse.json({ detail: 'Unknown ticker' }, { status: 404 }),
      ),
    )

    const error = await request('/test/not-found').catch((caught: unknown) => caught)

    expect((error as ApiError).retryAfterSeconds).toBeNull()
  })

  it('leaves retryAfterSeconds null when Retry-After is an HTTP-date rather than seconds', async () => {
    server.use(
      http.post('/test/rate-limited-date', () =>
        HttpResponse.json(
          { detail: 'Rate limited' },
          { status: 429, headers: { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' } },
        ),
      ),
    )

    const error = await request('/test/rate-limited-date', { method: 'POST' }).catch(
      (caught: unknown) => caught,
    )

    expect((error as ApiError).retryAfterSeconds).toBeNull()
  })

  it('maps a network-level failure (fetch throws) to a status-0 ApiError', async () => {
    server.use(http.get('/test/network-error', () => HttpResponse.error()))

    const error = await request('/test/network-error').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(0)
    expect((error as ApiError).detail).toMatch(/unable to reach the api/i)
  })

  it('prefixes every request with VITE_API_BASE_URL when it is set', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test')
    server.use(
      http.get('https://api.example.test/test/base-url', () =>
        HttpResponse.json({ ok: true }),
      ),
    )

    await expect(request('/test/base-url')).resolves.toEqual({ ok: true })
  })
})
