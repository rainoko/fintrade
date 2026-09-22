import PowerOffOutlinedIcon from '@mui/icons-material/PowerOffOutlined'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'

export interface UnavailableStateProps {
  /** Short heading naming what's unavailable, e.g. 'Scanner unavailable'. */
  heading: string
  /** Optional supporting detail, e.g. the backend's own `detail` string. */
  message?: string | null
}

/**
 * A feature that is *disabled or not currently reachable*, not broken — the
 * "degrade gracefully" counterpart to `ErrorState`. Several backend routes
 * (e.g. every `/api/ibkr/*` endpoint) report this as an ordinary `200`
 * response with a `state` field (`disabled`/`gateway_unreachable`/
 * `not_authenticated`), never an HTTP error, specifically so the frontend
 * doesn't have to render it as one — see `docs/architecture/API.md`'s IBKR
 * routes and the `frontend-market-scanner-page` task's description. Uses a
 * neutral, non-alarming presentation (a muted icon/heading, `color:
 * "text.secondary"` throughout, no `role="alert"`) — deliberately distinct
 * from `ErrorState`'s red/alert treatment, since nothing has actually gone
 * wrong here — and from `EmptyState`'s "there's real data, there's just none
 * of it right now" framing, since those two are genuinely different
 * outcomes a caller needs to tell apart (e.g. a scan that ran successfully
 * but matched nothing, vs. a scanner that couldn't run at all).
 */
export default function UnavailableState({ heading, message }: UnavailableStateProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 1,
        py: 6,
        px: 2,
        textAlign: 'center',
        color: 'text.secondary',
      }}
    >
      <PowerOffOutlinedIcon fontSize="large" color="disabled" />
      <Typography variant="h6" component="p" color="text.secondary">
        {heading}
      </Typography>
      {message && (
        <Typography variant="body2" color="text.secondary">
          {message}
        </Typography>
      )}
    </Box>
  )
}
