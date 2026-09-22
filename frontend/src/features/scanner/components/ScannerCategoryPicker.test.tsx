import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ScannerCategoryPicker from './ScannerCategoryPicker'

const categories = [
  { code: 'TOP_PERC_GAIN', label: 'Top % Gainers' },
  { code: 'TOP_PERC_LOSE', label: 'Top % Losers' },
]

describe('ScannerCategoryPicker', () => {
  it('lists every category as a selectable option', async () => {
    const user = userEvent.setup()
    render(
      <ScannerCategoryPicker
        categories={categories}
        value=""
        onChange={vi.fn()}
        onRun={vi.fn()}
        running={false}
      />,
    )

    await user.click(screen.getByRole('combobox', { name: 'Scan category' }))

    expect(screen.getByRole('option', { name: 'Top % Gainers' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Top % Losers' })).toBeInTheDocument()
  })

  it('calls onChange with the selected category code', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <ScannerCategoryPicker
        categories={categories}
        value=""
        onChange={onChange}
        onRun={vi.fn()}
        running={false}
      />,
    )

    await user.click(screen.getByRole('combobox', { name: 'Scan category' }))
    await user.click(screen.getByRole('option', { name: 'Top % Losers' }))

    expect(onChange).toHaveBeenCalledWith('TOP_PERC_LOSE')
  })

  it('disables the Run scan button when no category is selected', () => {
    render(
      <ScannerCategoryPicker
        categories={categories}
        value=""
        onChange={vi.fn()}
        onRun={vi.fn()}
        running={false}
      />,
    )

    expect(screen.getByRole('button', { name: 'Run scan' })).toBeDisabled()
  })

  it('enables the Run scan button once a category is selected, and calls onRun when clicked', async () => {
    const onRun = vi.fn()
    const user = userEvent.setup()
    render(
      <ScannerCategoryPicker
        categories={categories}
        value="TOP_PERC_GAIN"
        onChange={vi.fn()}
        onRun={onRun}
        running={false}
      />,
    )

    const button = screen.getByRole('button', { name: 'Run scan' })
    expect(button).toBeEnabled()

    await user.click(button)

    expect(onRun).toHaveBeenCalledTimes(1)
  })

  it('shows the Run scan button as loading while a scan is running', () => {
    render(
      <ScannerCategoryPicker
        categories={categories}
        value="TOP_PERC_GAIN"
        onChange={vi.fn()}
        onRun={vi.fn()}
        running
      />,
    )

    expect(screen.getByRole('button', { name: 'Run scan' })).toBeDisabled()
  })
})
