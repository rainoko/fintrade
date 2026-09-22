import Stack from '@mui/material/Stack'
import { useState } from 'react'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import UnavailableState from '../../../components/common/UnavailableState/UnavailableState'
import { useRunScanner } from '../hooks/useRunScanner'
import { toScannerCategories, type ScannerCategory } from '../scannerCategories'
import ScannerCategoryPicker from './ScannerCategoryPicker'
import ScannerResultsTable from './ScannerResultsTable'

export interface ScannerPanelProps {
  /** `GET /api/ibkr/scanner/params`'s raw `categories`, already confirmed
   * non-null (`state === 'available'`) by ScannerPage before rendering this. */
  categories: Record<string, unknown>[]
}

// `POST /api/ibkr/scanner/run`'s `scan_config` needs `instrument`/`location`
// keys IBKR's own gateway response never actually exposes to this frontend:
// `GET /api/ibkr/scanner/params` only ever forwards `scan_type_list` (the
// category picker below) -- the backend deliberately discards
// `instrument_list`/`location_tree` rather than modeling them (see
// backend-market-scanner's `decisions` entry). Building a full
// instrument/location/filter picker UI is out of scope for this task's own
// "pick a scan category, run it" shape (task description) -- these two
// fixed defaults match the exact example scan_config the backend's own
// schema documents (`IBKRScannerRunRequest.scan_config`'s `examples`).
// See this task's `decisions` entry.
const SCAN_INSTRUMENT = 'STK'
const SCAN_LOCATION = 'STK.US.MAJOR'

/**
 * Owns the pick-a-category / run-a-scan / review-results flow: the selected
 * category, the `useRunScanner` mutation, and which of
 * loading/error/unavailable/results to render for its outcome. `categories`
 * itself is passed down already-fetched from ScannerPage (mirroring
 * PortfolioPage passing `usePortfolio()`'s already-fetched `positions` into
 * PositionsTable/RiskPanel) -- this component's own state is entirely the
 * run flow, not the categories query.
 */
export default function ScannerPanel({ categories }: ScannerPanelProps) {
  const scannerCategories: ScannerCategory[] = toScannerCategories(categories)
  const [categoryCode, setCategoryCode] = useState('')
  const runScanner = useRunScanner()

  const handleRun = () => {
    /* v8 ignore next 3 -- unreachable via the UI: ScannerCategoryPicker's Run
       button is disabled whenever `categoryCode` is empty. */
    if (!categoryCode) {
      return
    }
    runScanner.mutate({
      scan_config: {
        instrument: SCAN_INSTRUMENT,
        location: SCAN_LOCATION,
        type: categoryCode,
      },
    })
  }

  return (
    <Stack spacing={3}>
      <ScannerCategoryPicker
        categories={scannerCategories}
        value={categoryCode}
        onChange={setCategoryCode}
        onRun={handleRun}
        running={runScanner.isPending}
      />

      {runScanner.isError && <ErrorState error={runScanner.error} />}

      {runScanner.data && runScanner.data.state !== 'available' && (
        <UnavailableState
          heading="Scanner unavailable"
          message={runScanner.data.detail ?? 'The IBKR market scanner is not available right now.'}
        />
      )}

      {runScanner.data && runScanner.data.state === 'available' && (
        <ScannerResultsTable results={runScanner.data.results ?? []} />
      )}
    </Stack>
  )
}
