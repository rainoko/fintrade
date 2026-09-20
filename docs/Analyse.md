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

- **Indicator:** Weekly MACD-Histogram (12, 26, 9) slope.
  - Histogram rising → tide is bullish → only look for buy (long) signals on lower timeframe.
  - Histogram falling → tide is bearish → only look for sell/avoid signals.
- **Secondary confirmation:** 13-week and 26-week EMA relationship (13 EMA above 26 EMA = uptrend).

Output: `tide = BULLISH | BEARISH | NEUTRAL` (neutral if MACD-H slope is flat/ambiguous — reduces confidence, does not block signal).

### Screen 2 — The Wave (medium-term, daily chart)

Purpose: within the tide's direction, wait for a counter-trend dip/rally (a "wave" against the "tide") using **oscillators**, since oscillators give the best signals when they diverge from the dominant trend.

- If tide is **bullish**: wait for daily oscillators to fall into **oversold** territory (a pullback) → potential buy.
- If tide is **bearish**: wait for daily oscillators to rise into **overbought** territory (a rally) → potential sell/short.

Indicators used:
- **Force Index** (2-day EMA) — `Force Index = Volume × (Close_today − Close_yesterday)`, smoothed with a 2-period EMA for short-term signals and 13-period EMA for trend confirmation. Negative spike in an uptrend = buying opportunity; positive spike in a downtrend = selling opportunity.
- **Stochastic Oscillator** (%K 5, %D 3, smoothing 3) — below 30 = oversold, above 70 = overbought.
- **Elder-Ray Index**:
  - `Bull Power = High − EMA(13)`
  - `Bear Power = Low − EMA(13)`
  - In an uptrend, look for Bear Power to be negative but rising (weak dip) as a buy cue; in a downtrend, Bull Power positive but falling as a sell cue.

### Screen 3 — The Ripple (entry trigger, short-term/intraday)

Purpose: precise entry timing once Screens 1 & 2 align.

- **Elder's classic trigger:** a buy-stop placed one tick above the prior day's high (in an uptrend pullback), or a sell-stop one tick below the prior day's low (in a downtrend rally).
- For a daily-bar app (no intraday feed required), approximate with: **today's close crosses back above yesterday's high** (bullish trigger) or **below yesterday's low** (bearish trigger), confirming the pullback/rally has ended and the tide has resumed.

---

## 3. The Impulse System (signal state filter)

Elder's **Impulse System** colors each bar using the interaction of trend and momentum, and dictates what actions are *allowed*:

- **Green** — EMA(13) rising AND MACD-Histogram rising → only buy or hold allowed (no new shorts).
- **Red** — EMA(13) falling AND MACD-Histogram falling → only sell or hold allowed (no new buys).
- **Blue** — indicators disagree → any action allowed, but signal strength is weaker.

Use this as a hard **gate**: if Impulse is Red, do not emit a fresh Buy signal even if Screen 2/3 line up — cap confidence or downgrade to Hold instead. Same in reverse for Red-gated Sell signals during Green impulse.

---

## 4. Indicator Summary Table

| # | Indicator | Timeframe | Parameters | Role |
|---|-----------|-----------|------------|------|
| 1 | EMA | Weekly & Daily | 13, 26 | Trend direction (tide + impulse) |
| 2 | MACD / MACD-Histogram | Weekly & Daily | 12, 26, 9 | Trend momentum, slope for tide & impulse |
| 3 | Force Index | Daily | 2-EMA (entry), 13-EMA (trend) | Volume-weighted momentum, spike detection |
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

Row 6 (Autoenvelope/Channel) already fed the §7 existing-position exit rule internally, but was otherwise invisible outside a held portfolio position until it was also exposed as `channel_upper`/`channel_lower` on `GET /api/stocks/{ticker}/analysis` and `GET /api/stocks/{ticker}/indicators` for *any* ticker — see `docs/architecture/API.md` for the response shape. No new math: both endpoints reuse this same EMA(13)-backed formula (see the `backend-channel-envelope-exposure` task's `decisions` for why EMA(13), not the book's own slower-EMA channel variant, was kept). Drawn on the price chart as of `frontend-channel-overlay`, alongside a shaded "value zone" between EMA13/EMA26 (ch. 41's own name for the zone between the fast and slow EMA) — see `docs/architecture/Frontend.md` §5.

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
| Tide alignment (Screen 1) | 30% | 100% if MACD-H slope & EMA13/26 agree strongly; 50% if mixed; 0% if tide contradicts the signal direction |
| Impulse gate | 20% | 100% if Impulse color matches signal direction (Green for Buy / Red for Sell); 40% if Blue; 0% if opposite color (should have blocked signal already) |
| Oscillator extremity (Screen 2) | 25% | Scaled by how deep into oversold/overbought territory Stochastic + Force Index are (e.g., Stochastic < 20 scores higher than < 30) |
| Elder-Ray confirmation | 15% | 100% if Bull/Bear Power confirms the exhaustion-then-reversal pattern |
| Volume confirmation | 10% | 100% if Force Index spike / trigger bar volume is above 20-day average |

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

### Profit target (suggested target + reward:risk ratio)
This app computes a signal, a confidence score, and a protective stop — but never a target price. Elder ch. 53 "How to Set Profit Targets" gives three style-dependent techniques; this app implements the two relevant to a swing/position-holding use case (the third — a day-trade's first-sign-of-opposing-divergence exit — doesn't apply, since this app has no intraday use case):
- **Swing-style**: ch. 58's own explicit Tradebill formula for an "A" target — current price + **30%** of that day's Autoenvelope/channel height (§4) — the same 30% figure the trade-grading rubric above already uses for a ≥30%-of-channel-height capture, by design.
- **Position-style**: the nearest prior support/resistance level above current price (§4 Row 9).

This app has no separate notion of "trade style" for a fresh signal — rather than inventing one, both techniques are always computed and the **tighter** (closer-to-current-price) of the two candidates is used, since a closer target is the more conservative, more probable one to actually be reached (see the `backend-profit-target` task's `decisions` for the full rationale, including why "tighter wins" rather than a fixed preference order).

Explicit, checkable sanity rule paired with the target: **potential reward should be at least 2× the risk** (distance to target ÷ distance to stop ≥ 2) — "it seldom pays to risk a dollar to make a dollar." The ratio is always computed and exposed, flagged via a boolean, not silently used to filter out a signal that fails it.

**BUY-only**: this app's protective-stop formula (and its whole portfolio model) is explicitly long-only (see "Stop-loss placement" above) — there's no symmetric short-side stop to pair with a SELL-side reward:risk ratio, so `profit_target` is null for a SELL signal (and for HOLD). It's also null for a BUY when neither technique currently produces a candidate (e.g. a young ticker with under ~100 days of history and no yet-detected resistance zone above current price).

Implementation: `app.portfolio.profit_target.suggest_profit_target`, exposed as `profit_target` on `GET /api/stocks/{ticker}/analysis` (see `docs/architecture/API.md`) — computed directly in `get_analysis`, reusing the already-computed channel bounds and support/resistance zones rather than recomputing either. **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`.

### Trade grading ("Is This an A-Trade?")
Once a position is closed (recorded in the `closed_trades` table above), grade it by three exact, checkable formulas (Elder ch. 55) rather than by raw dollars/percent-return alone — they measure how much of what was *realistically available* got captured, not just what was captured:
- **Buy grade** = (entry day's high − buy price) / (entry day's high − entry day's low) — how close to the entry day's low the buy was. **>50% is "very good."**
- **Sell grade** = (sell price − exit day's low) / (exit day's high − exit day's low) — how close to the exit day's high the sell was. **>50% is "very good."**
- **Trade grade** = (sell price − buy price) / (channel high − channel low, measured on the *entry* day) — the trade's actual gain as a fraction of the entry day's Autoenvelope/channel height (§4). **≥30% capture is an "A" trade, ~10% a "C" trade.**

Implementation: `app.portfolio.grading` (pure formulas, hand-verified against the book's own worked ADSK example — buy grade 97%, sell grade 35%, trade grade 32% — in `tests/unit/test_portfolio_grading.py`), exposed per closed trade via `GET /api/portfolio/closed-trades`. Any grade is `null` when its inputs aren't available for that trade (the ticker's fetched daily history doesn't reach back to the entry/exit date, or — trade grade only — the entry date falls inside the Autoenvelope's own ~100-bar warm-up window) rather than a fabricated number.

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

No new provider calls are needed — every one of these tickers' OHLCV is already fetched/analyzed for its own signal on `GET /api/watchlist`/`GET /api/portfolio`. The aggregate is computed fresh on every request rather than cached, matching those endpoints' own convention (only the underlying OHLCV fetch is cached, via `app.data.cache.CachedDataProvider` — see the `backend-watchlist-breadth-proxy` task's `decisions`). A tracked ticker whose Tide can't be computed right now is excluded from the counts/percentages and reported separately (`unavailable_count`) rather than guessed at.

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

### Portfolio position & account data

Not retrieved from a market data provider — this is the user's own data:

- **Manual entry / CSV import** — ticker, quantity, average cost basis, entry date, and cash balance entered or imported by the user. Simplest, zero integration cost, sufficient for MVP.
- **Brokerage API sync** (e.g., Alpaca, Interactive Brokers, Schwab) — future enhancement for automatic position/equity sync instead of manual upkeep. Adds OAuth/credential handling complexity — out of scope until the manual flow is validated.

---

## 10. Open Questions / Next Steps

- Confirm data source for OHLCV (e.g., a market data API) and rate limits.
- Decide whether Screen 3 trigger is evaluated live (intraday) or end-of-day only (recommended for MVP, given "prior day high/low" approximation above).
- Decide the exact weighting table in §6 with backtested tuning once historical data is available — current weights are a reasonable starting default from Elder's own emphasis (trend > oscillators > confirmation), not empirically fit.
- Define what "total equity" means for the 2%/6% rules (cash-only brokerage account? include external assets?) — needs user input.
- Decide UI/output format for signals (dashboard, alerts, CLI report, etc.) — out of scope for this analysis doc.
