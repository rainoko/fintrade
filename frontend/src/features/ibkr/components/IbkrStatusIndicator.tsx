import HelpOutlineIcon from '@mui/icons-material/HelpOutlineOutlined'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Tooltip from '@mui/material/Tooltip'
import IbkrStatusBadge from '../../../components/common/IbkrStatusBadge/IbkrStatusBadge'
import { useIbkrStatus } from '../hooks/useIbkrStatus'

/**
 * Header-level connectivity indicator for the optional IBKR Client Portal
 * Gateway integration (`GET /api/ibkr/status`, docs/architecture/API.md).
 * Rendered inside `AppShell`'s `AppBar` — see this task's `decisions` entry
 * for why the app bar, rather than a dedicated settings page (this app has
 * none yet) or the dashboard: the gateway's connection state is a
 * cross-cutting fact relevant regardless of which page is open, cheap to
 * check, and worth surfacing everywhere at a glance rather than only on one
 * particular screen.
 *
 * Feature component (not `common/`): it owns the `useIbkrStatus` data fetch
 * and its own loading/transport-error presentation, so `AppShell` itself
 * stays a thin layout composition (Frontend.md §3) and
 * `common/IbkrStatusBadge` stays a pure state -> label/color/icon renderer
 * with no fetch awareness of its own.
 */
export default function IbkrStatusIndicator() {
  const statusQuery = useIbkrStatus()

  // Checked in this order (data first) rather than isLoading/isError first
  // followed by a defensive `if (!statusQuery.data) return null`: this
  // query has no `enabled: false` that could leave it settled with neither
  // data nor an error, matching RiskPanel.tsx's own documented reasoning
  // for the same check order.
  if (!statusQuery.data) {
    if (statusQuery.isError) {
      // A transport-level failure (this app's own backend unreachable) is a
      // genuinely different situation from any of the four real gateway
      // states `IbkrStatusBadge` models — rendering it as e.g.
      // `gateway_unreachable` would misleadingly claim to know something
      // about the IBKR gateway specifically when actually this app's own
      // API couldn't be reached at all. Rendered inline (not via the
      // heavier `common/ErrorState`, sized for a page body) since this
      // widget lives in a compact app-bar toolbar.
      // `ApiError.detail` (api/client.ts) is always a populated string --
      // including its own network-failure case, "Unable to reach the API.
      // Check your connection and try again." -- so this is used directly,
      // with no `|| fallback` (that would just be unreachable dead code).
      const detail = statusQuery.error.detail
      return (
        <Tooltip title={detail}>
          <Chip
            data-testid="ibkr-status-indicator-unknown"
            label="IBKR: Unknown"
            color="default"
            icon={<HelpOutlineIcon fontSize="small" />}
            size="small"
            aria-label={`IBKR: Unknown. ${detail}`}
          />
        </Tooltip>
      )
    }
    return <CircularProgress size={16} color="inherit" aria-label="Loading IBKR status" />
  }

  return <IbkrStatusBadge state={statusQuery.data.state} detail={statusQuery.data.detail} />
}
