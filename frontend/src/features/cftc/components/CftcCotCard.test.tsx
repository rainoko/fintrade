import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import CftcCotCard from './CftcCotCard'

describe('CftcCotCard', () => {
  it('shows a loading state, then the 5 fixed markets with their net positions and COT Index', async () => {
    renderWithProviders(<CftcCotCard />)

    expect(screen.getByText('Loading CFTC Commitments of Traders data...')).toBeInTheDocument()

    const table = await screen.findByRole('table', { name: 'CFTC Commitments of Traders' })

    expect(within(table).getByText('EURO FX - CHICAGO MERCANTILE EXCHANGE')).toBeInTheDocument()
    expect(within(table).getByText('JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE')).toBeInTheDocument()
    expect(within(table).getByText('WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE')).toBeInTheDocument()
    expect(within(table).getByText('GOLD - COMMODITY EXCHANGE INC.')).toBeInTheDocument()
    expect(within(table).getByText('UST BOND - CHICAGO BOARD OF TRADE')).toBeInTheDocument()

    // EUR commercial net (30000) + its COT Index (72.5 -> rounded to 73 for display).
    expect(within(table).getByText('30,000')).toBeInTheDocument()
    expect(within(table).getByText('COT Index: 73')).toBeInTheDocument()
  })

  it('renders "--" for every COT Index on a market with fewer than 2 weeks of history (bonds, in the fixed fixture), not a crash or a misleading 0', async () => {
    renderWithProviders(<CftcCotCard />)

    const table = await screen.findByRole('table', { name: 'CFTC Commitments of Traders' })
    const bondsRow = within(table).getByText('UST BOND - CHICAGO BOARD OF TRADE').closest('tr')
    expect(bondsRow).not.toBeNull()

    const nullCotIndexCells = within(bondsRow as HTMLElement).getAllByText('COT Index: —')
    expect(nullCotIndexCells).toHaveLength(3)
  })

  it('surfaces the MetricHelp explanation of Elder ch. 37\'s follow-commercials/fade-small-speculators framing', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CftcCotCard />)

    await screen.findByRole('table', { name: 'CFTC Commitments of Traders' })

    await user.click(screen.getByRole('button', { name: 'Commitments of Traders (COT) help' }))

    expect(
      await screen.findByText(/follow commercials.*fade small speculators/i),
    ).toBeInTheDocument()
    // Dynamic valueInterpretation: the fixture's most/least bullish-relative-
    // to-own-range commercial markets (oil: 12.0 lowest, eur: 72.5 highest).
    expect(screen.getByText(/most bullish.*EURO FX/i)).toBeInTheDocument()
  })

  it('surfaces a 503 ApiError via common/ErrorState when the gateway/cache-miss fetch fails', async () => {
    server.use(
      http.get('/api/cftc/cot', () =>
        HttpResponse.json(
          { detail: "The CFTC's data endpoint is currently unavailable." },
          { status: 503 },
        ),
      ),
    )

    renderWithProviders(<CftcCotCard />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    expect(
      screen.getByText("The CFTC's data endpoint is currently unavailable."),
    ).toBeInTheDocument()
  })

  it('surfaces a network-level ApiError via common/ErrorState', async () => {
    server.use(http.get('/api/cftc/cot', () => HttpResponse.error()))

    renderWithProviders(<CftcCotCard />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })
})
