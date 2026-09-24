import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CloudOffIcon from '@mui/icons-material/CloudOff'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew'
import Chip, { type ChipProps } from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'
import type { ReactElement } from 'react'

/** Mirrors `IBKRStatusResponse.state` (`api/ibkr.ts`, `backend/openapi.json`) exactly. */
export type IbkrGatewayState =
  | 'disabled'
  | 'available'
  | 'gateway_unreachable'
  | 'not_authenticated'

export interface IbkrStatusBadgeProps {
  /** The gateway state to render — see `GET /api/ibkr/status` (API.md). */
  state: IbkrGatewayState
  /**
   * Optional human-readable context from the response's own `detail` field.
   * Shown in the tooltip when present; falls back to a fixed, per-state
   * explanation otherwise (`detail` is usually `null` for `available`, per
   * API.md).
   */
  detail?: string | null
}

interface Presentation {
  label: string
  color: ChipProps['color']
  icon: ReactElement
  fallbackTooltip: string
}

// Standard MUI semantic Chip colors (success/warning/error/default) rather
// than a new custom `theme.palette.*` entry (the pattern `signal`/`season`/
// `riskBreach` use): those exist because this codebase needs colors with a
// specific *methodology* meaning (BUY/SELL/HOLD, an Elder "season") that
// MUI's own palette has no equivalent for, each carefully checked for
// perceptual distance from every other custom entry (see theme.ts's
// extensive ΔE76 comments). A gateway connectivity indicator is exactly the
// generic "ok/warning/error/off" case MUI's own semantic palette already
// models — reusing it avoids both an unnecessary theme change and having to
// separately verify a new custom color against every existing one. See this
// task's `decisions` entry.
function presentationFor(state: IbkrGatewayState): Presentation {
  switch (state) {
    case 'available':
      return {
        label: 'IBKR: Connected',
        color: 'success',
        icon: <CheckCircleIcon fontSize="small" />,
        fallbackTooltip: 'The IBKR gateway is running and its session is authenticated.',
      }
    case 'not_authenticated':
      return {
        label: 'IBKR: Sign-in needed',
        color: 'warning',
        icon: <LockOutlinedIcon fontSize="small" />,
        fallbackTooltip:
          "The IBKR gateway is up, but its interactive browser login hasn't been completed, or the session has since expired.",
      }
    case 'gateway_unreachable':
      return {
        label: 'IBKR: Gateway down',
        color: 'error',
        icon: <CloudOffIcon fontSize="small" />,
        fallbackTooltip: 'No IBKR gateway process answered — it is most likely not running.',
      }
    case 'disabled':
      return {
        label: 'IBKR: Disabled',
        color: 'default',
        icon: <PowerSettingsNewIcon fontSize="small" />,
        fallbackTooltip: 'The optional IBKR Client Portal Gateway integration is turned off.',
      }
  }
}

/**
 * Colored, iconed chip for the optional IBKR Client Portal Gateway
 * integration's connection state (`GET /api/ibkr/status`,
 * docs/architecture/API.md). Takes only a plain string-union prop and never
 * fetches — same domain-agnostic test `common/SignalBadge`/`common/SeasonBadge`
 * already apply (Frontend.md §3) — so it lives in `components/common/` rather
 * than `features/ibkr/`; `features/ibkr/components/IbkrStatusIndicator.tsx`
 * owns the actual `useIbkrStatus` data fetch and loading/error presentation.
 */
export default function IbkrStatusBadge({ state, detail }: IbkrStatusBadgeProps) {
  const { label, color, icon, fallbackTooltip } = presentationFor(state)
  const tooltipText = detail ?? fallbackTooltip

  return (
    <Tooltip title={tooltipText}>
      <Chip
        data-testid="ibkr-status-badge"
        label={label}
        color={color}
        icon={icon}
        size="small"
        aria-label={`${label}. ${tooltipText}`}
      />
    </Tooltip>
  )
}
