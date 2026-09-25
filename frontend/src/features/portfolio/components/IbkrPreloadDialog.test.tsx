import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PositionOut } from '../../../api/portfolio'
import { resetPortfolioStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import IbkrPreloadDialog from './IbkrPreloadDialog'

const AAPL_POSITION: PositionOut = {
  id: 'pos_123',
  ticker: 'AAPL',
  quantity: 100,
  avg_cost_basis: 195.3,
  entry_date: '2026-05-14',
}

function renderDialog(open: boolean, existingPositions: PositionOut[] = [AAPL_POSITION]) {
  return renderWithProviders(
    <IbkrPreloadDialog
      open={open}
      onClose={vi.fn()}
      existingPositions={existingPositions}
    />,
  )
}

describe('IbkrPreloadDialog', () => {
  afterEach(() => {
    resetPortfolioStore()
  })

  it('renders nothing when closed', () => {
    renderDialog(false)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows a loading state, then the non-conflicting and conflicting sections', async () => {
    renderDialog(true)

    expect(screen.getByText('Fetching IBKR positions...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByText('New positions to import (1)')).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('table', { name: 'Non-conflicting IBKR positions' }),
    ).toBeInTheDocument()
    expect(
      within(
        screen.getByRole('table', { name: 'Non-conflicting IBKR positions' }),
      ).getByText('NVDA'),
    ).toBeInTheDocument()

    expect(screen.getByText('Conflicting tickers (1)')).toBeInTheDocument()
    const conflictTable = screen.getByRole('table', {
      name: 'Conflicting IBKR positions',
    })
    expect(within(conflictTable).getByText('AAPL')).toBeInTheDocument()
    expect(within(conflictTable).queryByText('Not found locally')).not.toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Import 1 position' })).toBeInTheDocument()
  })

  it('shows UnavailableState when the preview reports a non-available state', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'gateway_unreachable',
          detail: 'Could not reach the IBKR gateway.',
          positions: null,
        }),
      ),
    )

    renderDialog(true)

    await waitFor(() => expect(screen.getByText('IBKR unavailable')).toBeInTheDocument())
    expect(screen.getByText('Could not reach the IBKR gateway.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Import/ })).not.toBeInTheDocument()
  })

  it('falls back to a generic message when the unavailable state has no detail', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({ state: 'disabled', detail: null, positions: null }),
      ),
    )

    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByText('The IBKR integration is not available right now.'),
      ).toBeInTheDocument(),
    )
  })

  it('falls back to 0 imported when the preload response omits its imported list', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('/api/ibkr/portfolio-preload', () =>
        HttpResponse.json({
          state: 'available',
          detail: null,
          imported: null,
          skipped_conflicting_tickers: ['AAPL'],
        }),
      ),
    )
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Import 1 position' }))

    await waitFor(() =>
      expect(screen.getByText('Imported 0 positions from IBKR.')).toBeInTheDocument(),
    )
  })

  it('surfaces a preview fetch failure via common/ErrorState', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({ detail: 'Account-positions fetch failed.' }, { status: 503 }),
      ),
    )

    renderDialog(true)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('shows a top-level empty state when there are no IBKR positions at all', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({ state: 'available', detail: null, positions: [] }),
      ),
    )

    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByText('No IBKR positions are available to preload right now.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: /^Import/ })).not.toBeInTheDocument()
  })

  it('shows a friendly empty state for the non-conflicting section when everything conflicts', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'available',
          detail: null,
          positions: [
            {
              conid: 1,
              ticker: 'AAPL',
              quantity: 50,
              avg_cost: 150,
              conflicts_with_existing_position: true,
            },
          ],
        }),
      ),
    )

    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByText('No new IBKR positions to import right now.'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText('New positions to import (0)')).toBeInTheDocument()
  })

  it('shows a friendly empty state for the conflicts section when nothing conflicts', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'available',
          detail: null,
          positions: [
            {
              conid: 1,
              ticker: 'NVDA',
              quantity: 10,
              avg_cost: 900,
              conflicts_with_existing_position: false,
            },
          ],
        }),
      ),
    )

    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByText(
          'No conflicts — every fetched IBKR position can be imported directly.',
        ),
      ).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Import 1 position' })).toBeInTheDocument()
  })

  it("renders a conflicting ticker whose local match can't be resolved as 'Not found locally', with no checkbox", async () => {
    // existingPositions deliberately doesn't include AAPL (out of sync with
    // the mock server's own `positions` store, which still has it) --
    // exercises the defensive fallback for a conflicting IBKR ticker this
    // dialog can't resolve a local id for.
    renderDialog(true, [])

    await waitFor(() => expect(screen.getByText('Not found locally')).toBeInTheDocument())
    const conflictTable = screen.getByRole('table', {
      name: 'Conflicting IBKR positions',
    })
    expect(within(conflictTable).queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('increments the import count when a conflicting ticker is selected for deletion', async () => {
    const user = userEvent.setup()
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )

    await user.click(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    )

    expect(screen.getByRole('button', { name: 'Import 2 positions' })).toBeInTheDocument()

    await user.click(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    )

    expect(screen.getByRole('button', { name: 'Import 1 position' })).toBeInTheDocument()
  })

  it('disables Import entirely when there is nothing importable and nothing selected', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'available',
          detail: null,
          positions: [
            {
              conid: 1,
              ticker: 'AAPL',
              quantity: 50,
              avg_cost: 150,
              conflicts_with_existing_position: true,
            },
          ],
        }),
      ),
    )

    renderDialog(true)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Import 0 positions' })).toBeDisabled(),
    )
  })

  it('confirms without selecting any conflict: imports only the non-conflicting NVDA position', async () => {
    const user = userEvent.setup()
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Import 1 position' }))

    await waitFor(() =>
      expect(screen.getByText('Imported 1 position from IBKR.')).toBeInTheDocument(),
    )
    const importedTable = screen.getByRole('table', { name: 'Imported IBKR positions' })
    expect(within(importedTable).getByText('NVDA')).toBeInTheDocument()
    expect(within(importedTable).queryByText('AAPL')).not.toBeInTheDocument()
    expect(screen.getByText(/Still skipped as conflicting:\s*AAPL/)).toBeInTheDocument()
  })

  it('confirms with the AAPL conflict selected: deletes it first, then imports both AAPL and NVDA', async () => {
    const user = userEvent.setup()
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Import 2 positions' }))

    await waitFor(() =>
      expect(screen.getByText('Imported 2 positions from IBKR.')).toBeInTheDocument(),
    )
    const importedTable = screen.getByRole('table', { name: 'Imported IBKR positions' })
    expect(within(importedTable).getByText('AAPL')).toBeInTheDocument()
    expect(within(importedTable).getByText('NVDA')).toBeInTheDocument()
    expect(screen.queryByText(/Still skipped as conflicting/)).not.toBeInTheDocument()
  })

  it('clicking Done on the success screen closes the dialog', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(
      <IbkrPreloadDialog open onClose={onClose} existingPositions={[AAPL_POSITION]} />,
    )

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Import 1 position' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'Done' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('surfaces a preload failure via ErrorState and keeps the review screen open', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('/api/ibkr/portfolio-preload', () =>
        HttpResponse.json({ detail: 'Account-positions fetch failed.' }, { status: 503 }),
      ),
    )
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Import 1 position' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(
      screen.getByText(
        /Any positions already deleted before this failure remain deleted/,
      ),
    ).toBeInTheDocument()
    // Still on the review screen, not the success screen.
    expect(screen.getByRole('button', { name: /^Import/ })).toBeInTheDocument()
  })

  it('surfaces a genuine (non-404) delete failure and never calls the preload endpoint', async () => {
    const user = userEvent.setup()
    let preloadCalled = false
    server.use(
      http.delete('/api/portfolio/positions/:id', () =>
        HttpResponse.json(
          { detail: 'Cannot close: manual override validation failed.' },
          { status: 422 },
        ),
      ),
      http.post('/api/ibkr/portfolio-preload', () => {
        preloadCalled = true
        return HttpResponse.json({
          state: 'available',
          detail: null,
          imported: [],
          skipped_conflicting_tickers: [],
        })
      }),
    )
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Import 2 positions' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(preloadCalled).toBe(false)
  })

  it('treats a 404 from a delete call as already-gone and still proceeds to preload', async () => {
    const user = userEvent.setup()
    server.use(
      http.delete('/api/portfolio/positions/:id', () =>
        HttpResponse.json({ detail: 'Position not found' }, { status: 404 }),
      ),
    )
    renderDialog(true)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Import 2 positions' }))

    // The delete 404 is swallowed, so the mutation still succeeds and reaches
    // the preload call -- since the override above never actually removed
    // AAPL from the shared store, AAPL is (correctly) still reported as
    // conflicting/skipped rather than imported, but the flow completes.
    await waitFor(() =>
      expect(screen.getByText('Imported 1 position from IBKR.')).toBeInTheDocument(),
    )
  })

  it('resets the selection when the dialog is closed and reopened', async () => {
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(
      <IbkrPreloadDialog open onClose={vi.fn()} existingPositions={[AAPL_POSITION]} />,
    )

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    )
    expect(screen.getByRole('button', { name: 'Import 2 positions' })).toBeInTheDocument()

    rerender(
      <IbkrPreloadDialog
        open={false}
        onClose={vi.fn()}
        existingPositions={[AAPL_POSITION]}
      />,
    )
    rerender(
      <IbkrPreloadDialog open onClose={vi.fn()} existingPositions={[AAPL_POSITION]} />,
    )

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 265598)',
      }),
    ).not.toBeChecked()
  })

  // frontend-ibkr-portfolio-preload-followups #1: two fetched IBKR positions
  // that resolve to the same ticker, neither conflicting locally, both land
  // in `nonConflicting` -- but the backend's own within-fetch dedup only
  // actually imports the first. The promised count must reflect that.
  it('counts a within-fetch duplicate ticker toward the import count only once', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'available',
          detail: null,
          positions: [
            {
              conid: 501,
              ticker: 'TSLA',
              quantity: 5,
              avg_cost: 200,
              conflicts_with_existing_position: false,
            },
            {
              conid: 502,
              ticker: 'TSLA',
              quantity: 3,
              avg_cost: 210,
              conflicts_with_existing_position: false,
            },
          ],
        }),
      ),
    )

    renderDialog(true, [])

    await waitFor(() =>
      expect(screen.getByText('New positions to import (2)')).toBeInTheDocument(),
    )
    // Both TSLA rows are still shown (the preview response is honest about
    // what IBKR actually reported), but only one of them will actually be
    // importable, so the confirm button promises 1, not 2.
    expect(screen.getByRole('button', { name: 'Import 1 position' })).toBeInTheDocument()
  })

  // frontend-ibkr-portfolio-preload-followups #4: two conflicting rows that
  // happen to share a ticker must still get distinct checkbox labels, even
  // though they resolve to the same local position (so their checked state
  // is legitimately tied together -- deleting "the local AAPL position" is a
  // single action regardless of how many IBKR rows point at it).
  it('gives each conflicting row a distinct checkbox label even when two rows share a ticker', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'available',
          detail: null,
          positions: [
            {
              conid: 601,
              ticker: 'AAPL',
              quantity: 20,
              avg_cost: 100,
              conflicts_with_existing_position: true,
            },
            {
              conid: 602,
              ticker: 'AAPL',
              quantity: 30,
              avg_cost: 110,
              conflicts_with_existing_position: true,
            },
          ],
        }),
      ),
    )

    renderDialog(true)

    await waitFor(() =>
      expect(screen.getByText('Conflicting tickers (2)')).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 601)',
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', {
        name: 'Delete existing AAPL position (IBKR conid 602)',
      }),
    ).toBeInTheDocument()
  })

  // frontend-ibkr-portfolio-preload-followups #3: MUI's Dialog fires its own
  // onClose on Escape regardless of any button's own disabled state -- only
  // guarding the Cancel button isn't enough.
  it('does not let Escape dismiss the dialog while the preload mutation is pending', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(
      http.post('/api/ibkr/portfolio-preload', async () => {
        await delay('infinite')
        return HttpResponse.json({
          state: 'available',
          detail: null,
          imported: [],
          skipped_conflicting_tickers: [],
        })
      }),
    )
    renderWithProviders(
      <IbkrPreloadDialog open onClose={onClose} existingPositions={[AAPL_POSITION]} />,
    )

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Import 1 position' }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled(),
    )
    // Dispatched directly on the dialog itself (fireEvent, not
    // userEvent.keyboard): once the Import button is disabled by the
    // pending mutation's loading state, the browser blurs it, moving
    // `document.activeElement` outside the modal -- userEvent.keyboard()
    // dispatches to `document.activeElement`, which would then never reach
    // MUI's Modal keydown handler at all, making this assertion pass
    // vacuously regardless of whether the guard actually works.
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape' })

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('lets Escape dismiss the dialog normally once no mutation is pending', async () => {
    const onClose = vi.fn()
    renderWithProviders(
      <IbkrPreloadDialog open onClose={onClose} existingPositions={[AAPL_POSITION]} />,
    )

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Import 1 position' }),
      ).toBeInTheDocument(),
    )
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape' })

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
