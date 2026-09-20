import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import NavDrawer from './NavDrawer'

function renderAt(path: string, onNavigate?: () => void) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NavDrawer onNavigate={onNavigate} />
    </MemoryRouter>,
  )
}

describe('NavDrawer', () => {
  it('renders a nav link for every top-level page', () => {
    renderAt('/')

    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: /portfolio/i })).toHaveAttribute(
      'href',
      '/portfolio',
    )
    expect(screen.getByRole('link', { name: /watchlist/i })).toHaveAttribute(
      'href',
      '/watchlist',
    )
    expect(screen.getByRole('link', { name: /methodology/i })).toHaveAttribute(
      'href',
      '/methodology',
    )
  })

  it('highlights the Dashboard link as active on /', () => {
    renderAt('/')

    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveClass('Mui-selected')
    expect(screen.getByRole('link', { name: /portfolio/i })).not.toHaveClass(
      'Mui-selected',
    )
  })

  it('highlights the Portfolio link as active on /portfolio', () => {
    renderAt('/portfolio')

    expect(screen.getByRole('link', { name: /portfolio/i })).toHaveClass('Mui-selected')
    expect(screen.getByRole('link', { name: /dashboard/i })).not.toHaveClass(
      'Mui-selected',
    )
  })

  it('highlights the Portfolio link as active on a nested portfolio path', () => {
    renderAt('/portfolio/123')

    expect(screen.getByRole('link', { name: /portfolio/i })).toHaveClass('Mui-selected')
  })

  it('highlights the Watchlist link as active on /watchlist', () => {
    renderAt('/watchlist')

    expect(screen.getByRole('link', { name: /watchlist/i })).toHaveClass('Mui-selected')
    expect(screen.getByRole('link', { name: /dashboard/i })).not.toHaveClass(
      'Mui-selected',
    )
  })

  it('highlights the Methodology link as active on /methodology', () => {
    renderAt('/methodology')

    expect(screen.getByRole('link', { name: /methodology/i })).toHaveClass('Mui-selected')
    expect(screen.getByRole('link', { name: /dashboard/i })).not.toHaveClass(
      'Mui-selected',
    )
  })

  it('calls onNavigate when a nav link is activated', async () => {
    const onNavigate = vi.fn()
    const user = userEvent.setup()
    renderAt('/', onNavigate)

    await user.click(screen.getByRole('link', { name: /portfolio/i }))

    expect(onNavigate).toHaveBeenCalledTimes(1)
  })
})
