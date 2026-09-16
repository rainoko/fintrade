import CloudOffIcon from '@mui/icons-material/CloudOff'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlined'
import SearchOffIcon from '@mui/icons-material/SearchOff'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import WifiOffIcon from '@mui/icons-material/WifiOff'
import Box from '@mui/material/Box'
import type { SvgIconProps } from '@mui/material/SvgIcon'
import Typography from '@mui/material/Typography'
import type { ComponentType } from 'react'
import type { ApiError } from '../../../api/client'

interface ErrorPresentation {
  heading: string
  Icon: ComponentType<SvgIconProps>
}

// Distinct heading + icon per documented ApiError case (docs/architecture/API.md's
// "Error Cases to Cover in Tests": 404/422/503), rather than one generic
// "Something went wrong" message for every failure — CLAUDE.md's API
// documentation standard and Frontend.md §7 both call this out explicitly.
// `error.detail` (from the backend's ErrorDetail/HTTPValidationError body)
// supplies the specific, case-dependent explanation text underneath.
function presentationFor(status: number): ErrorPresentation {
  switch (status) {
    case 404:
      return { heading: 'Not found', Icon: SearchOffIcon }
    case 422:
      return { heading: 'Unable to process request', Icon: WarningAmberIcon }
    case 503:
      return { heading: 'Service unavailable', Icon: CloudOffIcon }
    case 0:
      return { heading: 'Connection error', Icon: WifiOffIcon }
    default:
      return { heading: 'Something went wrong', Icon: ErrorOutlineIcon }
  }
}

export interface ErrorStateProps {
  /** The ApiError thrown by api/client.ts's `request` (see api/client.ts). */
  error: ApiError
}

/**
 * Renders an ApiError with a distinct heading/icon per HTTP status case
 * (404 unknown ticker, 422 insufficient history/validation, 503 provider
 * unavailable, plus a 0 network-failure case) and the backend's own
 * human-readable `detail` underneath it.
 */
export default function ErrorState({ error }: ErrorStateProps) {
  const { heading, Icon } = presentationFor(error.status)

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
      }}
      role="alert"
    >
      <Icon fontSize="large" color="error" />
      <Typography variant="h6" component="p">
        {heading}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {error.detail}
      </Typography>
    </Box>
  )
}
