import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetWatchlistStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import AddTickerForm from './AddTickerForm'

describe('AddTickerForm', () => {
  beforeEach(() => {
    resetWatchlistStore()
  })

  it('disables the Add button until a ticker is entered', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AddTickerForm />)

    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()

    await user.type(screen.getByLabelText('Add ticker to watchlist'), 'TSLA')
    expect(screen.getByRole('button', { name: 'Add' })).toBeEnabled()
  })

  it('does not submit for a whitespace-only ticker', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AddTickerForm />)

    await user.type(screen.getByLabelText('Add ticker to watchlist'), '   ')
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  })

  it('submits the trimmed, uppercased ticker and clears the field on success', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AddTickerForm />)

    await user.type(screen.getByLabelText('Add ticker to watchlist'), '  tsla  ')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() =>
      expect(screen.getByLabelText('Add ticker to watchlist')).toHaveValue(''),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces an ApiError via common/ErrorState when the add request fails', async () => {
    server.use(
      http.post('/api/watchlist', () =>
        HttpResponse.json({ detail: 'Something went wrong.' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<AddTickerForm />)

    await user.type(screen.getByLabelText('Add ticker to watchlist'), 'TSLA')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong.')).toBeInTheDocument()
  })
})
