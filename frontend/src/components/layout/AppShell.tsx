import MenuIcon from '@mui/icons-material/Menu'
import AppBar from '@mui/material/AppBar'
import Box from '@mui/material/Box'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import { useTheme } from '@mui/material/styles'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import NavDrawer from './NavDrawer'

const DRAWER_WIDTH = 240

// Persistent app shell: MUI AppBar + nav, wrapping every routed page via
// react-router's <Outlet/> (see App.tsx, which nests all page routes under
// this as a layout route).
//
// Responsive behavior: below MUI's `sm` breakpoint (600px) the persistent
// side drawer collapses into a hamburger-triggered temporary drawer.
// Decision: neither Frontend.md nor Analyse.md specifies a project-specific
// mobile breakpoint, so this reuses MUI's own `sm` threshold rather than
// inventing a new one — it's the same breakpoint every other MUI responsive
// primitive in the app will default to, keeping behavior consistent without
// a bespoke value to maintain.
export default function AppShell() {
  const theme = useTheme()
  const isNarrow = useMediaQuery(theme.breakpoints.down('sm'))
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleDrawerToggle = () => setMobileOpen((open) => !open)
  const handleDrawerClose = () => setMobileOpen(false)

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar
        position="fixed"
        sx={{
          zIndex: (t) => t.zIndex.drawer + 1,
          ...(!isNarrow && {
            width: `calc(100% - ${DRAWER_WIDTH}px)`,
            ml: `${DRAWER_WIDTH}px`,
          }),
        }}
      >
        <Toolbar>
          {isNarrow && (
            <IconButton
              color="inherit"
              aria-label="open navigation"
              edge="start"
              onClick={handleDrawerToggle}
              sx={{ mr: 2 }}
            >
              <MenuIcon />
            </IconButton>
          )}
          <Typography variant="h6" noWrap component="div">
            fintrade
          </Typography>
        </Toolbar>
      </AppBar>
      <Box component="nav" sx={{ width: { sm: DRAWER_WIDTH }, flexShrink: { sm: 0 } }}>
        {isNarrow ? (
          <Drawer
            variant="temporary"
            open={mobileOpen}
            onClose={handleDrawerClose}
            sx={{
              '& .MuiDrawer-paper': { boxSizing: 'border-box', width: DRAWER_WIDTH },
            }}
          >
            <NavDrawer onNavigate={handleDrawerClose} />
          </Drawer>
        ) : (
          <Drawer
            variant="permanent"
            open
            sx={{
              '& .MuiDrawer-paper': { boxSizing: 'border-box', width: DRAWER_WIDTH },
            }}
          >
            <NavDrawer />
          </Drawer>
        )}
      </Box>
      <Box
        component="main"
        sx={{ flexGrow: 1, p: 3, width: { sm: `calc(100% - ${DRAWER_WIDTH}px)` } }}
      >
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  )
}
