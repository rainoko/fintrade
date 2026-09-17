import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TableSortLabel from '@mui/material/TableSortLabel'
import Paper from '@mui/material/Paper'
import { useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import EmptyState from '../EmptyState/EmptyState'

export interface DataTableColumn<T> {
  /** Property of `T` this column renders/sorts by. */
  key: keyof T
  /** Column header text. */
  header: string
  /** Whether clicking the header sorts by this column. Defaults to false. */
  sortable?: boolean
  /** Custom cell renderer. Defaults to the raw `row[key]` value. */
  render?: (row: T) => ReactNode
  align?: 'left' | 'right' | 'center'
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  /** Stable unique key for each row, e.g. `(row) => row.id`. */
  getRowKey: (row: T) => string | number
  /** Message shown via EmptyState when `rows` is empty. */
  emptyMessage?: string
  /** Optional action shown alongside the empty-state message. */
  emptyAction?: ReactNode
  /**
   * Optional per-row inline styling, e.g. flagging a row that breaches a
   * caller's own rule (RiskPanel's `two_percent_rule_breached`). Takes the
   * row and returns a `style` object, or `undefined` for no special styling
   * — still domain-agnostic, since the condition that triggers it is
   * entirely the caller's business. Plain inline `style` (not `sx`) so a
   * resolved color always renders as a `style` attribute jsdom/testing-
   * library can assert on directly, matching PercentChange/SignalBadge's
   * same choice elsewhere in `common/`.
   */
  getRowStyle?: (row: T) => CSSProperties | undefined
  /**
   * Accessible name for the underlying `<table>` (MUI's `Table` forwards
   * `aria-label`), so a page rendering more than one DataTable (e.g.
   * PortfolioPage's PositionsTable + RiskPanel) can be queried by name
   * instead of an ambiguous generic `table` role match.
   */
  ariaLabel?: string
}

type SortDirection = 'asc' | 'desc'

function isMissing(value: unknown): boolean {
  return value === null || value === undefined
}

function compareValues(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') {
    return a - b
  }
  return String(a).localeCompare(String(b))
}

/**
 * Comparator used for sorting: missing values (null/undefined, e.g. an
 * optional numeric column with some rows unset) always sort last regardless
 * of ascending/descending direction, rather than falling back to
 * String(undefined)='undefined' lexicographic comparison (which would sort
 * '10' before '9' once any row's value is missing, since compareValues only
 * special-cases number/number pairs).
 */
function compareForSort(a: unknown, b: unknown, direction: SortDirection): number {
  const aMissing = isMissing(a)
  const bMissing = isMissing(b)
  if (aMissing || bMissing) {
    if (aMissing && bMissing) {
      return 0
    }
    return aMissing ? 1 : -1
  }
  const result = compareValues(a, b)
  return direction === 'asc' ? result : -result
}

/**
 * Thin MUI Table wrapper: typed columns, optional per-column sorting, and a
 * built-in empty state (reusing common/EmptyState) when `rows` is empty.
 * Domain-agnostic — every column and cell value is supplied by the caller.
 */
export default function DataTable<T>({
  columns,
  rows,
  getRowKey,
  emptyMessage = 'No data to display.',
  emptyAction,
  getRowStyle,
  ariaLabel,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<keyof T | null>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

  const sortedRows = useMemo(() => {
    if (sortKey === null) {
      return rows
    }
    const copy = [...rows]
    copy.sort((a, b) => compareForSort(a[sortKey], b[sortKey], sortDirection))
    return copy
  }, [rows, sortKey, sortDirection])

  if (rows.length === 0) {
    return <EmptyState message={emptyMessage} action={emptyAction} />
  }

  const handleSort = (key: keyof T) => {
    if (sortKey === key) {
      setSortDirection((direction) => (direction === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label={ariaLabel}>
        <TableHead>
          <TableRow>
            {columns.map((column) => (
              <TableCell key={String(column.key)} align={column.align ?? 'left'}>
                {column.sortable ? (
                  <TableSortLabel
                    active={sortKey === column.key}
                    direction={sortKey === column.key ? sortDirection : 'asc'}
                    onClick={() => handleSort(column.key)}
                  >
                    {column.header}
                  </TableSortLabel>
                ) : (
                  column.header
                )}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {sortedRows.map((row) => (
            <TableRow key={getRowKey(row)} style={getRowStyle?.(row)}>
              {columns.map((column) => (
                <TableCell key={String(column.key)} align={column.align ?? 'left'}>
                  {column.render ? column.render(row) : String(row[column.key])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
