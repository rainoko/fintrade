import { screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetDailyHomeworkStore } from '../../tests/mocks/handlers'
import { renderWithProviders } from '../../tests/renderWithProviders'
import DailyHomeworkPage from './DailyHomeworkPage'

function renderPage() {
  return renderWithProviders(
    <MemoryRouter>
      <DailyHomeworkPage />
    </MemoryRouter>,
  )
}

describe('DailyHomeworkPage', () => {
  beforeEach(() => {
    resetDailyHomeworkStore()
  })

  it('renders the page title and the self-test form', async () => {
    renderPage()

    expect(screen.getByRole('heading', { name: 'Daily Homework', level: 1 })).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Am I ready to trade today?' }),
      ).toBeInTheDocument(),
    )
  })
})
