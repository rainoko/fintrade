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

Optional/secondary (not required for MVP, note for future): Williams %R, SafeZone stops (volatility-based trailing stop using average of downside/upside penetrations), Directional System / ADX for trend strength.

Row 6 (Autoenvelope/Channel) already fed the §7 existing-position exit rule internally, but was otherwise invisible outside a held portfolio position until it was also exposed as `channel_upper`/`channel_lower` on `GET /api/stocks/{ticker}/analysis` and `GET /api/stocks/{ticker}/indicators` for *any* ticker — see `docs/architecture/API.md` for the response shape. No new math: both endpoints reuse this same EMA(13)-backed formula (see the `backend-channel-envelope-exposure` task's `decisions` for why EMA(13), not the book's own slower-EMA channel variant, was kept).

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
Total open risk across all positions (sum of each position's distance-to-stop × size) must not exceed 6% of account equity in a given month. If breached, the app should surface a **portfolio-level warning** and suggest which position(s) to trim/close first (e.g., weakest confidence score or largest individual risk contribution).

### Stop-loss placement (SafeZone concept)
Stop-loss for a long position = recent swing low minus a volatility buffer (average size of downside penetrations of a short EMA over the last N days). This stop is what feeds the 2%/6% calculations above, and a **close below this stop is itself a SELL trigger** for that position regardless of Screen 2/3 state ("protective stop hit").

### Existing-position exit signals (beyond fresh technical SELL)
A held position should be flagged **SELL/reduce** if any of:
- Price closes below its computed protective stop.
- Position risk alone exceeds the 2% rule (position has grown/equity has shrunk).
- Portfolio-level 6% rule is breached and this position is a contributor.
- Price reaches the upper Autoenvelope/channel band with Impulse turning Red (profit-taking zone in an overbought state).
- Tide flips from BULLISH to BEARISH on the weekly chart for a currently-long position.

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
