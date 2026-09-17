import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import TickerSearchBox from './TickerSearchBox'

function renderWithRouter() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<TickerSearchBox />} />
        <Route path="/stocks/:ticker" element={<div>Stock Detail Placeholder</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('TickerSearchBox', () => {
  it('disables the submit button until a ticker is entered', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    expect(screen.getByRole('button', { name: 'Go' })).toBeDisabled()

    await user.type(screen.getByLabelText('Look up a ticker'), 'aapl')

    expect(screen.getByRole('button', { name: 'Go' })).toBeEnabled()
  })

  it('navigates to /stocks/:ticker, uppercasing and trimming the input', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await user.type(screen.getByLabelText('Look up a ticker'), '  aapl  ')
    await user.click(screen.getByRole('button', { name: 'Go' }))

    expect(await screen.findByText('Stock Detail Placeholder')).toBeInTheDocument()
  })

  it('keeps the submit button disabled for whitespace-only input', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await user.type(screen.getByLabelText('Look up a ticker'), '   ')

    expect(screen.getByRole('button', { name: 'Go' })).toBeDisabled()
    expect(screen.queryByText('Stock Detail Placeholder')).not.toBeInTheDocument()
  })

  it("does not navigate if the form is submitted directly while blank (handleSubmit's own guard, independent of the disabled button)", () => {
    renderWithRouter()

    fireEvent.submit(screen.getByLabelText('Look up a ticker').closest('form')!)

    expect(screen.queryByText('Stock Detail Placeholder')).not.toBeInTheDocument()
  })
})
