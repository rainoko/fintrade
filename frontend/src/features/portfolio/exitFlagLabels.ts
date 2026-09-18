/**
 * Human-readable label per known `exit_flags` value (docs/Analyse.md §7,
 * app.portfolio.exits.evaluate_exit_flags). Shared between RiskPanel (full
 * per-position risk table, Portfolio page) and SellFlaggedPositionsCard
 * (dashboard sell-flag summary) so the two never drift on wording for the
 * same underlying flag. A value not in this map (e.g. a future flag added on
 * the backend before the frontend catches up) falls back to
 * humanizeSnakeCase's fallback (underscores-to-spaces, capitalized) rather
 * than rendering nothing for it.
 */
export const EXIT_FLAG_LABELS: Record<string, string> = {
  stop_hit: 'Stop hit',
  two_percent_rule_breached: '2% rule breached',
  six_percent_rule_contributor: '6% rule contributor',
  profit_zone_impulse_red: 'Profit zone (Impulse red)',
  tide_flipped_bearish: 'Tide flipped bearish',
}
