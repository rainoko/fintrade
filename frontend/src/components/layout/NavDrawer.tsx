import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet'
import ChecklistIcon from '@mui/icons-material/Checklist'
import DashboardIcon from '@mui/icons-material/Dashboard'
import MenuBookIcon from '@mui/icons-material/MenuBook'
import RadarIcon from '@mui/icons-material/Radar'
import VisibilityIcon from '@mui/icons-material/Visibility'
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

// Static top-level nav: Dashboard, Portfolio, Watchlist, Scanner, Daily
// Homework, and Methodology. Stock Detail ('/stocks/:ticker') is
// intentionally not listed here — it's a ticker-parameterized route reached
// by navigating from a position/search, not a standalone nav destination
// (see docs/architecture/Frontend.md §3's page list). Methodology
// ('/methodology', frontend-methodology-explainer) IS listed even though
// it's not in that doc's page list yet — it's a genuine standalone
// destination (the "signals we considered" reference page), not reached by
// drilling into any specific ticker/position the way Stock Detail is.
// Scanner ('/scanner', frontend-market-scanner-page) is likewise a genuine
// standalone destination per docs/ideas.md's own ch. 56 scoping — "a new
// page, not a section of the watchlist or ticker detail view" — placed
// after Watchlist since its own flow feeds candidates *into* the watchlist.
// Daily Homework ('/homework', frontend-daily-homework-page) is the same
// kind of standalone destination — a daily ritual with no ticker/position to
// drill in from — see that task's `decisions` entry for the full placement
// rationale.
const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: <DashboardIcon /> },
  { label: 'Portfolio', path: '/portfolio', icon: <AccountBalanceWalletIcon /> },
  { label: 'Watchlist', path: '/watchlist', icon: <VisibilityIcon /> },
  { label: 'Scanner', path: '/scanner', icon: <RadarIcon /> },
  { label: 'Daily Homework', path: '/homework', icon: <ChecklistIcon /> },
  { label: 'Methodology', path: '/methodology', icon: <MenuBookIcon /> },
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
