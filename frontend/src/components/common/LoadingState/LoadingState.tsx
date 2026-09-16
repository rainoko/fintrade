import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import Typography from '@mui/material/Typography'

export interface LoadingStateProps {
  /** Optional message shown under the spinner, e.g. 'Loading portfolio...'. */
  message?: string
}

/**
 * Generic in-flight indicator used while a TanStack Query hook's `isLoading`
 * is true. Purely presentational.
 */
export default function LoadingState({ message }: LoadingStateProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 1.5,
        py: 6,
      }}
    >
      <CircularProgress aria-label="Loading" />
      {message && (
        <Typography variant="body2" color="text.secondary">
          {message}
        </Typography>
      )}
    </Box>
  )
}
