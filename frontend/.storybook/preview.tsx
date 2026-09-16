import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import type { Preview } from '@storybook/react-vite'
import { theme } from '../src/theme/theme'

// Wires every story to the app's real MUI theme (src/theme/theme.ts) so
// components render with the same palette/typography they'll have in the
// app — including the semantic signal/riskBreach colors.
const preview: Preview = {
  decorators: [
    (Story) => (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Story />
      </ThemeProvider>
    ),
  ],
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    a11y: {
      // Fail the a11y checks panel on violations rather than just listing
      // them, so an inaccessible common/ component doesn't slip through
      // Storybook unnoticed.
      test: 'error',
    },
  },
}

export default preview
