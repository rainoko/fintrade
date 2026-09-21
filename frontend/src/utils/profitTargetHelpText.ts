// Shared MetricHelp text fragments for the "Profit Target" metric, used by
// BOTH `features/stocks/components/metricHelpContent.ts`'s `profitTargetHelp`
// (a fresh ticker's own signal, `StockDetailPage`) and
// `features/portfolio/components/metricHelpContent.ts`'s `profitTargetHelp`
// (a held position, `RiskPanel`/`PositionProfitTargetCell`) — the first
// same-named MetricHelp entry in this codebase to need near-identical
// content duplicated across two per-feature registries (frontend-profit-
// target-display-followups' own `decisions` entry). Lives under `src/utils/`
// rather than either feature folder specifically so neither registry
// imports the other — both files' own top-of-file comments already
// establish "one registry per feature, no cross-feature registry import" as
// the deliberate convention here (mirroring `buyGradeHelp`/`sellGradeHelp`/
// `tradeGradeHelp`, none of which has a same-named stocks-side counterpart);
// a small domain-agnostic-location shared string constant is the version of
// that convention that also avoids the two texts silently drifting apart on
// a future edit to the Elder ch.53/58 citation or the 2:1 wording.
//
// Plain string constants, not `MetricHelp`-shaped objects — each caller's
// own `interpretValue` differs meaningfully (the portfolio version handles
// an extra null-signal branch a stock ticker's `AnalysisResponse.signal`
// never needs), so only the fully-identical `definition` and the fully-
// identical suffix half of `elderContext` are factored out here; the parts
// that differ (the opening clause of `elderContext`, and the portfolio-only
// trailing sentence about a held position's fresh-entry framing) stay
// defined locally in each registry.

/** Identical, word-for-word, in both `profitTargetHelp.definition` entries. */
export const PROFIT_TARGET_DEFINITION =
  'A suggested exit price for a fresh BUY signal, computed two ways -- current price plus 30% of the weekly chart’s Autoenvelope/channel height (Elder ch. 58’s Tradebill "A" target formula, per ch. 39 p.161’s rule that a profit target is set from the long-term chart), or the nearest support/resistance zone above current price (Elder ch. 18) -- using whichever is TIGHTER (closer to the current price), since a closer target is the more conservative, more probable one to actually be reached.'

/**
 * The shared trailing portion of both `profitTargetHelp.elderContext`
 * entries -- everything from the 2:1 rule's own citation through the
 * BUY-only/long-only disclosure. Each caller's `elderContext` prepends its
 * own opening clause naming what the reward is measured against ("the same
 * protective stop this app already computes" for a fresh ticker, "this same
 * position’s protective stop shown alongside it" for a held position) before
 * this shared suffix, and the portfolio version appends one more sentence
 * of its own after it (the fresh-entry-vs-original-purchase-price framing a
 * held position needs and a fresh ticker's signal doesn't).
 */
export const PROFIT_TARGET_ELDER_CONTEXT_SUFFIX =
  '("it seldom pays to risk a dollar to make a dollar", ch. 53, docs/Analyse.md §7) -- shown here as a reward:risk ratio, always computed and flagged rather than silently hidden when it fails. BUY-only: this app’s protective-stop formula (and its whole portfolio model) is explicitly long-only, so there’s no symmetric SELL-side target/ratio.'
