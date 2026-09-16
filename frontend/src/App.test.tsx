import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from './App'

// Route-table smoke test: confirms every route in App.tsx resolves to its
// placeholder page. Real page content/behavior is covered by each page's
// own tests once it lands (frontend-dashboard-page, frontend-portfolio-page,
// frontend-stock-analysis-page).
describe('App', () => {
  it.each([
    ['/', 'Dashboard'],
    ['/portfolio', 'Portfolio'],
    ['/stocks/AAPL', 'Stock Detail'],
  ])('renders the page mapped to %s', (path, heading) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
  })
})
