/**
 * Static content for the Methodology Reference page (`/methodology`,
 * `frontend-methodology-explainer`) -- the "signals we considered" page
 * explicitly requested at the start of this task-authoring batch. Every
 * entry below is a direct paraphrase of `docs/Analyse.md` (the source of
 * truth for what this app computes) and `docs/ideas.md` (the scratchpad of
 * everything considered but not, or not yet, built), each carrying its own
 * book/chapter citation and an honest `appStatus` describing whether/how it
 * currently affects the BUY/SELL/HOLD signal, the confidence score, or the
 * portfolio risk rules -- not just what the indicator/technique *is*.
 *
 * Deliberately data-only (no JSX, no component logic) so the page's actual
 * *content* can be reviewed/updated on its own, independent of its
 * rendering -- see this task's `decisions` entry for why this file lives
 * under `features/methodology/data/` rather than being inlined into a
 * component, and for the decision on how this content stays in sync as the
 * signal roster changes going forward.
 *
 * Cross-linking decision (see `decisions`): this page deliberately does
 * NOT duplicate the live, per-value interpretive text already served by
 * `common/MetricHelp` (`features/stocks/components/metricHelpContent.ts`,
 * `features/portfolio/components/metricHelpContent.ts`) -- those explain
 * *this specific ticker's current value* next to where it's shown; this
 * page explains the *methodology* (what the technique is, Elder's own
 * citation, and its current status in this app) independent of any one
 * ticker. Where a MetricHelp entry already exists for something described
 * here, `crossLinksTo` names it so a reader can find the live version.
 */

export type MethodologyStatus = 'core_signal' | 'risk_management' | 'informational' | 'considered'

export interface StatusMeta {
  label: string
  /** MUI Chip `color` prop value. */
  color: 'success' | 'primary' | 'info' | 'default'
  description: string
}

/**
 * One row per `MethodologyStatus`, in the order the filter row/legend
 * renders them -- deliberately ordered "most load-bearing first" (what
 * actually decides today's BUY/SELL/HOLD, then what decides portfolio
 * risk/money-management guidance, then what's computed and shown but
 * doesn't feed either, then what's only ever been considered).
 */
export const STATUS_META: Record<MethodologyStatus, StatusMeta> = {
  core_signal: {
    label: 'Active — feeds the signal',
    color: 'success',
    description:
      'Directly used to compute today’s BUY/SELL/HOLD signal and/or its confidence score (docs/Analyse.md §5-6).',
  },
  risk_management: {
    label: 'Active — feeds portfolio risk & money management',
    color: 'primary',
    description:
      'Directly used by the 2%/6% Rules, the protective stop, the profit target, trade grading, or an existing-position exit flag (docs/Analyse.md §7) -- independent of the entry signal above, per Elder’s own "indicator signals alone are not enough" rule.',
  },
  informational: {
    label: 'Computed & exposed — informational only',
    color: 'info',
    description:
      'Computed by the backend and shown to you, but NOT (yet) wired into the signal, the confidence score, or a portfolio risk rule -- an honest "here’s the toolkit, here’s what it isn’t doing yet" case, not a bug.',
  },
  considered: {
    label: 'Considered — not yet implemented',
    color: 'default',
    description:
      'Logged in docs/ideas.md as something Elder describes and this app could add, but that hasn’t been built (or scoped as a task) yet.',
  },
}

/**
 * Every `MethodologyStatus` value, in the same "most load-bearing first"
 * order `STATUS_META` above is defined in -- derived from `STATUS_META`'s
 * own key order rather than hand-duplicated as a second `string[]` literal
 * in each consumer (`MethodologyPage.tsx`'s old `ALL_STATUSES`,
 * `MethodologyStatusFilter.tsx`'s old `STATUS_ORDER`), so a future 5th
 * status added to `MethodologyStatus`/`STATUS_META` can't silently be
 * missing from either one (docs/tasks/frontend-methodology-explainer-
 * followups.json's `decisions` entry).
 */
export const STATUS_ORDER: MethodologyStatus[] = Object.keys(STATUS_META) as MethodologyStatus[]

export interface MethodologyEntry {
  id: string
  name: string
  /** Book/chapter/page citation, e.g. "Elder, ch. 39, pp. 156-157". */
  citation: string
  /** What this technique/indicator is, in plain language. */
  summary: string
  /** How it fits Elder's Triple Screen/Impulse/money-management methodology. */
  elderContext: string
  appStatus: MethodologyStatus
  /** Honest description of whether/how this affects what a user sees today. */
  appBehavior: string
  /** Optional pointer to where this same thing has a live, per-value MetricHelp explanation elsewhere in the app. */
  crossLinksTo?: string
}

export interface MethodologySection {
  id: string
  title: string
  intro: string
  entries: MethodologyEntry[]
}

export const METHODOLOGY_SECTIONS: MethodologySection[] = [
  {
    id: 'overview',
    title: 'Overview: the Triple Screen Trading System',
    intro:
      'This app’s signal engine is based on Dr. Alexander Elder’s methodology, primarily from Trading for a Living and The New Trading for a Living -- the Triple Screen Trading System, combined with his Impulse System, Force Index and Elder-Ray indicators, and his 2%/6% risk-management rules (docs/Analyse.md §1). Elder’s core idea: never rely on one indicator. Combine a trend-following tool (to establish direction) with oscillators (to time entries against that trend), and always filter trade size through money-management rules, independent of how good the signal looks. The sections below walk through every screen/rule this app actually implements, in the order Elder evaluates them, followed by the full catalog of every other indicator and technique this app is aware of -- whether it’s wired into your signal today, exposed as pure context, or still just an idea on the drawing board (docs/ideas.md).',
    entries: [],
  },
  {
    id: 'screen-1-tide',
    title: 'Screen 1 — The Tide (long-term trend)',
    intro:
      'Purpose: determine the dominant market trend, evaluated on the weekly chart. Elder’s rule: never trade against the tide (docs/Analyse.md §2).',
    entries: [
      {
        id: 'weekly-impulse-tide',
        name: 'Weekly Impulse System (Tide)',
        citation: 'Elder, ch. 39 "Triple Screen Trading System", The New Trading for a Living (2014), pp. 156-157',
        summary:
          'The Impulse System (see below) computed on the weekly chart instead of the daily one. Weekly Impulse GREEN (weekly EMA(13) and weekly MACD-Histogram both rising bar-over-bar) means the tide is bullish; RED (both falling) means bearish; BLUE (the two disagree, or too little weekly history) means neutral.',
        elderContext:
          'Elder’s own words are explicit that the Impulse System directly replaced his original weekly-MACD-Histogram-slope test as Screen 1’s trend tool: "The original version of Triple Screen used the slope of weekly MACD-Histogram as its weekly trend-following indicator... After I invented the Impulse system... I began to use it for the first screen of Triple Screen." This app’s Screen 1 implements that replacement, not a reconciliation between the two (see the `backend-weekly-impulse-screen1` task’s `decisions` entry).',
        appStatus: 'core_signal',
        appBehavior:
          'Directly computes `tide` (BULLISH/BEARISH/NEUTRAL): BUY requires a bullish tide, SELL requires a bearish tide, and a neutral tide never blocks a signal outright but caps its confidence. Weighted 30% of the confidence score -- the single largest component.',
        crossLinksTo: 'Stock Detail page → Signal Summary → Tide (Screen 1) help icon',
      },
      {
        id: 'weekly-macd-slope-informational',
        name: 'Weekly MACD-Histogram slope (superseded, kept as context)',
        citation: 'Elder, ch. 39, pp. 156-157 (the technique Weekly Impulse directly replaced)',
        summary:
          'The original standalone Screen 1 test: the weekly MACD-Histogram’s own last-step slope classification (rising/falling/flat), secondarily confirmed by the 13-week vs. 26-week EMA relationship.',
        elderContext:
          'No longer decides the Tide -- Weekly Impulse (above) does that now, per Elder’s own ch. 39 correction. Still exposed alongside `tide` purely as informational context, since it’s a cheap byproduct of the same weekly MACD-Histogram series.',
        appStatus: 'informational',
        appBehavior:
          'Exposed as `weekly_macd_histogram_slope` alongside `screens.tide` on the analysis response. Not read by any signal/confidence/risk logic.',
      },
    ],
  },
  {
    id: 'screen-2-wave',
    title: 'Screen 2 — The Wave (medium-term oscillators)',
    intro:
      'Purpose: within the tide’s direction, wait for a counter-trend dip/rally using oscillators, since oscillators give their best signals when they diverge from the dominant trend. If the tide is bullish, this app waits for a daily oversold pullback; if bearish, for a daily overbought rally (docs/Analyse.md §2).',
    entries: [
      {
        id: 'force-index',
        name: 'Force Index (2-day / 13-day EMA)',
        citation: 'Elder, ch. 30, docs/Analyse.md §2/§4 row 3',
        summary:
          'Volume × today’s price change, smoothed with a 2-period EMA (entry timing) and a 13-period EMA (trend confirmation). A negative spike in an uptrend is a buying opportunity; a positive spike in a downtrend is a selling opportunity.',
        elderContext:
          'Elder ch. 30 states the two spike directions are NOT equally reliable: "markets recoil from down spikes but not from up spikes... spikes that point down reflect intense fear, which doesn’t persist for very long. Spikes that point up reflect excessive enthusiasm and greed, which can persist for quite a long time." This app encodes that asymmetry with a statistically stricter threshold for a bearish/overbought spike than a bullish/oversold one (`backend-force-index-refinements`’s `decisions`).',
        appStatus: 'core_signal',
        appBehavior:
          'Feeds Screen 2’s pullback/rally classification directly, and its spike/volume behavior feeds the confidence score’s "oscillator extremity" (25%) and "volume confirmation" (10%) components.',
      },
      {
        id: 'force-index-reversal-spike',
        name: 'Force Index "5x usual depth" reversal spike',
        citation: 'Elder, ch. 30',
        summary:
          'A distinct, much simpler quantified cue from the same chapter: a 2-day-EMA down-spike at least 5x its own usual depth. The book gives no equivalent numeric up-spike version, consistent with the same directional-asymmetry claim above -- so this app only ever evaluates down-spikes for this specific rule.',
        elderContext:
          'A separate short-term reversal-timing signal from Screen 2’s own oversold-pullback classification above, not a restatement of it.',
        appStatus: 'informational',
        appBehavior:
          'Detected via `app.signals.triple_screen.is_force_index_reversal_spike` but not read by `_determine_signal`, the Impulse gate, or confidence scoring today.',
      },
      {
        id: 'stochastic',
        name: 'Stochastic Oscillator (%K 5, %D 3, smoothing 3)',
        citation: 'Elder, ch. 25-26, docs/Analyse.md §2/§4 row 4',
        summary: 'Below 30 = oversold, above 70 = overbought -- a classic momentum-timing oscillator.',
        elderContext:
          'One of Screen 2’s two primary oversold/overbought gauges (alongside Force Index), used to time entries against the Tide’s direction.',
        appStatus: 'core_signal',
        appBehavior:
          'Feeds Screen 2’s pullback/rally classification and the confidence score’s "oscillator extremity" component (25% weight, scaled by depth -- e.g. below 20 scores higher than below 30).',
        crossLinksTo: 'Stock Detail page → Oscillator chart',
      },
      {
        id: 'elder-ray',
        name: 'Elder-Ray Index (Bull Power / Bear Power)',
        citation: 'Elder, docs/Analyse.md §2/§4 row 5',
        summary:
          'Bull Power = High − EMA(13); Bear Power = Low − EMA(13). In an uptrend, a rising-but-still-negative Bear Power is a buy cue; in a downtrend, a falling-but-still-positive Bull Power is a sell cue.',
        elderContext: 'Measures the relative strength of buyers vs. sellers against the prevailing EMA(13) trend.',
        appStatus: 'core_signal',
        appBehavior:
          'Feeds Screen 2 and the confidence score’s "Elder-Ray confirmation" component (15% weight -- 100% if Bull/Bear Power confirm the exhaustion-then-reversal pattern).',
        crossLinksTo: 'Stock Detail page → Indicators panel',
      },
    ],
  },
  {
    id: 'screen-3-trigger',
    title: 'Screen 3 — The Trigger (entry timing)',
    intro:
      'Purpose: precise entry timing once Screens 1 & 2 align. Elder’s classic trigger is an intraday buy-stop one tick above the prior day’s high (or sell-stop one tick below the prior low). For a daily-bar app with no intraday feed, this is approximated as: today’s close crosses back above yesterday’s high (bullish trigger) or below yesterday’s low (bearish trigger) (docs/Analyse.md §2).',
    entries: [
      {
        id: 'trigger-breakout',
        name: 'Prior-day high/low breakout trigger',
        citation: 'Elder, docs/Analyse.md §2 Screen 3',
        summary: 'Confirms the pullback/rally has ended and the tide has resumed.',
        elderContext:
          'Screen 3 is deliberately the last and most mechanical of the three screens -- it fires or it doesn’t, with no partial credit.',
        appStatus: 'core_signal',
        appBehavior: 'BUY/SELL both require Trigger to have fired; it does not independently feed confidence.',
      },
    ],
  },
  {
    id: 'impulse-system',
    title: 'The Impulse System (daily gate)',
    intro:
      'Elder’s Impulse System colors each bar using the interaction of trend and momentum, and dictates what actions are allowed: Green (EMA(13) rising AND MACD-Histogram rising) = only buy or hold; Red (both falling) = only sell or hold; Blue (they disagree) = any action allowed, but weaker (docs/Analyse.md §3). Weekly Impulse is Screen 1 (Tide, above, ch. 39’s own correction) -- Daily Impulse is a distinct, additional gate layered on top (ch. 40), unaffected by that correction.',
    entries: [
      {
        id: 'daily-impulse-gate',
        name: 'Daily Impulse System (entry/exit gate)',
        citation: 'Elder, ch. 40, pp. 158-166',
        summary:
          'Computed on the daily chart. If daily Impulse is Red, a fresh BUY is not emitted even if Screens 1-3 otherwise line up -- confidence is capped or the signal is downgraded to HOLD instead. Mirror in reverse for a Green-gated SELL.',
        elderContext: 'Layered on top of Screen 1 being weekly Impulse -- a real, additional technique per the primary source, not something the weekly change supersedes.',
        appStatus: 'core_signal',
        appBehavior:
          'Directly gates which action `_determine_signal` is allowed to output, and feeds the confidence score’s "Impulse gate" component (20% weight).',
        crossLinksTo: 'Stock Detail page → Signal Summary → Impulse help icon',
      },
    ],
  },
  {
    id: 'confidence-scoring',
    title: 'Confidence Score (0–100%)',
    intro:
      'Confidence is a rule-based, weighted agreement score across the five components below -- explicitly not a statistical probability (docs/Analyse.md §6). Displayed with a Low (<40%)/Medium (40-70%)/High (>70%) band alongside the raw percentage. Every current value is explained live, next to where it’s shown, via the (?) help icon on each row of the Signal Summary panel on any Stock Detail page -- this section summarizes the fixed weighting only; see that live help for what a specific score means for a specific ticker right now.',
    entries: [
      {
        id: 'confidence-tide-alignment',
        name: 'Tide alignment — 30%',
        citation: 'docs/Analyse.md §6',
        summary: '100% if Tide agrees with the signal direction, 50% if Neutral, 0% if it contradicts the direction.',
        elderContext: 'The single largest weight, reflecting "never trade against the tide."',
        appStatus: 'core_signal',
        appBehavior: 'One of five weighted inputs summed into `confidence`.',
      },
      {
        id: 'confidence-impulse-gate',
        name: 'Impulse gate — 20%',
        citation: 'docs/Analyse.md §6',
        summary: '100% if Impulse color matches the signal direction, 40% if Blue, 0% if opposite.',
        elderContext: 'Reflects how strongly the Impulse gate itself endorses the direction already chosen.',
        appStatus: 'core_signal',
        appBehavior: 'One of five weighted inputs summed into `confidence`.',
      },
      {
        id: 'confidence-oscillator-extremity',
        name: 'Oscillator extremity (Screen 2) — 25%',
        citation: 'docs/Analyse.md §6',
        summary: 'Scaled by how deep into oversold/overbought territory Stochastic + Force Index are.',
        elderContext: 'A deeper extreme reads as a stronger counter-trend setup.',
        appStatus: 'core_signal',
        appBehavior: 'One of five weighted inputs summed into `confidence`.',
      },
      {
        id: 'confidence-elder-ray',
        name: 'Elder-Ray confirmation — 15%',
        citation: 'docs/Analyse.md §6',
        summary: '100% if Bull/Bear Power confirm the exhaustion-then-reversal pattern.',
        elderContext: 'A secondary confirming check, not a primary driver.',
        appStatus: 'core_signal',
        appBehavior: 'One of five weighted inputs summed into `confidence`.',
      },
      {
        id: 'confidence-volume',
        name: 'Volume confirmation — 10%',
        citation: 'docs/Analyse.md §6',
        summary: '100% if Force Index spike / trigger-bar volume is above its 20-day average.',
        elderContext: 'The smallest weight -- a confirming check that genuine participation, not a thin move, is behind the signal.',
        appStatus: 'core_signal',
        appBehavior: 'One of five weighted inputs summed into `confidence`.',
      },
    ],
  },
  {
    id: 'portfolio-risk',
    title: 'Portfolio-Level Rules (risk management overlay)',
    intro:
      'Elder is explicit that indicator signals alone are not enough -- money management decides whether/how much to act on a signal, and can force an exit even without an opposing indicator signal (docs/Analyse.md §7). Everything in this section is evaluated per-position or per-portfolio, independent of a fresh entry signal.',
    entries: [
      {
        id: 'two-percent-rule',
        name: '2% Rule',
        citation: 'Elder, docs/Analyse.md §7',
        summary: 'Never risk more than 2% of total account equity on a single trade (position size × distance to stop ≤ 2% of equity).',
        elderContext: 'Used to compute suggested position size on a fresh BUY and to flag existing oversized positions.',
        appStatus: 'risk_management',
        appBehavior: 'Computed by `app.portfolio.risk`, surfaced on the Portfolio page’s risk panel and per-position exit flags.',
        crossLinksTo: 'Portfolio page → Risk Panel',
      },
      {
        id: 'six-percent-rule',
        name: '6% Rule',
        citation: 'Elder ch. 51, docs/Analyse.md §7',
        summary:
          'Total risk for the current calendar month must not exceed 6% of account equity -- this month’s already-realized losses plus the risk currently open across all held positions.',
        elderContext: 'A portfolio-level circuit breaker, independent of any single position’s own signal.',
        appStatus: 'risk_management',
        appBehavior:
          '`total_open_risk_pct` sums realized losses (from the `closed_trades` table, populated on position deletion) plus open-position risk; a breach surfaces a portfolio-level warning.',
        crossLinksTo: 'Portfolio page → Risk Panel',
      },
      {
        id: 'safezone-stop',
        name: 'Protective Stop-Loss (SafeZone concept)',
        citation: 'Elder ch. 54, docs/Analyse.md §7',
        summary:
          'Recent swing low minus 2x (Elder’s own stated minimum) a volatility buffer built from average downside penetrations of a short EMA -- "placing your stop any closer would be self-defeating."',
        elderContext: 'Feeds the 2%/6% calculations above; a close below this stop is itself a SELL trigger for that position regardless of Screen 2/3 state.',
        appStatus: 'risk_management',
        appBehavior: 'Computed per held position (`app.portfolio.risk.protective_stop`) and shown per position.',
      },
      {
        id: 'profit-target',
        name: 'Profit Target (+ reward:risk ratio)',
        citation: 'Elder ch. 53/58, docs/Analyse.md §7',
        summary:
          'For a fresh BUY: current price + 30% of that day’s Autoenvelope/channel height (ch. 58’s "A"-target formula), or the nearest support/resistance zone above current price -- whichever is TIGHTER (closer to current price) is used.',
        elderContext:
          'Paired with a sanity check: potential reward should be at least 2x the risk to the same protective stop ("it seldom pays to risk a dollar to make a dollar"). BUY-only -- this app’s stop model is long-only, so there’s no symmetric SELL-side target.',
        appStatus: 'risk_management',
        appBehavior: 'Computed and shown alongside a fresh BUY signal (`profit_target` on the analysis response); not read back into the signal/confidence itself.',
        crossLinksTo: 'Stock Detail page → Signal Summary → Profit Target help icon',
      },
      {
        id: 'trade-grading',
        name: 'Trade Grading ("Is This an A-Trade?")',
        citation: 'Elder ch. 55, docs/Analyse.md §7',
        summary:
          'Once a position is closed, three exact formulas grade how much of what was realistically available got captured: Buy grade, Sell grade (each vs. that day’s own high/low), and Trade grade (gain as a fraction of the entry day’s channel height). ≥30% capture on the trade grade is an "A" trade.',
        elderContext: 'Grades the trader’s execution against the day’s own realistic range, not raw dollars/percent-return alone.',
        appStatus: 'risk_management',
        appBehavior: 'Computed per closed trade, exposed via the Trade Journal on the Portfolio page.',
        crossLinksTo: 'Portfolio page → Trade Journal',
      },
      {
        id: 'existing-position-exits',
        name: 'Existing-position exit flags',
        citation: 'docs/Analyse.md §7',
        summary:
          'A held position is flagged SELL/reduce if: price closes below its protective stop; its own risk alone exceeds the 2% rule; the portfolio-level 6% rule is breached and it’s a contributor; price reaches the upper channel band with Impulse turning Red; or the weekly Tide flips from Bullish to Bearish.',
        elderContext: 'Exits are risk-driven, not just signal-driven -- a position can be told to sell even without a fresh technical SELL entry signal.',
        appStatus: 'risk_management',
        appBehavior: 'Computed per held position and shown as exit flags on the Portfolio/Dashboard pages.',
      },
      {
        id: 'personal-breadth-proxy',
        name: 'Personal Breadth Proxy',
        citation: 'Elder ch. 34-36, docs/Analyse.md §7',
        summary:
          'True market breadth (New High-New Low Index, % above 50-day MA, Advance/Decline line) needs a broad ticker universe this app doesn’t fetch. As a cheap approximation, `GET /api/watchlist/breadth` aggregates the same Tide already computed for every ticker on the user’s own watchlist + portfolio into a BULLISH/BEARISH/NEUTRAL breakdown.',
        elderContext:
          'Elder: "general market trends are responsible for as much as half the movement in individual stocks" -- applies at this smaller, personal scale too, though it’s explicitly not a substitute for real broad-market breadth.',
        appStatus: 'informational',
        appBehavior: 'Shown as its own widget on the Watchlist page; not read back into any individual ticker’s signal/confidence.',
        crossLinksTo: 'Watchlist page → Personal Breadth card',
      },
    ],
  },
  {
    id: 'other-indicators',
    title: 'Other Indicators — Computed & Exposed, Not (Yet) Wired Into the Signal',
    intro:
      'Everything below is real, computed, hand-verified-against-the-book code in this app today -- it just doesn’t currently move the BUY/SELL/HOLD signal, the confidence score, or a portfolio risk rule. Each is exposed somewhere in the app (a chart overlay, a panel, an API field) as honest additional context, per Elder’s own emphasis on never relying on one tool alone -- but this app hasn’t (yet) decided how to fold each one into the load-bearing logic above. Every one of these is a natural, explicit follow-up the corresponding backend task intentionally left unimplemented.',
    entries: [
      {
        id: 'rsi',
        name: 'RSI (Relative Strength Index)',
        citation: 'Elder ch. 27, pp. 99-102, docs/Analyse.md §4 row 10',
        summary:
          '9-day, closing-price-only oscillator: RSI = 100 − 100/(1 + RS). Closing-price-only unlike Stochastic (which also reads high/low) -- Elder’s own side-by-side comparison calls it "less noisy," with signals that tend to emerge earlier.',
        elderContext: 'A distinct, additive oscillator alongside Stochastic/Force Index/Elder-Ray -- not a structural gap-filler.',
        appStatus: 'informational',
        appBehavior: 'Exposed as `rsi` on the analysis and indicator-history responses, drawn on the oscillator chart sharing Stochastic’s pane. Not wired into `_determine_signal`, the Impulse gate, or confidence scoring.',
        crossLinksTo: 'Stock Detail page → Oscillator chart → RSI help icon',
      },
      {
        id: 'divergence',
        name: 'Divergence Detection (MACD-H / Stochastic / RSI)',
        citation: 'Elder ch. 15/23/26/27, docs/Analyse.md §4 row 11',
        summary:
          'Price makes a new high/low while the indicator makes only a shallower extreme than its previous comparable one -- momentum losing steam before price turns. MACD-Histogram divergence additionally requires the histogram to cross its own zero centerline between the two extremes ("an absolute must for a true divergence").',
        elderContext: 'One of Elder’s strongest signal types -- ch. 39’s own Tide example calls a divergence the reason "the uptrend is very strong."',
        appStatus: 'informational',
        appBehavior:
          'Exposed as `divergence` on the analysis/indicator-history responses and drawn as connecting markers on both charts. Not wired into `_determine_signal`, the Impulse gate, or confidence scoring -- an explicit, intentional follow-up.',
        crossLinksTo: 'Stock Detail page → Price/Oscillator chart → Divergence help icon',
      },
      {
        id: 'support-resistance',
        name: 'Support/Resistance Zones',
        citation: 'Elder ch. 18, pp. 55-60, docs/Analyse.md §4 row 9',
        summary:
          'Horizontal congestion zones built from clustered swing-point closes, strength-scored by length/height/dollar-volume, that flip role when broken (old resistance → new support) and can be confirmed or flagged as a false breakout.',
        elderContext: 'False breakouts are "a specific, high-value trade setup" -- stop placement is explicit: near the failed move’s own extreme.',
        appStatus: 'informational',
        appBehavior:
          'Exposed as `support_resistance_zones` on the analysis response and drawn as shaded price-chart bands. NOT (yet) wired into Screen 1/2/3, the Impulse gate, confidence, or the protective-stop formula -- using a known zone to tighten that stop is an explicit follow-up left unimplemented.',
        crossLinksTo: 'Stock Detail page → Price chart → Support/Resistance zone markers',
      },
      {
        id: 'kangaroo-tail',
        name: 'Kangaroo Tail Pattern ("fingers")',
        citation: 'Elder ch. 20, pp. 65-67, docs/Analyse.md §4 row 13',
        summary:
          'A 3-bar OHLC reversal pattern: a single bar’s range ≥2.5x the 10-day average, protruding from a tight recent range, with the close retracing ≥50% back from the tip -- confirmed by the next bar continuing the reversal. Suggested stop: halfway through the tail.',
        elderContext: 'Completely separate from every EMA/oscillator-based technique above -- pure bar-range pattern recognition.',
        appStatus: 'informational',
        appBehavior: 'Exposed as `kangaroo_tail` on the analysis/indicator-history responses and drawn as chart markers. Not wired into `_determine_signal`, the Impulse gate, or confidence scoring.',
        crossLinksTo: 'Stock Detail page → Price chart → Kangaroo Tail markers',
      },
      {
        id: 'indicator-seasons',
        name: 'Indicator Seasons',
        citation: 'Elder ch. 32, pp. 122-124, docs/Analyse.md §4 row 12',
        summary:
          'A four-way Spring/Summer/Autumn/Winter classification of the daily MACD-Histogram’s slope × position-vs-centerline. Spring/Autumn (the just-crossed-the-centerline states) are the best entries -- precisely because they’re emotionally the hardest to act on.',
        elderContext: 'A more granular, 4-state read layered on top of the existing 3-state Impulse and Tide, without changing either.',
        appStatus: 'informational',
        appBehavior: 'Exposed as `season` on the analysis/indicator-history responses and shown as a badge. Purely informational -- not read by `_determine_signal`, the Impulse gate, or confidence scoring.',
        crossLinksTo: 'Stock Detail page → Indicators panel → Season badge',
      },
      {
        id: 'obv',
        name: 'On-Balance Volume (OBV)',
        citation: 'Elder ch. 29, pp. 107-112 (Joseph Granville), docs/Analyse.md §4 row 14',
        summary:
          'A cumulative running total: today’s full volume is added if close > prior close, subtracted if close < prior close. Only its pattern of highs/lows and divergence against price matters -- the absolute level is meaningless.',
        elderContext: 'A trading-range breakout of OBV ahead of a price breakout is itself a buy/sell cue.',
        appStatus: 'informational',
        appBehavior:
          'Exposed as `obv` on each point of the indicator-history response only (not the single-latest-bar analysis response, since a cumulative series in isolation is meaningless). Not wired into `_determine_signal`, the Impulse gate, or confidence scoring; OBV divergence detection is an explicit, separate unimplemented follow-up.',
        crossLinksTo: 'Stock Detail page → Volume indicators chart',
      },
      {
        id: 'accumulation-distribution',
        name: 'Accumulation/Distribution (A/D)',
        citation: 'Elder ch. 29, pp. 107-112 (Larry Williams), docs/Analyse.md §4 row 15',
        summary:
          '`(close − open) / (high − low) × volume`, cumulative running total -- more finely calibrated than OBV since it credits volume proportional to where the close landed within the day’s own range.',
        elderContext: 'Conceptually close to Elder-Ray (both read the open/close-vs-range relationship) but cumulative and volume-weighted where Elder-Ray isn’t -- a genuinely distinct indicator.',
        appStatus: 'informational',
        appBehavior: 'Exposed as `accumulation_distribution` on the indicator-history response only, same reasoning as OBV above. Not wired into signal/confidence.',
        crossLinksTo: 'Stock Detail page → Volume indicators chart',
      },
      {
        id: 'atr-directional-system',
        name: 'Average True Range (ATR) / Directional System (+DI/-DI/ADX)',
        citation: 'Elder ch. 24, pp. 89-94, docs/Analyse.md §4 row 16',
        summary:
          'ATR: trailing 13-day average True Range, a volatility measure. Directional System: +DI/-DI measure buying vs. selling pressure, ADX (13-day average of DX) is Elder’s own new-trend-detection tool -- a rise of 4 steps off its own low "rings a bell" on a new trend being born.',
        elderContext: 'Trust trend-following logic only while ADX is rising; an ADX downturn from above both DI lines is a take-partial-profits cue, not a reversal cue.',
        appStatus: 'informational',
        appBehavior:
          'Exposed as a nested `trend_strength` object (`atr`, `plus_di`, `minus_di`, `adx`) on the analysis/indicator-history responses and drawn on the Trend Strength chart. Not wired into `_determine_signal`, the Impulse gate, or confidence scoring -- Elder’s own trading rules for this data (long only while +DI > -DI, trust trend-following only while ADX rises) are an explicit, separate follow-up.',
        crossLinksTo: 'Stock Detail page → Trend Strength chart',
      },
      {
        id: 'channel-value-zone',
        name: 'Channel (Autoenvelope) & Value Zone',
        citation: 'Elder ch. 41 "Channel Trading Systems", pp. 166-172, docs/Analyse.md §4 row 6',
        summary:
          'A symmetrical % channel around EMA(13): Upper = EMA + coef·EMA, Lower = EMA − coef·EMA, tuned so the channel contains ~95% of recent price action. The zone between the fast (13) and slow (26) EMA is the "value zone."',
        elderContext: 'A stand-alone method Elder says can be combined with Triple Screen rather than replacing anything in it.',
        appStatus: 'risk_management',
        appBehavior:
          'Feeds the existing-position exit rule ("price reaches the upper channel band with Impulse turning Red") and the profit-target formula (above) internally; also exposed generally as `channel_upper`/`channel_lower` for any ticker and drawn on the price chart, alongside the shaded value zone. A genuinely dual-status item: risk-management-active via those two paths, but not read by the entry signal/confidence itself.',
        crossLinksTo: 'Stock Detail page → Price chart → Channel overlay help icon',
      },
      {
        id: 'earnings-dividend-dates',
        name: 'Earnings & Dividend Date Awareness',
        citation: 'Elder ch. 58 (Tradebill), p. 241',
        summary:
          'A BUY signal or open position gets an "earnings expected within 14 days" flag -- a nasty earnings surprise can gap straight through a technical stop, a risk no stop-loss formula protects against.',
        elderContext: 'The Tradebill’s very first data fields, before any technical analysis at all.',
        appStatus: 'informational',
        appBehavior: 'Exposed via `extended_data.earnings_within_warning_days` on the analysis response, shown on the Fundamental Data panel. Purely informational -- not wired into signal/confidence.',
        crossLinksTo: 'Stock Detail page → Fundamental Data panel',
      },
      {
        id: 'short-interest',
        name: 'Short Interest',
        citation: 'Elder ch. 37, pp. 146-148',
        summary: '`short_ratio` ("days to cover") and `short_percent_of_float` -- a rough measure of short-squeeze fuel.',
        elderContext: 'Extra buying pressure if short-sellers are forced to cover into a rally.',
        appStatus: 'informational',
        appBehavior: 'Exposed via `extended_data` on the analysis response, shown on the Fundamental Data panel. Not folded into confidence.',
        crossLinksTo: 'Stock Detail page → Fundamental Data panel',
      },
      {
        id: 'insider-transactions',
        name: 'Insider Transactions',
        citation: 'Elder ch. 37, p. 147',
        summary: 'Raw recent officer/director buy/sell filings.',
        elderContext: 'A cluster of 3+ buys or sells within a month is Elder’s own secondary signal worth noting.',
        appStatus: 'informational',
        appBehavior:
          'Only the raw filing list is exposed via `extended_data` today -- cluster *detection* isn’t computed (an explicit, separate follow-up).',
        crossLinksTo: 'Stock Detail page → Fundamental Data panel',
      },
    ],
  },
  {
    id: 'considered',
    title: 'Considered But Not (Yet) Implemented',
    intro:
      'Everything below is logged in docs/ideas.md -- reviewed against the book, in most cases fully specified enough to build -- but no code for it exists in this app yet. Recorded here so the full picture of "what Elder describes vs. what this app currently does" is honest and complete, not just a list of what’s already built.',
    entries: [
      {
        id: 'broad-market-breadth',
        name: 'True Broad-Market Breadth (NH-NL / % Above 50-day MA / Advance-Decline Line)',
        citation: 'Elder ch. 34-36, pp. 133-142',
        summary:
          'New High-New Low Index, % of stocks above their 50-day MA, and the cumulative Advance/Decline line, computed across a broad ticker universe (e.g. the full S&P 500) rather than only the user’s own watchlist/portfolio.',
        elderContext: '"General market trends are responsible for as much as half the movement in individual stocks."',
        appStatus: 'considered',
        appBehavior:
          'Not built -- judged too heavy for the payoff at this app’s current single-user scale (docs/Analyse.md §7). The Personal Breadth Proxy above (informational, already built) is the cheaper alternative currently shipped instead. Free constituent-list sources have already been identified if this is ever picked up.',
      },
      {
        id: 'adaptive-thresholds',
        name: 'Adaptive (percentile-based) overbought/oversold thresholds',
        citation: 'Elder ch. 25-27',
        summary:
          'Replace the fixed Stochastic/RSI 30/70 thresholds with a per-ticker, rolling-6-month 5th/95th-percentile calculation, recalibrated roughly quarterly -- "the same temperature levels mean different things in summer or winter."',
        elderContext: 'Elder’s own stated rule, not tied to one specific oscillator.',
        appStatus: 'considered',
        appBehavior:
          'Not built -- this app still uses fixed 30/70 thresholds everywhere. A real product trade-off (per-stock calibration makes cross-ticker comparison less apples-to-apples) is flagged in docs/ideas.md as worth weighing before committing.',
      },
      {
        id: 'trend-range-regime',
        name: 'Trend vs. Trading-Range Regime Detection',
        citation: 'Elder ch. 19, pp. 60-64',
        summary:
          'Markets spend most of their time in trading ranges, not trends -- a Neutral Tide isn’t a data gap, it’s the normal state, with its own "buy weakness/sell strength near range edges" tactic (the opposite of trend tactic). Detectable via "if a moving average hasn’t made a new high/low in a month, it’s probably ranging."',
        elderContext: 'A structurally different second trading mode, not just a new indicator -- explicitly flagged in docs/ideas.md as needing a real product decision, not just an implementation task.',
        appStatus: 'considered',
        appBehavior:
          'Not built -- this app treats a Neutral Tide as "nothing to do" today, with no range-bound tactic of its own. Stop width also doesn’t currently vary by regime.',
      },
      {
        id: 'nics-stop',
        name: '"Nic’s Stop" (second-lowest-low placement)',
        citation: 'Elder ch. 54, pp. 221-222',
        summary:
          'Place a stop just below the second-lowest low in the lookback window (not the single most extreme low) -- since everyone else’s stops cluster right at the obvious extreme, price tends to run there first before reversing.',
        elderContext: 'An alternative Elder actually prefers in his own worked examples over anchoring to the single lowest low.',
        appStatus: 'considered',
        appBehavior:
          'Not built -- the current protective-stop formula anchors to the single lowest low in its lookback window.',
      },
      {
        id: 'profit-protection-ratchet',
        name: 'Progressive Profit-Protection Ratchet ("cuffing the trade")',
        citation: 'Elder ch. 54, pp. 223-224',
        summary:
          'Once open profit reaches a pre-planned checkpoint (e.g. 30% of the profit target), move the stop to breakeven; as profit grows further, progressively lock in a growing fraction of it.',
        elderContext: '"As a trade moves in your favor, your remaining potential gain begins to shrink, while your risk... keeps increasing" -- the reward:risk ratio decays as a winner ages.',
        appStatus: 'considered',
        appBehavior: 'Not built -- the current stop is recomputed fresh from price action each time, never anchored to how far into profit a specific position already is.',
      },
      {
        id: 'trade-apgar',
        name: 'Trade Apgar (veto-capable per-strategy scoring)',
        citation: 'Elder ch. 58, pp. 238-241',
        summary:
          'A structurally different scoring pattern from this app’s weighted confidence sum: five yes/no/partial questions scored 0/1/2 each, summed to a max of 10, with a hard veto -- trade only if the total is ≥7 AND no single question scored zero.',
        elderContext: 'The all-or-nothing veto on a single zero is the key structural difference from a pure weighted sum -- this app’s confidence score has no equivalent hard-veto mechanism at the scoring level today (only Tide misalignment gates the signal structurally, upstream of scoring).',
        appStatus: 'considered',
        appBehavior: 'Not built. Most naturally paired with user-defined, named strategies (below) if/when multi-strategy support is ever added.',
      },
      {
        id: 'trade-journal-taxonomy',
        name: 'Named Strategies, Exit-Reason Taxonomy & 2-Month Follow-Up Review',
        citation: 'Elder ch. 55/57/59, pp. 225-247',
        summary:
          'Letting a user name/tag their own trading strategies, record a structured exit reason per closed trade (target hit, stop hit, "couldn’t stand the pain", "recognized junk trade after entry", etc.), and get a scheduled prompt to revisit a trade ~2 months after it closed with a full-hindsight retrospective note.',
        elderContext: 'Elder credits reviewing his own equity curve filtered to just the "couldn’t stand the pain" tag with convincing him to never trade without stops again.',
        appStatus: 'considered',
        appBehavior:
          'Not built -- the current Trade Journal (above) records the three grading formulas but no strategy tag, exit-reason taxonomy, or follow-up-review workflow.',
      },
      {
        id: 'consensus-sentiment',
        name: 'Consensus & Commitment Indicators (sentiment, put/call, COT)',
        citation: 'Elder ch. 37, pp. 142-148',
        summary:
          'Advisor/journalist sentiment polls (book’s own paid services have a free modern equivalent: the AAII Investor Sentiment Survey), the CBOE Put/Call Ratio, and CFTC Commitment of Traders reports (futures-only) -- contrarian "extreme reading" signals, distinct from technical price/volume analysis.',
        elderContext: 'A different category from everything else on this page -- crowd psychology/positioning, not price/volume math.',
        appStatus: 'considered',
        appBehavior: 'Not built. Free sourcing options for every one of these have already been identified in docs/ideas.md.',
      },
      {
        id: 'ibkr-data-provider',
        name: 'IBKR Data Provider (hourly bars, market scanner)',
        citation: 'docs/ideas.md (IBKR Client Portal Web API research)',
        summary:
          'An optional, secondary `DataProvider` via a locally-run IB Gateway, unlocking real intraday hourly bars (a genuine Screen 3 breakout trigger instead of the current daily-close approximation) and a broker-side market scanner (a real mechanism for broad-market breadth, above) -- not a replacement for the existing yfinance/Stooq chain.',
        elderContext: 'Directly reopens Elder’s own preferred ch. 39 Screen 3 technique (a genuine intraday buy-stop) as a real option, rather than only ever the daily-bar approximation this app currently uses.',
        appStatus: 'considered',
        appBehavior: 'Not built -- tracked on the task board as `backend-ibkr-data-provider` (state: planned).',
      },
      {
        id: 'volume-trend-confirmation',
        name: 'Volume-Trend Confirmation Rules (beyond Force Index)',
        citation: 'Elder ch. 28 "Volume", pp. 103-107',
        summary:
          'Plain volume-vs-its-own-2-week-average as its own independent confirming signal -- shrinking volume while a trend continues means it’s "ripe for reversal"; shrinking volume during a countertrend pullback signals the pullback is nearly spent.',
        elderContext: 'A distinct signal from Force Index (volume × price change) -- trend-relative volume behavior over the whole move, not just one bar.',
        appStatus: 'considered',
        appBehavior: 'Not built -- confidence scoring’s existing "volume confirmation" component only checks the single trigger bar’s volume against its 20-day average.',
      },
    ],
  },
]
