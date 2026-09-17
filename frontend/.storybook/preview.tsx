import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import type { Preview } from '@storybook/react-vite'
// Self-hosted Inter, the theme's primary font family (src/theme/theme.ts).
// Same weights as src/main.tsx (see that file for why these five) — without
// this import, Storybook falls back to Storybook's own default font and
// components render with a different typeface than the real app.
import '@fontsource/inter/300.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
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
