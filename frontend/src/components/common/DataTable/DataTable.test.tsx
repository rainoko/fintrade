import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import DataTable, { type DataTableColumn } from './DataTable'

interface Row {
  id: number
  ticker: string
  quantity: number
}

const columns: DataTableColumn<Row>[] = [
  { key: 'ticker', header: 'Ticker', sortable: true },
  { key: 'quantity', header: 'Quantity', sortable: true, align: 'right' },
]

const rows: Row[] = [
  { id: 1, ticker: 'MSFT', quantity: 5 },
  { id: 2, ticker: 'AAPL', quantity: 10 },
]

function getBodyRows() {
  const table = screen.getByRole('table')
  return within(table).getAllByRole('row').slice(1)
}

describe('DataTable', () => {
  it('renders a header cell per column and a row per data item', () => {
    render(<DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} />)

    expect(screen.getByRole('columnheader', { name: 'Ticker' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Quantity' })).toBeInTheDocument()
    expect(getBodyRows()).toHaveLength(2)
    expect(screen.getByText('MSFT')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
  })

  it('renders the built-in empty state when there are no rows', () => {
    render(<DataTable columns={columns} rows={[]} getRowKey={(row) => row.id} />)

    expect(screen.getByText('No data to display.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders a custom empty message and action', () => {
    render(
      <DataTable
        columns={columns}
        rows={[]}
        getRowKey={(row) => row.id}
        emptyMessage="No positions yet"
        emptyAction={<button type="button">Add Position</button>}
      />,
    )

    expect(screen.getByText('No positions yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Position' })).toBeInTheDocument()
  })

  it('sorts rows ascending then descending when a sortable header is clicked', async () => {
    const user = userEvent.setup()
    render(<DataTable columns={columns} rows={rows} getRowKey={(row) => row.id} />)

    await user.click(screen.getByRole('button', { name: 'Ticker' }))
    let bodyRows = getBodyRows()
    expect(within(bodyRows[0]).getByText('AAPL')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('MSFT')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Ticker' }))
    bodyRows = getBodyRows()
    expect(within(bodyRows[0]).getByText('MSFT')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('AAPL')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Ticker' }))
    bodyRows = getBodyRows()
    expect(within(bodyRows[0]).getByText('AAPL')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('MSFT')).toBeInTheDocument()
  })

  it('sorts numeric columns numerically, not lexicographically', async () => {
    const user = userEvent.setup()
    const numericRows: Row[] = [
      { id: 1, ticker: 'A', quantity: 9 },
      { id: 2, ticker: 'B', quantity: 10 },
      { id: 3, ticker: 'C', quantity: 2 },
    ]
    render(<DataTable columns={columns} rows={numericRows} getRowKey={(row) => row.id} />)

    await user.click(screen.getByRole('button', { name: 'Quantity' }))

    const bodyRows = getBodyRows()
    expect(within(bodyRows[0]).getByText('C')).toBeInTheDocument()
    expect(within(bodyRows[1]).getByText('A')).toBeInTheDocument()
    expect(within(bodyRows[2]).getByText('B')).toBeInTheDocument()
  })

  it('renders a custom cell via the render function', () => {
    render(
      <DataTable
        columns={[
          { key: 'ticker', header: 'Ticker' },
          {
            key: 'quantity',
            header: 'Quantity',
            render: (row) => `${row.quantity} shares`,
          },
        ]}
        rows={rows}
        getRowKey={(row) => row.id}
      />,
    )

    expect(screen.getByText('5 shares')).toBeInTheDocument()
    expect(screen.getByText('10 shares')).toBeInTheDocument()
  })

  it('does not render a sort control for a non-sortable column', () => {
    render(
      <DataTable
        columns={[{ key: 'ticker', header: 'Ticker' }]}
        rows={rows}
        getRowKey={(row) => row.id}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Ticker' })).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Ticker' })).toBeInTheDocument()
  })
})
