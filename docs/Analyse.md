# Analyse.md — Stock & Portfolio Signal Analysis

## 1. Intent

Build an application that:

1. Analyses individual stocks (price/volume history).
2. Analyses the user's current portfolio positions (entry price, size, current price).
3. Produces a **Buy / Sell / Hold** signal per stock.
4. Attaches a **confidence score (0–100%)** to each signal, reflecting how strongly the underlying indicators agree.

The analytical method is based on **Dr. Alexander Elder's methodology**, primarily from *Trading for a Living* and *Come Into My Trading Room* — the **Triple Screen Trading System**, combined with his **indicators** (Impulse System, Force Index, Elder-Ray) and **risk-management rules** (2% / 6% rules).

Elder's core idea: never rely on one indicator. Combine a **trend-following tool** (to establish direction) with **oscillators** (to time entries against that trend), and always filter trade size through **money-management rules**, independent of how good the signal looks.

---

## 2. Triple Screen Trading System (per-stock signal engine)

Elder's system uses three "screens" applied at different timeframes to filter out bad trades. We adapt it to three passes over the same instrument's data.

### Screen 1 — The Tide (long-term trend, weekly chart)

Purpose: determine the dominant market trend. **Never trade against the tide.**

- **Indicator: the weekly Impulse System color** (see §3 below, computed on the *weekly* chart
  instead of the daily one). **Verified against the primary source** (Elder ch. 39, "Triple
  Screen Trading System", *The New Trading for a Living*, 2014, pp. 156-157 — quoted in full in
  `docs/ideas.md`): "The original version of Triple Screen used the slope of weekly
  MACD-Histogram as its weekly trend-following indicator... After I invented the Impulse
  system... I began to use it for the first screen of Triple Screen." Elder's own words are
  explicit that the Impulse System **directly replaced** the plain weekly-MACD-Histogram-slope
  test as his main trend tool — it is not an addition alongside that test, and this app's Screen
  1 (`app.signals.triple_screen.evaluate_tide`) implements that replacement, not a reconciliation
  between the two (see the `backend-weekly-impulse-screen1` task's `decisions` entry for the full
  rationale). Weekly Impulse GREEN (EMA(13) and weekly MACD-Histogram(12,26,9) both rising
  bar-over-bar) → tide is bullish → only look for buy (long) signals on lower timeframes. Weekly
  Impulse RED (both falling) → tide is bearish → only look for sell/avoid signals. Weekly Impulse
  BLUE (the two disagree, or too little weekly history) → tide is neutral.
- **Superseded** (kept here for history only — no longer what `evaluate_tide` computes): the
  original standalone test was weekly MACD-Histogram slope, secondarily confirmed by the 13-week
  vs. 26-week EMA relationship (13 EMA above 26 EMA = uptrend). The weekly MACD-Histogram's own
  slope classification is still exposed alongside `tide` (see below) as informational context,
  but no longer decides it.

Output: `tide = BULLISH | BEARISH | NEUTRAL`, from the weekly Impulse color -> Tide mapping above
(GREEN → BULLISH, RED → BEARISH, BLUE → NEUTRAL — NEUTRAL reduces confidence, does not block
signal). Also exposes `weekly_macd_histogram_slope` (rising/falling/flat, the weekly
MACD-Histogram's own last-step classification) purely as informational context — see
`docs/architecture/API.md`'s `screens.tide` shape. This same per-ticker Tide trend, aggregated
across a user's whole watchlist+portfolio, is also what §7's "Personal breadth proxy"
subsection reports — kept there rather than here since it's a portfolio-level, multi-ticker
aggregate (see the `backend-watchlist-breadth-proxy-followups` task's `decisions` for why it
stays in §7 despite Tide itself being a Screen 1/§2 concept).

### Screen 2 — The Wave (medium-term, daily chart)

Purpose: within the tide's direction, wait for a counter-trend dip/rally (a "wave" against the "tide") using **oscillators**, since oscillators give the best signals when they diverge from the dominant trend.

- If tide is **bullish**: wait for daily oscillators to fall into **oversold** territory (a pullback) → potential buy.
- If tide is **bearish**: wait for daily oscillators to rise into **overbought** territory (a rally) → potential sell/short.

Indicators used:
- **Force Index** (2-day EMA) — `Force Index = Volume × (Close_today − Close_yesterday)`, smoothed with a 2-period EMA for short-term signals and 13-period EMA for trend confirmation. Negative spike in an uptrend = buying opportunity; positive spike in a downtrend = selling opportunity. A "spike" is a statistically outsized move against a trailing 13-bar window, not merely any negative/positive tick — and, per Elder ch. 30, **the two directions are not equally reliable**: "markets recoil from down spikes but not from up spikes... spikes that point down reflect intense fear, which doesn't persist for very long. Spikes that point up reflect excessive enthusiasm and greed, which can persist for quite a long time." This app encodes that asymmetry by requiring a statistically *stricter* threshold for a bearish/overbought-rally (up-)spike than a bullish/oversold-pullback (down-)spike (`app.signals.triple_screen._is_force_index_spike` — see `backend-force-index-refinements`'s `decisions` for the exact multipliers and rationale), rather than treating both directions identically. Separately, ch. 30 gives its own much simpler, explicitly-quantified short-term reversal cue — a down-spike **"5 times or more its usual depth"** — as a distinct signal from the Screen 2 classification above (`app.signals.triple_screen.is_force_index_reversal_spike`); the book gives no equivalent numeric rule for an up-spike version, consistent with the same directional-asymmetry claim, so this function only ever evaluates down-spikes.
- **Stochastic Oscillator** (%K 5, %D 3, smoothing 3) — below 30 = oversold, above 70 = overbought.
- **Elder-Ray Index**:
  - `Bull Power = High − EMA(13)`
  - `Bear Power = Low − EMA(13)`
  - In an uptrend, look for Bear Power to be negative but rising (weak dip) as a buy cue; in a downtrend, Bull Power positive but falling as a sell cue.

### Screen 3 — The Ripple (entry trigger, short-term/intraday)

Purpose: precise entry timing once Screens 1 & 2 align.

- **Elder's classic trigger:** a buy-stop placed one tick above the prior day's high (in an uptrend pullback), or a sell-stop one tick below the prior day's low (in a downtrend rally).
- For a daily-bar app (no intraday feed required), approximate with: **today's close crosses back above yesterday's high** (bullish trigger) or **below yesterday's low** (bearish trigger), confirming the pullback/rally has ended and the tide has resumed. This remains the default/swing-mode behavior (§10's "recommended for MVP" choice).
- **Day-trader mode** (`backend-day-trader-timeframe-mode-signal-engine`, ch. 39's own switchable-timeframe framing — see §2's intro and `docs/architecture/Backend.md` §10): once a user-configured long-term/intermediate/short-term timeframe triple is active, Screen 3 (`app.signals.triple_screen.evaluate_trigger`) is instead evaluated against the triple's own real short-term-timeframe bars (e.g. genuine 2-minute bars via IBKR intraday data) — Elder's *literal* buy-stop/sell-stop rule above, not the daily-bar approximation. The underlying comparison is identical either way (latest bar's close vs. the prior bar's high/low); only which bars are fed in changes what the result represents.

---

## 3. The Impulse System (signal state filter)

Elder's **Impulse System** colors each bar using the interaction of trend and momentum, and dictates what actions are *allowed*:

- **Green** — EMA(13) rising AND MACD-Histogram rising → only buy or hold allowed (no new shorts).
- **Red** — EMA(13) falling AND MACD-Histogram falling → only sell or hold allowed (no new buys).
- **Blue** — indicators disagree → any action allowed, but signal strength is weaker.

This app computes the Impulse System on **two separate timeframes, both per Elder ch. 39/40**
(pp. 156-166, `docs/ideas.md`), using the exact same color logic above on each:

- **Weekly** — computed on the weekly chart and used as **Screen 1 (Tide)'s own trend test**
  (see §2 above); this is the ch. 39 replacement of the original weekly-MACD-Histogram-slope
  test, not a second, separate weekly technique.
- **Daily** — computed on the daily chart and used as the entry/exit-timing **gate** ch. 40
  itself describes, layered on top of Screen 1: if daily Impulse is Red, do not emit a fresh
  Buy signal even if Screens 1-3 otherwise line up — cap confidence or downgrade to Hold
  instead. Same in reverse for Green-gated Sell signals during a Red-blocked setup. This daily
  gate is unaffected by the weekly-Impulse-is-Screen-1 correction above — it's a distinct,
  additional technique per the primary source, not something the weekly change supersedes.

---

## 4. Indicator Summary Table

| # | Indicator | Timeframe | Parameters | Role |
|---|-----------|-----------|------------|------|
| 1 | EMA | Weekly & Daily | 13, 26 | Trend direction (tide + impulse) |
| 2 | MACD / MACD-Histogram | Weekly & Daily | 12, 26, 9 | Trend momentum, slope for tide & impulse |
| 3 | Force Index | Daily | 2-EMA (entry), 13-EMA (trend) | Volume-weighted momentum, spike detection — directionally asymmetric (down-spikes more reliable than up-spikes, ch. 30); separate "5x usual depth" reversal cue, down-spike only |
| 4 | Stochastic Oscillator | Daily | %K 5, %D 3, smooth 3 | Overbought/oversold timing (Screen 2) |
| 5 | Elder-Ray (Bull/Bear Power) | Daily | EMA 13 | Strength of buyers vs sellers relative to trend |
| 6 | Autoenvelope (Channel) | Daily | EMA 13 ± avg % deviation | Profit-target / take-profit zone, overextension |
| 7 | Volume | Daily | raw + relative to 20-day avg | Confirms Force Index spikes, confirms breakouts |
| 8 | Prior day High/Low | Daily | — | Screen 3 entry trigger |
| 9 | Support/Resistance Zones | Daily | fractal swing clustering (see below) | Horizontal congestion-zone detection, strength scoring, false-breakout signal |
| 10 | RSI (Relative Strength Index) | Daily | 9-day, simple average | Closing-price-only oscillator, overbought/oversold timing (informational, alongside Stochastic) |
| 11 | Divergence Detection (MACD-Histogram / Stochastic / RSI) | Daily | 20–40-bar swing spacing, ≤50% second-extreme depth (Kerry Lovvorn's empirical filters) | Momentum-vs-price divergence, one of Elder's strongest signal types |
| 12 | Indicator Seasons (MACD-Histogram) | Daily | slope (rising/falling) × position vs. zero centerline | Four-way Spring/Summer/Autumn/Winter classification of trend maturity (informational only) |
| 13 | Kangaroo Tail Pattern ("fingers") | Daily | bar range ≥2.5× the 10-day average, ≥50% body retracement from the tip | 3-bar OHLC reversal pattern, confirmed by the next bar; suggested stop halfway through the tail |
| 14 | On-Balance Volume (OBV) | Daily | cumulative running total, no parameters | Volume-weighted momentum; cumulative-series pattern/divergence only (informational) |
| 15 | Accumulation/Distribution (A/D) | Daily | cumulative running total, no parameters | Volume weighted by close's position within the day's range; cumulative-series pattern/divergence only (informational) |
| 16 | Average True Range (ATR) / Directional System (+DI/-DI/ADX) | Daily | True Range, 13-day simple average throughout | Volatility (ATR) and trend strength/new-trend detection (+DI/-DI/ADX), each a meaningful single-bar value (informational) |

Optional/secondary (not required for MVP, note for future): Williams %R, SafeZone stops (volatility-based trailing stop using average of downside/upside penetrations).

Row 6 (Autoenvelope/Channel) already fed the §7 existing-position exit rule internally, but was otherwise invisible outside a held portfolio position until it was also exposed as `channel_upper`/`channel_lower` on `GET /api/stocks/{ticker}/analysis` and `GET /api/stocks/{ticker}/indicators` for *any* ticker — see `docs/architecture/API.md` for the response shape. No new math: both endpoints reuse this same EMA(13)-backed formula (see the `backend-channel-envelope-exposure` task's `decisions` for why EMA(13), not the book's own slower-EMA channel variant, was kept). Drawn on the price chart as of `frontend-channel-overlay`, alongside a shaded "value zone" between EMA13/EMA26 (ch. 41's own name for the zone between the fast and slow EMA) — see `docs/architecture/Frontend.md` §5. This table row/these two exposed endpoints stay Daily; the §7 "Profit target" section's own channel candidate is the one deliberate exception, computed on the **weekly** chart per ch. 39 p.161 — see that section for why.

Row 10 (RSI), Elder ch. 27: `RSI = 100 - 100/(1 + RS)`, `RS` = average of net up-closes over the trailing window ÷ average of net down-closes over the same window, using a plain/arithmetic rolling average (not Wilder's exponential smoothing — see `app.indicators.rsi.rsi` and the `backend-indicator-rsi` task's `decisions` for why). Closing-price-only, unlike Stochastic (which also reads high/low) — Elder's own side-by-side comparison calls RSI "less noisy," with signals that tend to emerge earlier. Window: **9 days** (the book's own 7-9-day range for sharper signals; see `decisions` for why 9 specifically was picked over 5/7/14). Exposed as `rsi` on `GET /api/stocks/{ticker}/analysis`'s `indicators` and on each point of `GET /api/stocks/{ticker}/indicators` — see `docs/architecture/API.md`. **Computation + exposure only**: not wired into `_determine_signal`, the Impulse gate, or confidence scoring, and not yet drawn on any chart. RSI divergence detection (see Row 11 below) is built on top of this indicator as of `backend-divergence-detection`.

Row 11 (Divergence Detection), Elder ch. 15/23/26/27: price makes a new high/low while the indicator makes only a *shallower* extreme than its previous comparable one — the trend is losing momentum even though price hasn't turned yet, one of the book's strongest signal types (ch. 39's own Tide example: "the uptrend is very strong because signal E came from a bullish divergence"). Detection algorithm (`app.signals.divergence`, see the `backend-divergence-detection` task's `decisions` for the full rationale):

1. **Swing points**: found on *price* (`close`) alone, via the shared `app.signals.swing_points` fractal detector (3-bar window each side, same default used elsewhere in this module) — the indicator's own value is then read at those same two dates, rather than independently detecting swing points on the indicator series itself.
2. **MACD-Histogram** (ch. 23) has one additional hard requirement: the histogram must cross its own zero centerline between the two compared extremes — "an absolute must for a true divergence" per the book; no crossover, no divergence at all (not merely a weaker one).
3. **Stochastic (ch. 26) and RSI (ch. 27)** get the simpler treatment: no centerline requirement, just a direct second-vs-first extreme comparison — strongest (`beyond_reference_line`, informational only) when the first extreme is beyond the oscillator's own overbought/oversold reference line (30/70) and the second is back inside it.
4. **Kerry Lovvorn's empirical refinement**, applied uniformly across all three indicators: the two compared extremes should be 20–40 bars apart (closer to 20 is better within that range), and the second extreme's own depth/height (measured from the indicator's centerline for MACD-Histogram, or its overbought/oversold reference line for Stochastic/RSI) should be no more than half the first's.
5. **"Hound of the Baskervilles"**: a formed divergence that price subsequently ignores (keeps moving in the "wrong" direction instead of the reversal the divergence implied) is itself a strong continuation signal in the opposite direction — Elder's one explicit stop-and-reverse case. Exposed as `aborted` — detected and exposed only; this app doesn't (yet) act on it.

Exposed on `GET /api/stocks/{ticker}/analysis` and `GET /api/stocks/{ticker}/indicators` as `divergence` (the single most recent qualifying divergence across whichever of MACD-Histogram/Stochastic/RSI currently has one — ties broken in MACD-Histogram's favor, then Stochastic, then RSI) — see `docs/architecture/API.md`. **Detection + exposure only**: not wired into `_determine_signal`, the Impulse gate, or confidence scoring — a natural, explicit follow-up this task intentionally left unimplemented.

Row 9 (Support/Resistance Zones), Elder ch. 18: a horizontal congestion zone is the price band where price repeatedly stalled — built from the *closing* prices of clustered swing highs/lows, not the single most extreme wick that happened to touch it once. Detection algorithm (`app.signals.support_resistance.detect_support_resistance_zones`, see the `backend-support-resistance` task's `decisions` for the full rationale — the book states the concept precisely but not a mechanical algorithm, so every parameter below is this app's own judgment call):

1. **Swing points**: a 5-bar fractal (today plus 2 bars each side) — a bar is a swing high if its `high` is the max of that window, a swing low if its `low` is the min.
2. **Clustering**: each swing point's own *close* price (sequential 1-D clustering, merging a point into the running cluster if within 1% of the cluster's mean) forms a candidate zone once it has ≥2 touches spanning ≥2 weeks (below that floor, not reported as a zone at all).
3. **Strength scoring**, per the book's three factors:
   - **Length**: minor ~2 weeks, intermediate ~2 months (60 days), major ~2 years (730 days) — the book's own thresholds, used as category boundaries directly.
   - **Height** (as % of the ticker's *current* price, not the zone's own touch-era price): minor ~1%, intermediate ~3%, major ≥7% — category boundaries set at the midpoints between the book's three anchor values (2%, 5%) so each anchor itself classifies as the book intends.
   - **Volume**: Elder's own explicit dollar-strength formula, `days-in-zone × average daily volume × average price` over the zone's touch span — exposed raw as `dollar_volume` (no absolute-value thresholds exist to classify it into minor/intermediate/major, unlike length/height).
   - `strength_score` (0–100) is a composite of the length and height categories only (not `dollar_volume`, for the reason above).
4. **Role-flipping**: once formed, a zone is scanned forward for a daily close beyond it. If price never closes back inside the zone within a 10-trading-day confirmation window, the break is confirmed: the zone's role flips (old resistance becomes new support, and vice versa) rather than the zone being discarded. At most one flip per zone is tracked by the current implementation (see `decisions`).
5. **False breakout**: if price *does* close back inside the zone within that same window, it's flagged as a false breakout instead of a confirmed break — role does not flip. `extreme_price` records the failed move's own extreme (its highest high, or lowest low) — Elder's explicit stop-placement reference: a stop belongs near that extreme, not further out.

Exposed on `GET /api/stocks/{ticker}/analysis` as `support_resistance_zones` (up to the 15 strongest zones by `strength_score`) — see `docs/architecture/API.md`. **Detection + scoring + false-breakout flagging + API exposure only**: zones are not (yet) wired into Screen 1/2/3, the Impulse gate, confidence scoring, or §7's `protective_stop()` formula — using a known zone to tighten that stop near support/resistance is an explicit, natural follow-up this task intentionally left unimplemented (see `decisions`). Drawn on the price chart as of `frontend-support-resistance-overlay`: a shaded horizontal band per zone (fill opacity weighted by `strength_score`, a dashed border for a zone whose role has flipped), plus a distinct marker and a dashed stop-price line at `extreme_price` for a zone's most recent false breakout — see `docs/architecture/Frontend.md` §5.

Row 12 (Indicator Seasons), Elder ch. 32 "Time" (pp. 122-124): a four-way classification of an oscillator's state, combining its bar-over-bar **slope** (rising/falling) with its **position relative to its own centerline** — stated generally in the book ("we can apply the concept of seasons to most indicators and timeframes"), applied here to the daily MACD-Histogram specifically, since its slope and centerline are already computed for the Impulse gate/`indicators.macd_histogram`:

| Slope | vs. centerline | Season | Elder's stated read |
|---|---|---|---|
| Rising | Below | Spring | Best time to go long |
| Rising | Above | Summer | Crowd-recognized uptrend; take profits on longs into strength |
| Falling | Above | Autumn | Best time to go short |
| Falling | Below | Winter | Crowd-recognized downtrend; cover shorts into weakness |

The book's own insight: Spring and Autumn — the *early*, still-just-crossed-the-centerline states — are explicitly called the best entries, precisely because they're emotionally the hardest to act on ("memories of the downtrend are still fresh" in Spring, so few traders buy even though it's the best risk/reward entry). Implementation (`app.signals.seasons.classify_season`): slope reuses the same bar-over-bar "rising iff latest > previous, tie counts as falling" convention as `app.signals.impulse._direction`; centerline position treats an exact zero as "below," not "above" (mirroring `app.signals.triple_screen`'s existing `sign * latest <= 0` treatment of zero as not-positive). Null only when fewer than 2 daily bars are available to compute a slope from.

Exposed as `season` on `GET /api/stocks/{ticker}/analysis`'s `indicators` and on each point of `GET /api/stocks/{ticker}/indicators` (a historical Spring/Summer/Autumn/Winter timeline) — see `docs/architecture/API.md`. **Purely informational**: this is a label layered on top of the already-computed MACD-Histogram series, not a new signal input — it is *not* read by `_determine_signal`, the Impulse gate, or confidence scoring, and gives a more granular 4-state read than the existing 3-state Impulse (Green/Red/Blue) or 3-state Tide (Bullish/Bearish/Neutral) without changing either.

Row 13 (Kangaroo Tail Pattern, "fingers"), Elder ch. 20 (pp. 65-67): a 3-bar OHLC reversal pattern, completely separate from every other row above — no EMA/oscillator/indicator series involved, just a bar-range-vs-recent-average-range comparison plus a confirming next bar. A single bar's range roughly 2-3x the recent average bar range, protruding from a tight recent range, where the close ends up back near the open (not at the extreme) — flanked by two bars of normal height. An upward-pointing tail (new high, closes back down) is a bearish reversal signal; a downward-pointing tail (new low, closes back up) is bullish. Detection algorithm (`app.signals.kangaroo_tail`, see the `backend-kangaroo-tail-pattern` task's `decisions` for the full rationale — the book states the shape precisely but no mechanical numbers, the same situation `app.signals.support_resistance` and `app.signals.kangaroo_tail`'s own sibling pattern-detection tasks were in):

1. **Baseline "average bar range"**: the mean `high - low` over the 10 trading days (~2 weeks) immediately preceding the candidate bar. A small baseline is itself what "protruding from a tight recent range" means here.
2. **Tail qualification**: the candidate's own range must be at least 2.5x that baseline (the midpoint of the book's own "roughly 2-3x") AND its high/low must be a genuine new extreme beyond the whole 10-day lookback window, not just wider than its own bars.
3. **Body position**: both the open and close must retrace at least 50% of the bar's own range back from the tip (the new high/low) — "the close ends up back near the open, not at the extreme".
4. **Flanked by two bars of normal height**: the bar immediately before AND immediately after the candidate must each themselves fail the range-multiplier test (reusing the same 2.5x threshold, not a second invented number).
5. **Confirming next bar**: that same next bar's close must also continue in the direction the reversal implies — below the tail's own close for an upward (bearish) tail, above it for a downward (bullish) one. This is a hard gate: a Kangaroo Tail is only ever detected/exposed once genuinely confirmed, mirroring MACD-Histogram divergence's own "no crossover, no divergence" precedent (Row 11) rather than exposed as an unconfirmed candidate with a boolean flag.

**Suggested stop**, per the book's own explicit rule ("halfway through the tail, not at its tip — too wide — or its base — too tight"): the tail bar's own range midpoint, `(high + low) / 2`.

Exposed as `kangaroo_tail` on `GET /api/stocks/{ticker}/analysis` and `GET /api/stocks/{ticker}/indicators` (the single most recently confirmed tail — same "current state" convention as `divergence`, Row 11) — see `docs/architecture/API.md`. **Detection + exposure only**: not wired into `_determine_signal`, the Impulse gate, or confidence scoring.

Rows 14-15 (On-Balance Volume / Accumulation-Distribution), Elder ch. 29 (pp. 107-112), developed respectively by Joseph Granville and Larry Williams — two volume-based indicators, both cumulative running totals whose absolute level is meaningless (it depends on however far back the underlying history happens to start): only their pattern of highs/lows and divergence against price matters, same as every other oscillator in this app (docs/ideas.md).

- **OBV** (`app.indicators.obv.obv`): today's full volume is added to the running total if close > prior close, subtracted if close < prior close, left unchanged if flat. The whole day's volume is credited to whichever side "won," however narrow the margin.
- **A/D** (`app.indicators.accumulation_distribution.accumulation_distribution`): `(close - open) / (high - low) * volume`, cumulative running total — more finely calibrated than OBV since it credits volume *proportional to where the close landed within the day's own range*, instead of the whole day's volume to whichever side won. Conceptually close to Elder-Ray (Row 5, both read the open/close-vs-range relationship) but A/D is cumulative and volume-weighted where Elder-Ray isn't — a genuinely distinct indicator, not a duplicate.

Edge cases (see this task's `decisions` entry, docs/tasks/backend-indicator-obv-ad.json, for the full rationale): OBV's first bar has no prior close to compare against, so its direction is undefined — mapped to a 0 contribution (the running total starts at 0) rather than left NaN, since NaN is "sticky" under a cumulative sum. A/D's zero-range bars (`high == low`) make that day's contribution a 0/0 division — also mapped to 0 for the same reason. Both series are therefore *never* null, unlike every other indicator in this table that has a warm-up period.

Exposed as `obv`/`accumulation_distribution` on each point of `GET /api/stocks/{ticker}/indicators` only — see `docs/architecture/API.md`. **Not** exposed on `GET /api/stocks/{ticker}/analysis`'s `indicators` (a single latest-bar snapshot): a cumulative series' current level in isolation is meaningless without the trailing history to compare it against, unlike `rsi`/`season` (Rows 10/12), which are meaningful single-bar values. **Computation + exposure only**: not wired into `_determine_signal`, the Impulse gate, or confidence scoring; divergence detection against OBV/A-D (also noted in docs/ideas.md) is an explicit, separate follow-up this task intentionally left unimplemented — it depends on `app.signals.swing_points`, the same building block `app.signals.divergence` already uses for MACD-Histogram/Stochastic/RSI (see the `backend-swing-point-detector` task).

Row 16 (Average True Range / Directional System), Elder ch. 24 (pp. 89-94) — the `backend-indicator-atr-adx` task. Two indicators sharing one building block, True Range: `TR = max(high - low, |high - prev_close|, |low - prev_close|)` (`app.indicators.atr.true_range`), NaN on the first bar (no prior close).

- **ATR** (`app.indicators.atr.atr`): the trailing 13-day simple/arithmetic average of True Range — a volatility measure, always ≥ 0. Not Wilder's smoothed moving average (see `decisions` for why a plain rolling mean was chosen, consistent with Row 10's RSI decision).
- **Directional System** (`app.indicators.directional_system`): `+DM`/`-DM` are the portion of today's high-low range extending beyond yesterday's, signed by direction (Wilder's standard construction: whichever of `high - prior high` / `prior low - low` is both positive and strictly larger than the other; a tie or an inside day counts as zero for both). `+DI`/`-DI` = 100 × (13-day average of `+DM`/`-DM`) ÷ (13-day average of True Range), each always ≥ 0. `DX = 100 × |+DI - -DI| / (+DI + -DI)`. `ADX` = 13-day average of `DX` — Elder's own new-trend-detection tool: trust trend-following logic only while ADX is rising, and a rise of 4 steps off its own low point (e.g. 9 → 13) specifically "rings a bell" on a new trend being born (docs/ideas.md). `ADX` warms up roughly twice as slowly as `ATR`/`+DI`/`-DI` (a further 13-bar window of `DX` on top of their own warm-up).

Exposed as a nested `trend_strength` object (`{atr, plus_di, minus_di, adx}`, each independently nullable during its own warm-up) on `GET /api/stocks/{ticker}/analysis`'s `indicators` and on each point of `GET /api/stocks/{ticker}/indicators` — see `docs/architecture/API.md` and this task's `decisions` for why `indicators.trend_strength` was chosen over nesting under `screens`. **Computation + exposure only**: not wired into `_determine_signal`, the Impulse gate, or confidence scoring — Elder's own trading/gating rules for this data (trade long only while `+DI > -DI`, trust trend-following only while ADX rises, an ADX downturn from above both DI lines as a take-partial-profits cue) are an explicit, separate methodology follow-up this task intentionally left unimplemented.

---

## 5. Signal Logic (Buy / Sell / Hold)

Per stock, evaluate in this order:

1. **Compute Tide** (Screen 1) → `BULLISH / BEARISH / NEUTRAL`.
2. **Compute Impulse** (daily) → `GREEN / RED / BLUE` — acts as a gate on which action is permitted.
3. **Compute Wave** (Screen 2 oscillators) → is price currently in a pullback (bullish tide) or rally (bearish tide)?
4. **Compute Trigger** (Screen 3) → has price resumed direction (crossed prior high/low)?

Resulting signal:

- **BUY**: Tide = BULLISH, Impulse ≠ RED, Wave shows/showed oversold pullback, Trigger fired (close > prior high).
- **SELL**: Tide = BEARISH, Impulse ≠ GREEN, Wave shows/showed overbought rally, Trigger fired (close < prior low).
- **HOLD**: conditions partially met, conflicting, or Neutral tide.

For **existing portfolio positions**, SELL is also evaluated independently of the entry logic above, via exit-specific rules (see §7) — a position can be told to sell even if a fresh "Sell" entry signal wouldn't otherwise fire, because exits are risk-driven, not just signal-driven.

---

## 6. Confidence Score (0–100%)

Confidence is a **weighted agreement score** across the indicators, not a statistical probability. Suggested weighting (tunable):

| Component | Weight | Scoring |
|---|---|---|
| Tide alignment (Screen 1) | 30% | 100% if Tide (the weekly Impulse color, §2/§3) agrees with the signal direction (Bullish for Buy / Bearish for Sell); 50% if Neutral (weekly Impulse Blue — the underlying EMA(13)/MACD-H directions disagree, or too little weekly history); 0% if Tide contradicts the signal direction |
| Impulse gate | 20% | 100% if Impulse color matches signal direction (Green for Buy / Red for Sell); 40% if Blue; 0% if opposite color (should have blocked signal already) |
| Oscillator extremity (Screen 2) | 25% | Scaled by how deep into oversold/overbought territory Stochastic + Force Index are (e.g., Stochastic < 20 scores higher than < 30) |
| Elder-Ray confirmation | 15% | 100% if Bull/Bear Power confirms the exhaustion-then-reversal pattern |
| Volume confirmation | 10% | 100% if Force Index spike / trigger bar volume is above 20-day average. **Day-trader mode** (`backend-day-trader-timeframe-mode-signal-engine`): unlike Screen 3 above, this component deliberately keeps reading the *intermediate*-leg's latest bar and 20-period rolling average for both halves of the OR — it is *not* switched to the short-term leg Trigger itself now evaluates against once a day-trader-mode timeframe triple is active. Swapping only the numerator to a short-term bar while the rolling-average denominator stayed intermediate-leg-scaled would compare two structurally incompatible magnitudes (a single finer-grained bar's volume is mechanically smaller than a coarser leg's rolling average), biasing this arm toward always reading "below average" rather than genuinely confirming anything — see `backend-day-trader-timeframe-mode-signal-engine-followups`'s `decisions` entry for the full rationale. |

`confidence = Σ(component_score × weight)`

Round to nearest whole percent. Suggested display bands: **<40% = Low**, **40–70% = Medium**, **>70% = High** — but always show the raw percentage, not just the band.

Note: this is a **rule-based composite score**, explicitly not a machine-learned probability — it should be documented as such to the user so it isn't misread as a statistical guarantee.

---

## 7. Portfolio-Level Rules (risk management overlay)

Elder is explicit that **indicator signals alone are not enough** — money management decides whether/how much to act on a signal, and can force an exit even without an opposing indicator signal.

### 2% Rule
Never risk more than 2% of total account equity on a single trade (position size × distance to stop-loss ≤ 2% of equity). Used to compute **suggested position size** when a fresh BUY signal fires, and to flag existing positions that are **oversized** relative to current equity.

### 6% Rule
Total risk for the current calendar month must not exceed 6% of account equity — this is a **two-part sum**: (1) this month's already-*realized* losses from closed trades, plus (2) the risk currently open across all held positions (sum of each position's distance-to-stop × size). If breached, the app should surface a **portfolio-level warning** and suggest which position(s) to trim/close first (e.g., weakest confidence score or largest individual risk contribution).

Implementation: `app.portfolio.risk.total_open_risk_pct` computes part (2) only; `app.portfolio.risk.realized_losses_pct` (combined with a `closed_trades`-table query in `app.api.routers.portfolio._realized_losses_this_month_pct`, since part (1) needs a DB query risk.py itself deliberately has no dependency on) computes part (1); `GET /api/portfolio/risk`'s `total_open_risk_pct` response field sums both. The `closed_trades` table (`ClosedTradeORM`, `app/db/models.py`) is populated by `DELETE /api/portfolio/positions/{id}` — see the `backend-trade-history-table` task's `decisions` for the full rationale, including why a realized loss is only counted for the position's own calendar month of *closure*, not spread across the trade's holding period.

### Stop-loss placement (SafeZone concept)
Stop-loss for a long position = recent swing low minus **2× (or more)** a volatility buffer (average size of downside penetrations of a short EMA over the last N days) — Elder's own words, "placing your stop any closer would be self-defeating" (ch. 54); this app uses the book's stated minimum of 2×, not a wider multiple (see the `backend-safezone-stop-coefficient-fix` task's `decisions` for why). This stop is what feeds the 2%/6% calculations above, and a **close below this stop is itself a SELL trigger** for that position regardless of Screen 2/3 state ("protective stop hit").

### Trailing/profit-protecting stop ("Don't Let a Winning Trade Turn into a Loss")
Ch. 54's companion subsection to the SafeZone stop above: as unrealized profit grows, move the stop to breakeven ("cuffing the trade") once profit crosses a threshold, then keep protecting a growing fraction of the profit earned beyond that point as it increases further (Elder's own worked example uses **a third**). Distinct from `protective_stop` above — a genuinely new stop-setting technique that reacts to how far a position has moved in its favor, not just current volatility.

The book states the *behavior* but neither number as a hard rule; this app's own judgment calls (see the `backend-trailing-profit-stop` task's `decisions`): breakeven triggers once unrealized profit reaches **10% of entry price**, and beyond that trigger the stop protects **1/3 of the profit earned past the trigger** (not total profit — this is what makes "crosses the threshold" and "moves to breakeven" the same event, with no discontinuity).

Companion principle, same chapter, **"Move Your Stop Only in the Direction of Your Trade"**: a stop must never be loosened once set, only tightened. This is enforced as a **hard ratchet** — `GET /api/portfolio/risk`'s `RiskPosition.trailing_stop` is guaranteed never lower than any value this endpoint has reported for that position before, even if a fresh computation from today's price alone would suggest a lower number. Two layers make that hold: `app.portfolio.risk.ratchet_trailing_profit_stop` re-folds this position's own full price history since entry on every call (new bars only ever accumulate, never revise away, so extending the fold can only hold the ratchet steady or raise it), floored by a **persisted** `PositionORM.trailing_stop_high_water_mark` — needed because the stateless fold alone isn't safe across `POST /api/portfolio/positions`'s same-ticker merge, which can raise `avg_cost_basis` (and so the breakeven trigger) with no price movement at all, letting a fresh recompute silently understate a value already earned under the OLD cost basis. That column is written *only* by the merge itself, against the position's pre-merge cost basis, right before it's overwritten — `GET /api/portfolio/risk` stays a pure read, only ever consulting the persisted floor, never advancing or persisting it — see `ratchet_trailing_profit_stop`'s and `trailing_stop_floor_before_merge`'s own docstrings and the task's `decisions` for the full history (including an earlier revision that had this GET route do the writing, reverted for violating HTTP GET's safe/idempotent contract). Before the breakeven trigger has ever fired, `trailing_stop` simply equals `protective_stop` (free to move either way with it) — there's no "winning trade" yet for this mechanic to protect.

Implementation: `app.portfolio.risk.trailing_profit_stop` (the single point-in-time formula), `app.portfolio.risk.ratchet_trailing_profit_stop` (the hard-ratchet wrapper wired into `GET /api/portfolio/risk`, alongside `protective_stop`), and `app.portfolio.risk.trailing_stop_floor_before_merge` (the persisted-floor write, wired into `POST /api/portfolio/positions`'s same-ticker-merge branch). **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`/exit flags, and independent of `protective_stop` — a trader is meant to consider both, not treat one as superseding the other.

### Profit target (suggested target + reward:risk ratio)
This app computes a signal, a confidence score, and a protective stop — but never a target price. Elder ch. 53 "How to Set Profit Targets" gives three style-dependent techniques; this app implements two of them (below). The third — a day-trade's first-sign-of-opposing-divergence exit — still isn't implemented even though day-trader (intraday) timeframe mode now exists: it addresses a *different exit signal* than the two techniques below, not a case of the value-zone/channel target technique becoming inapplicable once a trader's timeframes happen to be intraday. See `app.portfolio.profit_target`'s own docstring and the `backend-day-trader-timeframe-mode-portfolio-risk-followups` task's `decisions` entry for the full reasoning behind that gap. The two implemented techniques:
- **Swing-style**: ch. 58's own explicit Tradebill formula for an "A" target — current price + **30%** of a channel height (§4). Ch. 39 p.161 ("Stops and Profit Targets"), read directly: "Triple Screen calls for setting profit targets using long-term charts and stops on the charts of your intermediate timeframe... When buying a dip on a daily chart, the value zone on a weekly chart presents a good target." This app's intermediate timeframe is daily (Wave/Screen 2), long-term is weekly (Tide/Screen 1) — so **this channel height is computed from the weekly chart**, not the daily `channel_upper`/`channel_lower` this same ticker's `indicators` response reports for the price-chart overlay and entry-day trade grading (both explicitly daily, §4 Row 6, and independent of this computation) — the same 30% figure the trade-grading rubric above already uses for a ≥30%-of-channel-height capture, by design. The protective stop (above) correctly stays on daily data per this same rule — it's the intermediate-timeframe half of the split.
- **Position-style**: the nearest prior support/resistance level above current price (§4 Row 9) — stays daily; ch. 39's long-term-chart rule is specifically about the value-zone (channel) target, not this technique.

This app has no separate notion of "trade style" for a fresh signal — rather than inventing one, both techniques are always computed and the **tighter** (closer-to-current-price) of the two candidates is used, since a closer target is the more conservative, more probable one to actually be reached (see the `backend-profit-target` task's `decisions` for the full rationale, including why "tighter wins" rather than a fixed preference order).

Explicit, checkable sanity rule paired with the target: **potential reward should be at least 2× the risk** (distance to target ÷ distance to stop ≥ 2) — "it seldom pays to risk a dollar to make a dollar." The ratio is always computed and exposed, flagged via a boolean, not silently used to filter out a signal that fails it.

**Long-only, not BUY-only**: this app's protective-stop formula (and its whole portfolio model) is explicitly long-only (see "Stop-loss placement" above) — there's no symmetric short-side stop to pair with a SELL-side reward:risk ratio, so a **fresh-entry** `profit_target` is null for a SELL signal candidate. It's also null for a fresh BUY when neither technique currently produces a candidate (e.g. a young ticker with under ~100 weeks of weekly history and no yet-detected resistance zone above current price).

`suggest_profit_target` itself takes no signal at all and enforces no BUY-only gate internally — that gating is each *caller's* own choice, and the two callers now differ deliberately:
- `GET /api/stocks/{ticker}/analysis`'s `profit_target` (a **fresh-entry candidate**) is only ever computed when `signal` is BUY — null for HOLD and SELL, per the long-only constraint above.
- `GET /api/portfolio/risk`'s `RiskPosition.profit_target` (an **already-open position**) is computed regardless of that ticker's current live signal. Ch. 53, read directly, doesn't gate an open position's target to entry-day/fresh-signal only — "a target set at entry ... is meant to be tracked for the life of the trade, not recomputed only while the signal happens to say BUY." A held position is unconditionally a long trade with a real entry already behind it, independent of what today's technicals happen to read, so it keeps showing a target through HOLD and even a since-arrived SELL exit signal — see the `backend-profit-target-open-position` task's `decisions`, which revisits this section's original BUY-only decision for this exact case now that ch. 53's primary source has been read directly (previously the decision was made — and this section written — before that direct read, and applied the same BUY-only gate to both callers).

Implementation: `app.portfolio.profit_target.suggest_profit_target`, exposed as `profit_target` on both `GET /api/stocks/{ticker}/analysis` (computed directly in `get_analysis`) and `GET /api/portfolio/risk` (computed directly in `get_risk`, per position — see `docs/architecture/API.md`). Both callers reuse a fresh daily support/resistance pass over that ticker's own `daily_ohlcv` and compute the weekly Autoenvelope channel internally from `weekly_ohlcv` (a separate pass from the daily `channel_upper`/`channel_lower` `indicators` reported alongside it — see the `backend-profit-target-weekly-channel` task's `decisions`). **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`.

### Trade grading ("Is This an A-Trade?")
Once a position is closed (recorded in the `closed_trades` table above), grade it by three exact, checkable formulas (Elder ch. 55) rather than by raw dollars/percent-return alone — they measure how much of what was *realistically available* got captured, not just what was captured:
- **Buy grade** = (entry day's high − buy price) / (entry day's high − entry day's low) — how close to the entry day's low the buy was. **>50% is "very good."**
- **Sell grade** = (sell price − exit day's low) / (exit day's high − exit day's low) — how close to the exit day's high the sell was. **>50% is "very good."**
- **Trade grade** = (sell price − buy price) / (channel high − channel low, measured on the *entry* day) — the trade's actual gain as a fraction of the entry day's Autoenvelope/channel height (§4). **≥30% capture is an "A" trade, ~10% a "C" trade.**

Implementation: `app.portfolio.grading` (pure formulas, hand-verified against the book's own worked ADSK example — buy grade 97%, sell grade 35%, trade grade 32% — in `tests/unit/test_portfolio_grading.py`), exposed per closed trade via `GET /api/portfolio/closed-trades`. Any grade is `null` when its inputs aren't available for that trade (the ticker's fetched daily history doesn't reach back to the entry/exit date, or — trade grade only — the entry date falls inside the Autoenvelope's own ~100-bar warm-up window) rather than a fabricated number.

Elder's own framing of these grades is a **letter grade**, not a raw number ("A is excellent, B good, C mediocre, and D poor") — `trade_grade_pct` is additionally mapped to a letter (`trade_letter_grade`): `A` >= 30%, `B` in [20%, 30%), `C` in [10%, 20%), `D` < 10%. Only the A (30%) and C (10%) thresholds are ever stated numerically in the book; B and D fill that gap via even 10-point-per-letter spacing implied by those two anchors being exactly two letter-steps apart — see the `backend-trade-grade-letter` task's `decisions` for the full rationale. `buy_grade_pct`/`sell_grade_pct` stay percentage-only (no letter grade) since the book gives them only a single ">50% = very good" anchor each, with no letter scale attached.

### Trade Apgar (pre-trade go/no-go score)
Before entering a trade, ch. 58's "Trade Apgar" scores 5 questions 0/1/2 each against a *specific* trading strategy — Elder is explicit this test is strategy-specific ("the scoring method you're about to see is designed for one system... all other systems will require a different test"), so this app implements a single **fixed** question set matching Elder's own worked example strategy, not a per-strategy-configurable builder (a first version, not the eventual "real" shape — see the `backend-trade-apgar` task's `decisions`). Go/no-go rule: **total score ≥7 AND no single question scored 0** — both conditions required together, not just the sum.

Elder's own example strategy's five questions:
1. **Weekly Impulse** — Red=0, Green=1, Blue=2.
2. **Daily Impulse** — same scale.
3. **Daily price vs. value** — above value=0, in value zone=1, below value=2 (a strategy that buys weakness, so cheaper scores higher).
4. **False breakout status** — none=0, already happened=1, on the verge=2. Manual input.
5. **"Perfection"** (both timeframes look ideal) — neither=0, one=1, both=2 (Elder's own note: both being perfect is rare — one perfect plus one merely good is fine). Manual input.

Three of the five questions are auto-populated from data this app already computes for any ticker via `app.signals.engine.analyse()`: weekly/daily Impulse color (§3), and the daily price-vs-value classification against the EMA(13)/EMA(26) "value zone" (ch. 41 — distinct from the Autoenvelope/channel band `channel_upper`/`channel_lower` expose, even though both are drawn on the same price chart). False-breakout status and "perfection" stay manual inputs for this first version.

Implementation: `app.portfolio.trade_apgar` (pure scoring functions), exposed via `POST /api/portfolio/trade-apgar` (see `docs/architecture/API.md`) — stateless, nothing persisted.

### Existing-position exit signals (beyond fresh technical SELL)
A held position should be flagged **SELL/reduce** if any of:
- Price closes below its computed protective stop.
- Position risk alone exceeds the 2% rule (position has grown/equity has shrunk).
- Portfolio-level 6% rule is breached and this position is a contributor.
- Price reaches the upper Autoenvelope/channel band with Impulse turning Red (profit-taking zone in an overbought state).
- Tide flips from BULLISH to BEARISH on the weekly chart for a currently-long position.

### Personal breadth proxy (watchlist/portfolio Tide aggregate)
True market breadth (New High-New Low Index, % of stocks above their 50-day MA, the Advance/Decline line — Elder ch. 34-36) needs a broad ticker *universe* (e.g. the full S&P 500) to count new highs/lows or above-MA stocks across — this app only ever fetches data for tickers a user has explicitly added, never a broad market universe. Sourcing and refreshing such a universe was judged too heavy for the payoff at this app's current single-user scale (see `docs/ideas.md`'s ch. 34-36 entry, which weighs a real S&P 500 constituent list against this cheaper alternative).

As a cheap, no-new-data-source approximation, `GET /api/watchlist/breadth` aggregates the same Screen 1 (Tide) trend already computed for every ticker on the user's own watchlist **and** portfolio (union, deduplicated) into a BULLISH/BEARISH/NEUTRAL count/percentage breakdown. Elder's own justification for tracking broad breadth at all — "general market trends are responsible for as much as half the movement in individual stocks" (ch. 34) — applies just as well at this smaller, personal scale, even though it isn't a substitute for the real thing: this is explicitly a **personal** breadth proxy, reflecting only the tickers this particular user happens to be tracking, not the market as a whole (see the `frontend-breadth-widget` task for how this distinction is surfaced to the user).

`GET /api/watchlist/breadth` is its own separate request, so it only *reuses* the shared OHLCV cache (`app.data.cache.CachedDataProvider`) **when warm** — if one of `GET /api/watchlist`/`GET /api/portfolio` was hit recently enough that the cache TTL hasn't expired, no new provider fetch results for a ticker also tracked there; otherwise this endpoint does its own fetch, same as any other. The aggregate itself is computed fresh on every request rather than cached, matching those endpoints' own convention (see the `backend-watchlist-breadth-proxy` task's `decisions`). A tracked ticker whose Tide can't be computed right now is excluded from the counts/percentages and reported separately (`unavailable_count`) rather than guessed at.

`bullish_pct`/`bearish_pct`/`neutral_pct` are each rounded independently to 1 decimal place, so they don't always sum to exactly 100.0 (e.g. an even 3-way split rounds to 33.3 + 33.3 + 33.3 = 99.9) — each is still independently correct; this is a known, accepted display characteristic, not a bug (see the `backend-watchlist-breadth-proxy-followups` task's `decisions`).

### IBKR-scanner breadth approximation (real, broad-market NH-NL / Advance-Decline)

Unlike the personal breadth proxy above (which only ever looks at tickers the user already tracks), `POST /api/ibkr/breadth/snapshot` reaches for a genuinely broad market universe — but only when the optional IBKR Client Portal Gateway integration is enabled and available (`FINTRADE_IBKR_ENABLED`, `app.data.ibkr_provider.IBKRProvider`; unavailable otherwise, never an error, per the `backend-ibkr-status-endpoint`/`backend-market-scanner` tasks' established convention).

**Research finding this scope is built on** (`backend-market-breadth-indicators` task's `decisions` entry has the full writeup): `IBKRProvider.run_scanner`'s categories (52-week-high/low, top % gainers/losers, hot-by-volume, etc.) each return a bounded, ranked shortlist of individual matching contracts (this app's own `ScannerResult` model: one entry per contract, with a `rank`, and no aggregate/total-match-count field anywhere in the request or response contract) — not a genuine full-market count or percentage. That rules out a literal, book-defined computation of any of ch. 34-36's three indicators:

- **New High-New Low Index** needs a same-day count of every stock across NYSE+AMEX+NASDAQ making a new 52-week high/low, not a capped shortlist of the most extreme names.
- **Advance/Decline** needs a full-market count of every stock that closed up vs. down, not a ranked "top % gainers/losers" list.
- **Stocks above 50-Day MA** needs a true percentage (both a numerator *and* a known denominator across the whole market) — out of scope entirely, and unlike the other two, not even approximable this way: IBKR's predefined scan-type categories have no moving-average-relative category at all to begin with, not just a count-cap problem.

Per this app's own explicit product decision to *approximate* rather than compute the literal values (the `backend-market-breadth-indicators` task's own description), `count` (see `docs/architecture/API.md`'s `POST /api/ibkr/breadth/snapshot`) treats the number of contracts a single scan run returns as a crude, saturating proxy for "how many names are near an extreme right now" for whichever side (`series_key`) the caller is tracking (e.g. a new-highs-style scan vs. a new-lows-style scan for an NH-NL reading, or top-gainers vs. top-losers for an Advance/Decline reading) — **explicitly not comparable to ch. 34's own numeric thresholds** (weekly NH-NL ±4,000/+2,500, 20-day NH-NL −500), which assume real full-market magnitudes in the hundreds to thousands, far beyond what a single capped scan run can ever report. Those thresholds are documented here as illustrative context only — no reference-line field is exposed on the API response, and a consuming frontend should present this as a directional/trend signal (rising/falling, or which side currently has more names) rather than plotting it against the book's absolute numbers.

This app also doesn't hardcode which IBKR scan-type code corresponds to "new highs" vs. "new lows" (or "advancers" vs. "decliners") — the exact category codes are unconfirmed against a live gateway, the same reasoning `backend-market-scanner` already used to justify passing `GET /api/ibkr/scanner/params`'s category list through as-is rather than hand-curating it. The caller supplies both an opaque `series_key` label and the `scan_config` that produces it, and computes a spread (e.g. NH-NL ≈ `nh.rolling_5d - nl.rolling_5d`) itself from two labeled readings.

Ch. 34's own two rolling windows over the daily figure — "weekly NH-NL" (a 5-trading-day moving total) and "20-day NH-NL" (a rolling monthly look-back) — need an accumulated daily history, not a stateless per-request computation: `app.db.models.IBKRBreadthSnapshotORM` stores one row per `(series_key, calendar day)`, recorded at most once per day (a repeat request for a day already recorded is served from storage, not re-scanned), and `rolling_5d`/`rolling_20d` sum over that history.

---

## 8. Data Requirements

- **Per stock:** daily OHLCV history (minimum ~200 trading days, to seed 26-week/weekly EMA & MACD after resampling), resampled to weekly for Screen 1.
- **Per portfolio position:** ticker, quantity, average cost basis, entry date.
- **Account level:** total equity (cash + positions), used for 2%/6% rule calculations.
- Weekly bars can be derived from daily bars (resample, no separate feed needed).

---

## 9. Data Sources (free)

### Market data (daily/weekly OHLCV)

| Source | Free tier | Notes |
|---|---|---|
| **Yahoo Finance** (via `yfinance`) | Unlimited, no API key | Unofficial (scrapes Yahoo endpoints) — can break or get rate-limited without warning. Supports daily and weekly intervals natively (`interval='1wk'`), so weekly bars for Screen 1 don't need to be resampled manually. Best fit for MVP/personal use; riskier for a commercial product due to ToS ambiguity. |
| **Stooq** (stooq.com) | Unlimited, no API key | Plain CSV endpoints (`stooq.com/q/d/l/?s=TICKER&i=d`). Reliable, no auth friction — good fallback if Yahoo blocks/rate-limits. |
| **Tiingo** | Free w/ API key (~500 req/day, ~50 symbols/hr) | Official, stable EOD US equities API. Generous enough for a single-user portfolio refreshed daily. |
| **Alpha Vantage** | Free w/ API key (heavily rate-limited, ~25 req/day currently) | Fine for occasional/single-symbol pulls; too tight for a multi-ticker portfolio refreshed daily. |
| **Financial Modeling Prep** | Free w/ API key (limited calls/day) | Similar constraints to Alpha Vantage. |

~~IEX Cloud~~ — shut down in 2024; do not build against it.

**Recommendation:** `yfinance` as primary source, **Stooq as fallback** if Yahoo endpoints fail or rate-limit. Both are free and require no API key, which keeps the MVP simple. Revisit if usage grows enough that reliability/ToS become a concern — at that point a paid provider (Tiingo/Polygon/etc.) or a brokerage market-data feed would be the upgrade path.

### Extended data (earnings/dividend dates, short interest, insider transactions)

Confirmed available for free, live, via the same `yfinance` dependency used for OHLCV above — `Ticker.calendar` (earnings + dividend dates), `Ticker.info` (`sharesShort`/`shortRatio`/`shortPercentOfFloat`/`floatShares`), and `Ticker.insider_transactions` (buy/sell filings). Exposed via `GET /api/stocks/{ticker}/analysis`'s `extended_data` field (docs/architecture/API.md) — see that field's own description for the exact shape.

- **Earnings-date awareness** (ch. 58's Tradebill, p. 241): a BUY signal or open position gets an "earnings expected within 14 days" flag (`earnings_within_warning_days`) — a nasty earnings surprise can gap straight through a technical stop, a risk no stop-loss formula protects against. Purely informational: not wired into `signal`/`confidence` — a trader decides for themselves whether to skip/reduce a position ahead of an earnings date, this app doesn't auto-block one.
- **Short interest** (ch. 37, pp. 146–148): `short_ratio` ("days to cover") and `short_percent_of_float` are a rough measure of short-squeeze fuel — extra buying pressure if short-sellers are forced to cover into a rally. Exposure only, not folded into `confidence`.
- **Insider transactions** (ch. 37, p. 147): raw recent officer/director buy/sell filings (`extended_data.insider_transactions`), plus a computed cluster flag (`AnalysisResponse.insider_clusters`, `app.signals.insider_clusters`) — 3+ distinct insiders trading the same direction within a rolling 30-day window, Elder's own secondary signal ("several insiders buying (or selling) within a one-month period"). Each raw filing's free-text description is classified buy/sell/other first (option exercises, gifts, grants/awards, and tax-withholding dispositions are excluded as not genuine open-market conviction trades — see the backend-insider-transaction-clusters task's `decisions` entry for the exact rule); only classified buy/sell filings with a known insider name and date feed clustering. Purely informational, like the other two rows above — not wired into `signal`/`confidence`/portfolio risk.

The Stooq fallback provider has no equivalent to any of this (its plain CSV endpoint is OHLCV-only) — when Stooq is actively serving market data instead of yfinance, `extended_data.unavailable_reason` is set to `"fallback_provider_active"` rather than every field silently reading as null (which would be indistinguishable from "checked yfinance, found nothing").

### Portfolio position & account data

Not retrieved from a market data provider — this is the user's own data:

- **Manual entry / CSV import** — ticker, quantity, average cost basis, entry date, and cash balance entered or imported by the user. Simplest, zero integration cost, sufficient for MVP.
- **Brokerage API sync** (e.g., Alpaca, Interactive Brokers, Schwab) — future enhancement for automatic position/equity sync instead of manual upkeep. Adds OAuth/credential handling complexity — out of scope until the manual flow is validated.

---

## 10. Open Questions / Next Steps

- Confirm data source for OHLCV (e.g., a market data API) and rate limits.
- Screen 3 trigger: end-of-day only remains the default/swing-mode choice (recommended for MVP, given the "prior day high/low" approximation above) — **partially resolved** by `backend-day-trader-timeframe-mode-signal-engine`: day-trader mode now evaluates Screen 3 live against genuine intraday short-term-timeframe bars instead of approximating (see §2's own updated Screen 3 bullet); swing mode (this app's default/only mode in production) is completely unaffected.
- Decide the exact weighting table in §6 with backtested tuning once historical data is available — current weights are a reasonable starting default from Elder's own emphasis (trend > oscillators > confirmation), not empirically fit.
- Define what "total equity" means for the 2%/6% rules (cash-only brokerage account? include external assets?) — needs user input.
- Decide UI/output format for signals (dashboard, alerts, CLI report, etc.) — out of scope for this analysis doc.
