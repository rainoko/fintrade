/**
 * Human-readable label per `ClosedTradeOut.exit_reason` value — Elder's own
 * exit-reason taxonomy (docs/Analyse.md §7 / docs/ideas.md's ch. 51 note)
 * plus this app's own `unspecified` default for a trade closed with no
 * explicit reason supplied (`DELETE /api/portfolio/positions/{id}`). Mirrors
 * `EXIT_FLAG_LABELS`' own convention: a value not in this map falls back to
 * `humanizeSnakeCase`'s fallback (underscores-to-spaces, capitalized)
 * instead of rendering nothing for it.
 */
export const EXIT_REASON_LABELS: Record<string, string> = {
  target_hit: 'Target hit',
  stop_hit: 'Stop hit',
  reached_value_zone: 'Reached value zone',
  going_nowhere: 'Going nowhere',
  starting_to_turn: 'Starting to turn',
  couldnt_stand_the_pain: "Couldn't stand the pain",
  recognized_junk_trade_after_entry: 'Recognized junk trade after entry',
  unspecified: 'Unspecified',
}
