import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet'
import DashboardIcon from '@mui/icons-material/Dashboard'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Toolbar from '@mui/material/Toolbar'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

interface NavItem {
  label: string
  path: string
  icon: ReactNode
}

// Static top-level nav: Dashboard and Portfolio only. Stock Detail
// ('/stocks/:ticker') is intentionally not listed here — it's a
// ticker-parameterized route reached by navigating from a position/search,
// not a standalone nav destination (see docs/architecture/Frontend.md §3's
// page list).
const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: <DashboardIcon /> },
  { label: 'Portfolio', path: '/portfolio', icon: <AccountBalanceWalletIcon /> },
]

interface NavDrawerProps {
  // Called after a nav link is activated. AppShell passes this only to the
  // temporary (mobile) drawer instance, so picking a destination also
  // closes the drawer; the permanent (desktop) drawer has nothing to close
  // and passes nothing.
  onNavigate?: () => void
}

export default function NavDrawer({ onNavigate }: NavDrawerProps) {
  const location = useLocation()

  return (
    <div>
      <Toolbar />
      <List component="nav" aria-label="main navigation">
        {NAV_ITEMS.map((item) => {
          const selected =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path)

          return (
            <ListItem key={item.path} disablePadding>
              <ListItemButton
                component={Link}
                to={item.path}
                selected={selected}
                onClick={onNavigate}
              >
                <ListItemIcon>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>
    </div>
  )
}
