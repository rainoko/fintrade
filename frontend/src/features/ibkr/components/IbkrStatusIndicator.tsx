import HelpOutlineIcon from '@mui/icons-material/HelpOutlineOutlined'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Tooltip from '@mui/material/Tooltip'
import { useEffect, useRef, type ReactElement } from 'react'
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
 * Also renders a "Log in to IBKR" button next to the badge whenever `state`
 * is `not_authenticated` and the response's `login_url` is populated
 * (`frontend-ibkr-login-button`) — clicking it opens that URL in a new
 * browser tab/window (`window.open`, never an in-app `<iframe>`/modal: see
 * this task's `decisions` entry for why IBKR's own login page cannot be
 * embedded). `login_url` absent for any other reason (an older cached
 * response, a genuine backend edge case) simply renders no button — the
 * badge alone still explains the situation via its tooltip.
 *
 * Feature component (not `common/`): it owns the `useIbkrStatus` data fetch
 * and its own loading/transport-error presentation, so `AppShell` itself
 * stays a thin layout composition (Frontend.md §3) and
 * `common/IbkrStatusBadge` stays a pure state -> label/color/icon renderer
 * with no fetch awareness of its own.
 */
export default function IbkrStatusIndicator() {
  const statusQuery = useIbkrStatus()
  const { refetch } = statusQuery

  // Set the instant "Log in to IBKR" is clicked (a real login page was just
  // opened in a new tab) and read — then cleared — the next time this
  // window regains focus, which is this app's own signal that the user has
  // switched back after attempting the login. That triggers an immediate
  // status refetch rather than waiting on the next up-to-30s background
  // poll to notice a completed login. Deliberately not tracking the opened
  // window's own `.closed` state instead (the checklist's other suggested
  // mechanism): `window.open` below is called with the `noopener` feature
  // (this app has no legitimate reason to hold a live reference into IBKR's
  // own window, and withholding one closes off the standard
  // "reverse tabnabbing" attack where an opened page uses `window.opener` to
  // navigate this app's own tab away) — per spec, `window.open` returns
  // `null` whenever `noopener` is requested, so there would be no window
  // reference to poll `.closed` on even if this app wanted to. See this
  // task's `decisions` entry.
  const awaitingLoginReturnRef = useRef(false)

  useEffect(() => {
    function handleWindowFocus() {
      if (!awaitingLoginReturnRef.current) {
        return
      }
      awaitingLoginReturnRef.current = false
      void refetch()
    }

    window.addEventListener('focus', handleWindowFocus)
    return () => window.removeEventListener('focus', handleWindowFocus)
  }, [refetch])

  // `isError` is checked *before* `!data`, not after: TanStack Query keeps
  // the last successful `data` populated across a failed background
  // refetch (its own documented behavior for `refetchInterval` polling), so
  // checking `!data` first would let a stale-but-present value from before
  // the failure mask a *later* transport failure indefinitely once the
  // initial fetch has ever succeeded once. Checking `isError` first instead
  // means every genuine transport failure — on the very first load or on
  // any later background poll — renders the same distinct 'Unknown' chip,
  // regardless of what `data` happened to hold before it.
  let content: ReactElement
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
    content = (
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
  } else if (!statusQuery.data) {
    // This query has no `enabled: false` that could leave it settled with
    // neither data nor an error, so reaching here means the initial fetch
    // simply hasn't resolved yet.
    content = <CircularProgress size={16} color="inherit" aria-label="Loading IBKR status" />
  } else {
    const { state, detail, login_url } = statusQuery.data
    content = (
      <>
        <IbkrStatusBadge state={state} detail={detail} />
        {state === 'not_authenticated' && login_url ? (
          <Button
            data-testid="ibkr-login-button"
            size="small"
            variant="outlined"
            color="warning"
            onClick={() => {
              awaitingLoginReturnRef.current = true
              window.open(login_url, '_blank', 'noopener,noreferrer')
            }}
          >
            Log in to IBKR
          </Button>
        ) : null}
      </>
    )
  }

  // `role="status"` (implicit `aria-live="polite"`) so a screen-reader user
  // who isn't currently focused on/near the app bar is still told when the
  // gateway's connectivity changes between the silent 30s background
  // polls — this indicator mounts once for the whole session with no user
  // action to re-trigger a read of it otherwise. Matches RiskPanel.tsx's own
  // `role="status"` precedent for a similarly unprompted state change.
  // Deliberately *not* `display: 'contents'` to hide this wrapper's own box
  // from layout: several browsers have a history of also stripping the
  // element's accessible node (and with it, the live-region role) when
  // `display: contents` is used, which would silently defeat the point.
  // `Toolbar`'s flex layout blockifies any direct child regardless of its
  // own `display`, so this extra `Box` sizes identically to the bare `Chip`/
  // `CircularProgress` it used to render as `AppShell`'s last flex item — the
  // `display: 'flex'`/`gap` below only affects how this `Box`'s OWN children
  // (the badge and, when shown, the login button) lay out relative to each
  // other, not how the `Box` itself sits in `Toolbar`'s flex row.
  return (
    <Box role="status" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      {content}
    </Box>
  )
}
