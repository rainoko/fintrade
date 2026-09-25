import { screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetTradingModeStore } from '../../tests/mocks/handlers'
import { renderWithProviders } from '../../tests/renderWithProviders'
import SettingsPage from './SettingsPage'

function renderPage() {
  return renderWithProviders(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  )
}

describe('SettingsPage', () => {
  beforeEach(() => {
    resetTradingModeStore()
  })

  it('renders the page title and the trading-mode settings form', async () => {
    renderPage()

    expect(screen.getByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: /swing/i })).toBeInTheDocument(),
    )
  })
})
