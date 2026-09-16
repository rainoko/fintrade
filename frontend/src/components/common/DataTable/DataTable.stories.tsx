import type { Meta, StoryObj } from '@storybook/react-vite'
import DataTable, { type DataTableColumn } from './DataTable'

interface PositionRow {
  id: number
  ticker: string
  quantity: number
  avgCost: number
}

const columns: DataTableColumn<PositionRow>[] = [
  { key: 'ticker', header: 'Ticker', sortable: true },
  { key: 'quantity', header: 'Quantity', sortable: true, align: 'right' },
  {
    key: 'avgCost',
    header: 'Avg Cost',
    sortable: true,
    align: 'right',
    render: (row) => `$${row.avgCost.toFixed(2)}`,
  },
]

const rows: PositionRow[] = [
  { id: 1, ticker: 'MSFT', quantity: 5, avgCost: 310.12 },
  { id: 2, ticker: 'AAPL', quantity: 10, avgCost: 178.5 },
  { id: 3, ticker: 'NVDA', quantity: 2, avgCost: 890.0 },
]

const meta: Meta<typeof DataTable<PositionRow>> = {
  title: 'Common/DataTable',
  component: DataTable<PositionRow>,
}

export default meta
type Story = StoryObj<typeof DataTable<PositionRow>>

export const Populated: Story = {
  args: {
    columns,
    rows,
    getRowKey: (row) => row.id,
  },
}

export const Empty: Story = {
  args: {
    columns,
    rows: [],
    getRowKey: (row) => row.id,
    emptyMessage: 'No positions yet.',
  },
}
