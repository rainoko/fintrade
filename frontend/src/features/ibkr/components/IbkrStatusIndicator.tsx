import HelpOutlineIcon from '@mui/icons-material/HelpOutlineOutlined'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Tooltip from '@mui/material/Tooltip'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import IbkrStatusBadge from '../../../components/common/IbkrStatusBadge/IbkrStatusBadge'
import { useIbkrStatus } from '../hooks/useIbkrStatus'

// How long the "Log in to IBKR" button stays disabled (loading) after a click, and how
// long this component waits for a `window` `blur` event before concluding `window.open`
// never actually moved focus away (see `awaitingLoginReturnRef` and `handleBlurAfterClick`
// below). Long enough for a real new-tab open to steal focus in practice, short enough
// that a genuinely popup-blocked click doesn't leave the button disabled for a
// user-noticeable stretch before they can retry.
const LOGIN_CLICK_COOLDOWN_MS = 300

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
 * badge alone still explains the situation via its tooltip. The button shows
 * MUI's `loading` state (spinner + disabled, this codebase's established
 * pending-action-button convention — see `AddTickerForm.tsx`,
 * `TradeApgarDialog.tsx`, `FollowUpReviewDialog.tsx`) for
 * `LOGIN_CLICK_COOLDOWN_MS` after each click (guards against rapid repeated
 * clicks opening duplicate tabs) and uses that same window to heuristically
 * detect a popup-blocked open, so it doesn't leave the return-refetch gate
 * stuck armed — see `frontend-ibkr-login-button-followups`'s `decisions`
 * entry.
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

  // Disables the "Log in to IBKR" button for `LOGIN_CLICK_COOLDOWN_MS` after
  // a click — both to stop rapid repeated clicks from opening that many
  // duplicate login tabs, and to give the popup-blocked check below a short
  // window to run before the button becomes clickable again (see
  // `frontend-ibkr-login-button-followups`'s `decisions` entry).
  const [isOpeningLogin, setIsOpeningLogin] = useState(false)
  const cooldownTimeoutRef = useRef<number | undefined>(undefined)

  // Whether a `window` `blur` event has fired since the most recent click, and the
  // listener registered for it (so it can be torn down early — see
  // `handleBlurAfterClick` below and this task's `decisions` entry for why a `blur`
  // *event* replaced the previous `document.hasFocus()` poll-at-a-fixed-instant check).
  const focusLeftSinceClickRef = useRef(false)
  const pendingBlurListenerRef = useRef<(() => void) | null>(null)

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

  // Clear any pending cooldown timeout, and any still-registered `blur` listener, on
  // unmount so neither can fire (and call `setIsOpeningLogin`/mutate a ref) after this
  // component is gone.
  useEffect(() => {
    return () => {
      if (cooldownTimeoutRef.current !== undefined) {
        window.clearTimeout(cooldownTimeoutRef.current)
      }
      if (pendingBlurListenerRef.current) {
        window.removeEventListener('blur', pendingBlurListenerRef.current)
      }
    }
  }, [])

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
            loading={isOpeningLogin}
            onClick={() => {
              setIsOpeningLogin(true)
              awaitingLoginReturnRef.current = true
              focusLeftSinceClickRef.current = false

              // Registered *before* `window.open` below (not after) so there is no
              // instant, however narrow, during which a synchronous focus change
              // triggered by `window.open` itself could fire a `blur` event with no
              // listener yet present to observe it — see
              // `frontend-ibkr-login-button-followups-followups-followups`'s
              // `decisions` entry. `noopener` means the call below always returns
              // `null` regardless of whether a tab actually opened (see the comment
              // on `awaitingLoginReturnRef`), so that return value can't distinguish
              // a real open from a popup-blocked one. But a real open moves focus to
              // the new tab almost immediately, so a `blur` event on this window
              // shortly after the click is a direct, synchronous signal that it
              // happened — a more standard and precise idiom for this than the
              // previous `document.hasFocus()` poll at one arbitrary fixed instant
              // (see this task's `decisions` entry). If no `blur` fires before the
              // cooldown timeout below, no new tab could have moved focus away — the
              // click was almost certainly popup-blocked, so the gate is cleared so
              // the next unrelated window focus doesn't fire one incorrect extra
              // status refetch. Still a heuristic, not a guarantee (e.g. a browser
              // configured to open new tabs in the background wouldn't move focus
              // even on a real, successful open — see this task's `decisions` entry
              // for that residual, already-bounded risk): its failure mode is
              // limited to occasionally missing the instant refetch for one login
              // attempt and falling back to the existing up-to-30s background poll,
              // never a stuck permanently-armed gate.
              function handleBlurAfterClick() {
                focusLeftSinceClickRef.current = true
                window.removeEventListener('blur', handleBlurAfterClick)
                pendingBlurListenerRef.current = null
              }
              window.addEventListener('blur', handleBlurAfterClick)
              pendingBlurListenerRef.current = handleBlurAfterClick

              // Most browsers just silently no-op/return `null` from `window.open`
              // for a popup-blocked or malformed-scheme URL, but some
              // browser/extension configurations throw synchronously instead (e.g.
              // a disallowed scheme). Registering the `blur` listener above
              // `window.open` (rather than after, per this task's own dependency)
              // closes one timing gap but opens another: a synchronous throw here
              // would otherwise skip the cooldown `setTimeout` below entirely,
              // leaving the just-registered listener referenced by
              // `pendingBlurListenerRef.current` with nothing to remove it until
              // the next unrelated `blur` event or this component's unmount (see
              // `frontend-ibkr-login-button-followups-followups-followups-followups`'s
              // `decisions` entry). The `try`/`catch` below removes it immediately
              // in that case, then rethrows so this throw's other pre-existing,
              // already-accepted failure mode -- `isOpeningLogin` staying stuck
              // `true` -- is left exactly as it was before this fix.
              try {
                window.open(login_url, '_blank', 'noopener,noreferrer')
              } catch (err) {
                window.removeEventListener('blur', handleBlurAfterClick)
                pendingBlurListenerRef.current = null
                throw err
              }

              cooldownTimeoutRef.current = window.setTimeout(() => {
                setIsOpeningLogin(false)
                if (pendingBlurListenerRef.current) {
                  window.removeEventListener('blur', pendingBlurListenerRef.current)
                  pendingBlurListenerRef.current = null
                }
                if (!focusLeftSinceClickRef.current) {
                  awaitingLoginReturnRef.current = false
                }
              }, LOGIN_CLICK_COOLDOWN_MS)
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
