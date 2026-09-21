"""Pydantic request/response models mirroring docs/architecture/API.md.

This module is the source of truth FastAPI generates /openapi.json from; the
frontend's api/types.ts should be generated from that schema, not hand-typed
(see docs/architecture/Frontend.md §5). Field descriptions here are what make
the generated OpenAPI schema self-explanatory — see CLAUDE.md's API
documentation standard.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Signal = Literal["BUY", "SELL", "HOLD"]
ConfidenceBand = Literal["Low", "Medium", "High"]
Interval = Literal["daily", "weekly"]
Trend = Literal["BULLISH", "BEARISH", "NEUTRAL"]
Impulse = Literal["GREEN", "RED", "BLUE"]
Season = Literal["Spring", "Summer", "Autumn", "Winter"]


# --- /api/stocks/{ticker}/history ---------------------------------------


class OHLCVBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class HistoryResponse(BaseModel):
    ticker: str
    interval: Interval
    bars: list[OHLCVBar]


# --- /api/stocks/{ticker}/analysis --------------------------------------


class TideScreen(BaseModel):
    trend: Trend = Field(description="Screen 1 output (docs/Analyse.md §2/§3): the weekly Impulse System color (EMA(13) direction + MACD-Histogram direction, both on the weekly chart) mapped onto BULLISH/BEARISH/NEUTRAL -- GREEN->BULLISH, RED->BEARISH, BLUE (the two disagree, or too little history)->NEUTRAL. Per Elder ch. 39, this replaced the original standalone weekly-MACD-Histogram-slope-plus-13/26-week-EMA test as Screen 1's own trend tool.")
    weekly_macd_histogram_slope: Literal["rising", "falling", "flat"] = Field(description="The weekly MACD-Histogram's own last-step classification -- informational context only as of docs/Analyse.md §2's ch. 39 correction; it no longer decides `trend` above (weekly Impulse's own EMA(13)/MACD-Histogram direction check does).")


class WaveScreen(BaseModel):
    stochastic_k: float = Field(description="Stochastic %K (5,3,3). Values below 30 are oversold, above 70 are overbought (docs/Analyse.md §4).")
    force_index_2ema: float = Field(description="Force Index, 2-period EMA smoothing (entry-timing variant, not the 13-period trend-confirmation one).")
    state: str = Field(description="Human-readable wave state, e.g. 'OVERSOLD_PULLBACK' — evaluated against the tide direction, not in isolation (docs/Analyse.md §2). Reflects only TODAY's bar -- see showed_pullback_in_lookback/showed_rally_in_lookback below for whether the qualifying state appeared on an earlier day within the signal's own lookback window.")
    showed_pullback_in_lookback: bool | None = Field(description="Whether Screen 2 showed OVERSOLD_PULLBACK on any of the last 5 trading days (today inclusive), not just today -- docs/Analyse.md §5's 'Wave shows/showed oversold pullback' language, and the exact condition `_determine_signal` (backend/app/signals/engine.py) gates a fresh BUY on (see `_wave_lookback`'s own docstring). A BUY can therefore occur even when `state` above isn't OVERSOLD_PULLBACK today, if it was on an earlier day within the window -- this field is what lets a client (e.g. a signal explanation) distinguish that case from the condition never having been met at all. Null when `screens.tide.trend` is NEUTRAL, since Wave is evaluated against a tide direction that doesn't exist in that case -- neither this nor showed_rally_in_lookback is ever reachable, so `False` would misleadingly read as 'checked, and it didn't happen' rather than 'not applicable'.")
    showed_rally_in_lookback: bool | None = Field(description="Same as showed_pullback_in_lookback, mirrored for OVERBOUGHT_RALLY / the SELL side (what `_determine_signal` gates a fresh SELL on). Exactly one of these two fields is ever the 'reachable' one for a given non-Neutral tide (BULLISH -> only showed_pullback_in_lookback can be true; BEARISH -> only showed_rally_in_lookback can be true) -- the other is `False`, not null, since that's itself a real (if structurally guaranteed) fact about this tide, not a not-applicable case.")


class TriggerScreen(BaseModel):
    fired: bool = Field(description="Whether Screen 3 confirmed price has resumed the tide's direction.")
    reference: str = Field(description="Which trigger rule fired, e.g. 'close_above_prior_high'.")


class Screens(BaseModel):
    tide: TideScreen
    impulse: Impulse = Field(description="Impulse System gate (docs/Analyse.md §3). RED blocks fresh BUY signals, GREEN blocks fresh SELL signals.")
    wave: WaveScreen
    trigger: TriggerScreen


class ConfidenceBreakdownItem(BaseModel):
    component: str = Field(description="One of the five weighted components from docs/Analyse.md §6, e.g. 'tide_alignment'.")
    weight: float = Field(description="This component's fixed weight (0-1); all five weights sum to 1.0.")
    score: float = Field(description="How strongly this component supports the signal (0-1), before weighting.")


class TrendStrength(BaseModel):
    atr: float | None = Field(
        default=None,
        description="Average True Range (docs/Analyse.md §4, Elder ch. 24) -- the 13-day "
        "simple/arithmetic rolling average of True Range (`max(high - low, "
        "|high - prev_close|, |low - prev_close|)`, `app.indicators.atr.true_range`), not "
        "Wilder's smoothed moving average (see `app.indicators.atr.atr`'s own docstring and "
        "the backend-indicator-atr-adx task's `decisions` entry). A volatility measure, not a "
        "directional one -- always >= 0. Null for the first 13 trading days of a ticker's "
        "history (needs 13 True Range values, itself needing a prior close). Computation + "
        "exposure only here -- not used for stop distance/profit targets/entry depth "
        "(docs/ideas.md's own numeric usage rules for this value), which is explicitly out "
        "of scope for the task that added this field.",
    )
    plus_di: float | None = Field(
        default=None,
        description="+DI (docs/Analyse.md §4, Elder ch. 24) -- the 13-day smoothed +DM "
        "(the portion of today's high extending beyond yesterday's high) as a percentage of "
        "similarly smoothed True Range (`app.indicators.directional_system.plus_minus_di`). "
        "Always >= 0. Null under the same warm-up condition as `atr` (needs the same 13-bar "
        "window over the same underlying True Range/+DM series).",
    )
    minus_di: float | None = Field(
        default=None,
        description="-DI, mirrored from `plus_di` using -DM (the portion of today's low "
        "extending beyond yesterday's low) instead of +DM. Always >= 0. Elder's own trading "
        "rule (docs/ideas.md, out of scope for the task that added this field): trade long "
        "only while `plus_di > minus_di`, short only while the reverse. Null under the same "
        "condition as `plus_di`.",
    )
    adx: float | None = Field(
        default=None,
        description="ADX (docs/Analyse.md §4, Elder ch. 24) -- `DX = 100 * |plus_di - "
        "minus_di| / (plus_di + minus_di)`, itself further smoothed over a trailing 13-day "
        "simple average (`app.indicators.directional_system.adx`). Elder's headline "
        "new-trend-detection tool: only trust trend-following logic while ADX is rising, and "
        "a rise of 4 steps off its own low point (e.g. 9 -> 13) specifically signals a new "
        "trend being born (docs/ideas.md) -- neither rule is evaluated by this app "
        "(computation + exposure only). Null for longer than `plus_di`/`minus_di`/`atr` -- "
        "needs a further 13-bar window of `DX` on top of their own warm-up, roughly twice as "
        "long overall.",
    )


class Indicators(BaseModel):
    ema_13: float
    ema_26: float
    macd_histogram: float
    bull_power: float = Field(description="Elder-Ray Bull Power = High - EMA(13).")
    bear_power: float = Field(description="Elder-Ray Bear Power = Low - EMA(13).")
    channel_upper: float | None = Field(
        default=None,
        description="Upper Autoenvelope/channel band (docs/Analyse.md §4: 'EMA 13 ± avg % "
        "deviation') -- `app.indicators.autoenvelope.autoenvelope`'s `mid * (1 + avg_pct)`, "
        "where `mid` is this same response's `ema_13`. This is the exact band "
        "`app.portfolio.exits.evaluate_exit_flags` already tests against internally for the "
        "'price reaches the upper Autoenvelope band with Impulse turning Red' existing-"
        "position exit rule (docs/Analyse.md §7), now exposed for any ticker rather than only "
        "a held portfolio position. Null for the first ~100 trading days of a ticker's history "
        "(the rolling deviation-average window isn't yet full) -- a much longer warm-up than "
        "any other field here, so this is null far more often than "
        "`ema_13`/`ema_26`/`macd_histogram`/`bull_power`/`bear_power`, which only need up to "
        "26 bars.",
    )
    channel_lower: float | None = Field(
        default=None,
        description="Lower Autoenvelope/channel band, same definition/source/warm-up as "
        "`channel_upper` mirrored to `mid * (1 - avg_pct)`.",
    )
    rsi: float | None = Field(
        default=None,
        description="Relative Strength Index (docs/Analyse.md §4, Elder ch. 27) -- "
        "`100 - 100 / (1 + RS)`, RS = average net up-close / average net down-close over a "
        "9-day window (simple/arithmetic rolling average, not Wilder's smoothed variant -- "
        "see `app.indicators.rsi.rsi`). Closing-price-only, unlike `stochastic_k` (which also "
        "reads high/low) -- Elder's own selling point for it: less noisy, signals tend to "
        "emerge earlier. Computation + exposure only; not currently wired into "
        "`screens`/`confidence_breakdown` (see the backend-indicator-rsi task). Null for the "
        "first 9 trading days of a ticker's history (needs 9 daily closing changes) -- a much "
        "shorter warm-up than `channel_upper`/`channel_lower`.",
    )
    season: Season | None = Field(
        default=None,
        description="'Indicator Seasons' (docs/Analyse.md, Elder ch. 32) -- a four-way "
        "classification of `macd_histogram`'s bar-over-bar slope combined with its position "
        "relative to its own zero centerline: Spring (rising, below -- best time to go long), "
        "Summer (rising, above -- crowd-recognized uptrend, take profits on longs into "
        "strength), Autumn (falling, above -- best time to go short), Winter (falling, below "
        "-- crowd-recognized downtrend, cover shorts into weakness). Purely informational -- "
        "not wired into `screens`/`confidence_breakdown` (see the backend-indicator-seasons "
        "task). Null only when there are fewer than 2 daily bars available to compute a "
        "slope from.",
    )
    trend_strength: TrendStrength = Field(
        description="Directional System / ADX (docs/Analyse.md §4, Elder ch. 24) -- always "
        "present as an object, but every one of its own fields is independently nullable "
        "during its own warm-up window (see `TrendStrength`'s own field descriptions), the "
        "same shape convention as this `Indicators` object itself. Purely informational -- "
        "not wired into `screens`/`confidence_breakdown` (see the backend-indicator-atr-adx "
        "task's own explicit scope note: Elder's usage rules for this data -- trade "
        "trend-following only while ADX rises, a 4-step rise off its own low 'rings a bell' "
        "on a new trend -- are a separate methodology decision, not indicator plumbing).",
    )


class FalseBreakoutOut(BaseModel):
    direction: Literal["up", "down"] = Field(description="Which way price broke before failing back inside the zone -- 'up' through the upper edge, 'down' through the lower edge.")
    breakout_date: date = Field(description="First date price closed beyond the zone.")
    reentry_date: date = Field(description="First subsequent date price closed back inside [lower, upper] -- what confirms the breakout was false, per docs/ideas.md's Elder ch. 18 note.")
    extreme_price: float = Field(description="The failed move's own extreme reached between breakout_date and reentry_date (the highest high for an 'up' false breakout, the lowest low for 'down') -- the book's explicit stop-placement reference: place a stop near this extreme, not further out.")


class SupportResistanceZone(BaseModel):
    role: Literal["support", "resistance"] = Field(description="Current role. A zone keeps existing with an inverted role after a confirmed (non-false) breakout rather than being discarded -- resistance price has since broken above and held becomes support, and vice versa.")
    upper: float = Field(description="Upper edge of the horizontal congestion zone -- built from the clustered swing points' own closing prices, not the single most extreme high/low wick.")
    lower: float = Field(description="Lower edge, mirrored.")
    first_touch_date: date = Field(description="Date of the earliest swing point clustered into this zone.")
    last_touch_date: date = Field(description="Date of the most recent swing point clustered into this zone.")
    touch_count: int = Field(description="Number of swing points clustered into this zone (always >= 2).")
    length_days: int = Field(description="Calendar days between first_touch_date and last_touch_date.")
    length_category: Literal["minor", "intermediate", "major"] = Field(description="Elder ch. 18's length-based strength factor: minor ~2 weeks, intermediate ~2 months, major ~2 years.")
    height_pct: float = Field(description="Zone height (upper - lower) as a percentage of the ticker's current (latest) close.")
    height_category: Literal["minor", "intermediate", "major"] = Field(description="Elder ch. 18's height-based strength factor: minor ~1%, intermediate ~3%, major >=7% of current price.")
    dollar_volume: float = Field(description="Elder's own dollar-strength formula: days-in-zone x average daily volume x average price, over the zone's own touch span. Informational only -- not folded into strength_score, since the book gives no absolute dollar-value thresholds to classify it against.")
    strength_score: float = Field(description="0-100 composite of length_category and height_category only (see dollar_volume's own description for why). A rule-based composite, like `confidence` (docs/Analyse.md §6) -- not a statistical probability.")
    broken: bool = Field(description="Whether a daily close has confirmed a permanent break beyond this zone (a true breakout, distinct from false_breakout below) since its last touch -- role has already flipped to the opposite of its original side in that case.")
    break_date: date | None = Field(default=None, description="Date of the confirmed break. Null if never broken.")
    false_breakout: FalseBreakoutOut | None = Field(default=None, description="The most recent false-breakout episode detected for this zone (docs/ideas.md, Elder ch. 18: price closes beyond the zone, then closes back inside it -- a specific, high-value reversal signal). Null if none detected. Can be non-null even when broken is also true, if an earlier false breakout was followed by a later, separate breakout that did hold.")


class DivergenceOut(BaseModel):
    kind: Literal["bullish", "bearish"] = Field(description="Which way the divergence points -- 'bullish' from two successive price swing LOWS (a potential buy setup), 'bearish' from two successive swing HIGHS (a potential sell setup). Elder ch. 15/23/26/27, docs/ideas.md.")
    indicator: Literal["macd_histogram", "stochastic", "rsi"] = Field(description="Which oscillator this divergence was detected against -- MACD-Histogram (the book's usual choice, and the only one of the three with a centerline-crossing requirement), Stochastic %K, or RSI.")
    first_extreme_date: date = Field(description="Date of the earlier of the two compared price swing points.")
    first_extreme_price: float = Field(description="Price (close) at first_extreme_date.")
    first_extreme_indicator_value: float = Field(description="indicator's own value at first_extreme_date -- not necessarily a local extreme of the indicator itself, just its reading on the day price made this swing point (docs/ideas.md's own phrasing: 'the indicator's value at the prior comparable swing extreme').")
    second_extreme_date: date = Field(description="Date of the later of the two compared price swing points -- always the more recent, more extreme price swing (a new high for bearish, a new low for bullish) with a shallower indicator reading than first_extreme_indicator_value.")
    second_extreme_price: float = Field(description="Price (close) at second_extreme_date.")
    second_extreme_indicator_value: float = Field(description="indicator's own value at second_extreme_date.")
    bars_apart: int = Field(description="Trading-day spacing between the two extremes. Always between 20 and 40 inclusive (Kerry Lovvorn's empirical spacing filter, docs/ideas.md) -- a closer-together or further-apart pair is never reported as a divergence at all.")
    centerline_crossed: bool | None = Field(description="Whether MACD-Histogram crossed its own zero centerline between the two extremes -- 'an absolute must for a true divergence' per the book. Always true when indicator is 'macd_histogram' (a non-crossing pair is never reported as a divergence at all, so this is never false here); null for 'stochastic'/'rsi', which have no such requirement.")
    beyond_reference_line: bool | None = Field(description="Whether this divergence is at its textbook strongest for Stochastic/RSI: the first extreme beyond the oscillator's own overbought/oversold reference line (30/70) and the second back inside it. Informational only, never a requirement. Null for 'macd_histogram', where this concept doesn't apply.")
    aborted: bool = Field(description="'Hound of the Baskervilles' (docs/ideas.md): whether price has, as of as_of, already ignored this divergence -- continued making new lows past second_extreme_price despite a bullish divergence, or new highs past it despite a bearish one -- which Elder treats as a strong continuation signal in the opposite direction (his one explicit stop-and-reverse case), not a failed signal to discard.")


class KangarooTailOut(BaseModel):
    direction: Literal["up", "down"] = Field(description="The tail's own physical shape -- 'up' (a new high, closing back down -- Elder's bearish reversal reading) or 'down' (a new low, closing back up -- bullish). Elder ch. 20 ('fingers').")
    tail_date: date = Field(description="The tail bar's own date. Not named `date` (unlike GET /api/stocks/{ticker}/indicators' own per-point field) since this object is nested wherever it appears, and needs to be distinguished from confirmed_date below.")
    confirmed_date: date = Field(description="Date of the very next bar, whose own close confirmed the reversal (below the tail's close for an 'up' tail, above it for a 'down' one) and whose own range stayed normal (not itself tail-sized) -- this pattern isn't reported at all until this bar exists and confirms it.")
    high: float = Field(description="The tail bar's own high.")
    low: float = Field(description="The tail bar's own low.")
    range_multiple: float = Field(description="How many times the recent average bar range (over the preceding lookback window) this bar's own high-low range was -- always >= the qualifying threshold (2.5x).")
    suggested_stop: float = Field(description="Elder's explicit stop-placement rule: halfway through the tail, not at its tip (too wide) or its base (too tight) -- the tail bar's own range midpoint, (high + low) / 2.")


class InsiderTransactionOut(BaseModel):
    insider: str | None = Field(description="Filing insider's name, e.g. 'Cook Timothy D'. Null on the rare row yfinance itself didn't populate a name for.")
    position: str | None = Field(description="Insider's role/relation to the company, e.g. 'Chief Executive Officer' or 'Director' (yfinance's `Position` column). Null when not reported.")
    transaction_text: str = Field(description="yfinance's own free-text transaction description, e.g. 'Sale at price 220.00 - 225.00 per share.' -- kept raw rather than parsed into a structured buy/sell direction (see the backend-market-data-extra-fields task's `decisions` entry).")
    shares: float | None = Field(description="Number of shares in this transaction. Null when not reported.")
    value: float | None = Field(description="Dollar value of this transaction. Null when not reported.")
    start_date: date | None = Field(description="Transaction's filed/effective date. Null when not reported.")
    ownership: str | None = Field(description="yfinance's raw ownership flag for this filing (e.g. 'D' direct / 'I' indirect) -- passed through unmapped since Yahoo's own code list isn't publicly documented beyond these two common values. Null when not reported.")


class InsiderClusterOut(BaseModel):
    direction: Literal["buy", "sell"] = Field(description="Which way this cluster's insiders traded -- 'buy' or 'sell'. Buy and sell clusters are detected entirely independently (a transaction only ever belongs to one direction's clustering pass, per its own classification).")
    window_start_date: date = Field(description="start_date of the cluster's earliest qualifying transaction.")
    window_end_date: date = Field(description="start_date of the cluster's most recent qualifying transaction -- always within 30 calendar days of window_start_date.")
    insiders: list[str] = Field(description="Distinct insider names in this cluster, alphabetically sorted. Always at least 3 (the minimum distinct-insider threshold this cluster reached to qualify at all -- Elder ch. 37 p. 147's 'several insiders ... within a one-month period').")
    transaction_count: int = Field(description="Total qualifying (classified buy/sell, named insider, dated) filings within the window -- can exceed len(insiders) when one of the insiders filed more than once within the window.")
    total_shares: float | None = Field(description="Sum of shares across the window's qualifying filings that reported a share count. Null when none of them did.")
    total_value: float | None = Field(description="Sum of dollar value across the window's qualifying filings that reported one. Null when none of them did.")


class ExtendedDataOut(BaseModel):
    earnings_date: date | None = Field(description="Soonest upcoming earnings date (yfinance `Ticker.calendar`'s 'Earnings Date' list, earliest entry -- Yahoo sometimes reports a multi-day estimate window rather than one confirmed date). Null when yfinance has no upcoming earnings date on record for this ticker, or when `unavailable_reason` is set below.")
    earnings_within_warning_days: bool = Field(description="True when `earnings_date` falls within the next 14 calendar days from today (Elder ch. 58: 'most traders avoid holding stocks whose earnings are about to be reported... a nasty earnings surprise can do serious damage' -- a gap-through-the-stop risk no technical stop protects against). Always False when `earnings_date` is null or already in the past.")
    ex_dividend_date: date | None = Field(description="Next ex-dividend date (`Ticker.calendar`'s 'Ex-Dividend Date'). Null when none is scheduled, or when `unavailable_reason` is set below.")
    shares_short: int | None = Field(description="Most recently reported short interest -- shares sold short and not yet covered (`Ticker.info`'s `sharesShort`, Elder ch. 37 pp.146-148). Null when not reported for this ticker, or when `unavailable_reason` is set below.")
    short_ratio: float | None = Field(description="'Days to cover' -- `shares_short` divided by average daily trading volume (`Ticker.info`'s `shortRatio`). Higher means more trading days it would take short-sellers to cover their position if they all tried at once -- a rough measure of short-squeeze fuel. Null under the same conditions as `shares_short`.")
    short_percent_of_float: float | None = Field(description="Shares short as a fraction (0-1, not a percentage) of the freely tradeable float (`Ticker.info`'s `shortPercentOfFloat`). Null under the same conditions as `shares_short`.")
    float_shares: int | None = Field(description="Freely tradeable share count the short-interest ratios above are computed against (`Ticker.info`'s `floatShares`). Null under the same conditions as `shares_short`.")
    insider_transactions: list[InsiderTransactionOut] = Field(description="Recent officer/director buy/sell filings (`Ticker.insider_transactions`, Elder ch. 37), in the order yfinance itself returns them (most-recent-first). Empty when none are reported, or when `unavailable_reason` is set below -- an empty list either way, since 'no filings' and 'not checked' aren't distinguished at the per-field level (only `unavailable_reason` itself distinguishes them). Raw exposure only -- for buy/sell-cluster detection over this same list, see `AnalysisResponse.insider_clusters`.")
    unavailable_reason: Literal["fallback_provider_active"] | None = Field(description="Set only when the fallback (Stooq) provider is currently serving market data instead of yfinance, which has no equivalent for any of the fields above (docs/architecture/Backend.md's data-provider section) -- every field above is then null/empty, meaning 'not checked, unsupported by the active provider' rather than 'checked, nothing found'. Null in the normal case (yfinance active), in which every null/empty field above genuinely means 'checked, nothing found'.")


class ProfitTargetOut(BaseModel):
    price: float = Field(description="Suggested profit target price for this fresh BUY signal (docs/Analyse.md §7, Elder ch. 53 'How to Set Profit Targets' plus ch. 58's Tradebill formula). See `source` for which of the two techniques below produced this number.")
    source: Literal["channel", "support_resistance"] = Field(description="Which technique produced `price`: 'channel' -- ch. 58's own Tradebill formula, current close + 30% of the weekly chart's Autoenvelope/channel height (ch. 39 p.161 -- a different channel than the daily one `AnalysisResponse.indicators.channel_upper`/`channel_lower` expose for the price-chart overlay); 'support_resistance' -- the nearest `support_resistance_zones` level above current close. Whichever of the two is TIGHTER (closer to current close) is used -- see the backend-profit-target task's `decisions` entry for why the more conservative target is preferred over a fixed preference order.")
    distance_to_stop: float = Field(description="Current close minus the same protective-stop value docs/Analyse.md §7's SafeZone formula would compute for this ticker right now (`app.portfolio.risk.stop_from_price_action`) -- the trade's per-share risk if entered at today's close. Can be <= 0 in the rare case today's close is already at or below that stop.")
    distance_to_target: float = Field(description="`price` minus current close -- the trade's per-share potential reward if entered at today's close. Always > 0 by construction (both target techniques only ever produce a price above current close).")
    reward_risk_ratio: float | None = Field(default=None, description="distance_to_target / distance_to_stop. Null when distance_to_stop <= 0 (an undefined ratio -- see distance_to_stop's own description), not a fabricated number.")
    meets_minimum_reward_risk: bool = Field(description="Whether reward_risk_ratio >= 2.0 -- Elder's own explicit minimum ('potential reward should be at least 2x the risk... it seldom pays to risk a dollar to make a dollar', docs/ideas.md ch. 53). False (never null) when reward_risk_ratio itself is null, since an undefined ratio can't meet the bar either -- this is the explicit 'flag, don't silently hide' signal docs/ideas.md calls for, not something a client has to derive itself from the raw ratio.")


class AnalysisResponse(BaseModel):
    ticker: str
    as_of: date
    signal: Signal
    confidence: int = Field(description="0-100 weighted composite score (docs/Analyse.md §6). Not a statistical probability.")
    confidence_band: ConfidenceBand = Field(description="Low <40, Medium 40-70, High >70.")
    screens: Screens
    confidence_breakdown: list[ConfidenceBreakdownItem] = Field(description="Per-component scores behind `confidence`, so the signal is auditable rather than a bare number.")
    indicators: Indicators = Field(description="Latest-bar-only snapshot. For the same 10 indicator values (plus stochastic_k/force_index_2ema, which live under screens.wave here) as a historical time series across every bar instead, see GET /api/stocks/{ticker}/indicators.")
    support_resistance_zones: list[SupportResistanceZone] = Field(description="Horizontal support/resistance zones detected from swing-point clustering over the ticker's full available daily history (docs/ideas.md, Elder ch. 18) -- up to the 15 strongest by strength_score, descending. Not currently wired into signal/confidence computation or protective_stop -- informational context only (see the backend-support-resistance task's decisions for why tightening protective_stop near a zone is an explicit, separate follow-up).")
    divergence: DivergenceOut | None = Field(description="The most recent qualifying MACD-Histogram/Stochastic/RSI divergence detected between price's own swing points and each indicator's value at those dates (docs/ideas.md, Elder ch. 15/23/26/27) -- null if none currently qualifies. When more than one indicator qualifies with the same second_extreme_date (common, since all three are checked against the same price swing points), MACD-Histogram wins, then Stochastic, then RSI. Detection + exposure only -- not wired into signal/confidence_breakdown (see the backend-divergence-detection task's decisions).")
    kangaroo_tail: KangarooTailOut | None = Field(description="The most recently confirmed Kangaroo Tail reversal pattern (docs/ideas.md, Elder ch. 20 'fingers') -- a single bar's range roughly 2.5x the recent average, protruding from a tight recent range, closing back near its own open, flanked by two normal-height bars, and confirmed by the very next bar continuing in the implied direction. Null if none currently qualifies. Detection + exposure only -- not wired into signal/confidence_breakdown (see the backend-kangaroo-tail-pattern task's decisions).")
    profit_target: ProfitTargetOut | None = Field(default=None, description="Suggested profit target + reward:risk ratio for this ticker's CURRENT signal (docs/Analyse.md §7, Elder ch. 53 'How to Set Profit Targets' plus ch. 58's Tradebill formula). Only ever non-null when `signal` is 'BUY': this app's protective-stop formula (and its whole portfolio model) is explicitly long-only, so there's no symmetric short-side stop to pair with a SELL-side reward:risk ratio -- see the backend-profit-target task's `decisions` entry. Also null for a BUY when neither target technique currently produces a candidate (e.g. a young ticker with under ~100 weeks of weekly history and no yet-detected resistance zone above current price).")
    extended_data: ExtendedDataOut = Field(description="Earnings/dividend dates, short interest, and recent insider transactions (docs/ideas.md; Elder ch. 37/53/58) -- confirmed-live-in-yfinance data this app didn't previously expose. Always a present object; see `ExtendedDataOut.unavailable_reason` for when the fallback (Stooq) provider means every field inside it is null/empty rather than a real 'checked, nothing found' result. See the backend-market-data-extra-fields task's `decisions` entry.")
    insider_clusters: list[InsiderClusterOut] = Field(description="Buy or sell clusters detected from `extended_data.insider_transactions` -- 3+ distinct insiders trading the same direction within a rolling 30-day window (Elder ch. 37 p. 147: 'several insiders buying (or selling) within a one-month period' is a real, if secondary, signal). Ordered most-recent-window_end_date-first. Empty when no cluster currently qualifies, including whenever `extended_data.insider_transactions` itself is empty. Detection + exposure only -- not wired into signal/confidence_breakdown/portfolio risk (see the backend-insider-transaction-clusters task's `decisions` entry).")


# --- /api/stocks/{ticker}/indicators ------------------------------------


class IndicatorHistoryPoint(BaseModel):
    date: date
    tide: TideScreen = Field(description="Same definition/shape as AnalysisResponse.screens.tide, for this bar -- Screen 1 (Tide) recomputed from only the weekly data as-of this bar's own calendar week (see IndicatorHistoryResponse.points' own description), never held fixed at today's value. Never null: like AnalysisResponse.screens.tide, too little weekly history to compute a slope at all still resolves to a concrete NEUTRAL/'flat' result rather than an absent one (app.signals.triple_screen.evaluate_tide's own docstring).")
    ema_13: float = Field(description="Same definition as AnalysisResponse.indicators.ema_13, for this bar.")
    ema_26: float = Field(description="Same definition as AnalysisResponse.indicators.ema_26, for this bar.")
    macd_histogram: float = Field(description="Same definition as AnalysisResponse.indicators.macd_histogram, for this bar.")
    bull_power: float = Field(description="Elder-Ray Bull Power = High - EMA(13), for this bar.")
    bear_power: float = Field(description="Elder-Ray Bear Power = Low - EMA(13), for this bar.")
    stochastic_k: float | None = Field(default=None, description="Stochastic %K (5,3,3), same definition as WaveScreen.stochastic_k, for this bar. Null for a bar still inside the indicator's warm-up window (needs (k_period - 1) + (smooth - 1) prior bars -- 6 with the current defaults, k_period=5/smooth=3) -- unlike WaveScreen.stochastic_k on GET /api/stocks/{ticker}/analysis, which is always non-null since /analysis only ever reports the latest bar, by definition never still warming up.")
    force_index_2ema: float | None = Field(default=None, description="Force Index, 2-period EMA smoothing, same definition as WaveScreen.force_index_2ema, for this bar. Null for a bar still inside the indicator's warm-up window (needs ~2 prior bars) -- same warm-up-only caveat as stochastic_k above.")
    channel_upper: float | None = Field(default=None, description="Same definition as AnalysisResponse.indicators.channel_upper, for this bar. Null for a bar still inside the Autoenvelope deviation-average's ~100-bar warm-up window -- a far longer warm-up than stochastic_k/force_index_2ema above, so this is null across a much larger leading span of a long `range` (e.g. `range=max`) than either of those.")
    channel_lower: float | None = Field(default=None, description="Same definition as AnalysisResponse.indicators.channel_lower, for this bar. Null under the same condition as channel_upper.")
    rsi: float | None = Field(default=None, description="Same definition as AnalysisResponse.indicators.rsi, for this bar. Null for a bar still inside the indicator's 9-day warm-up window -- same warm-up-only caveat as stochastic_k/force_index_2ema above, though with a shorter (9-bar) window than either.")
    season: Season | None = Field(default=None, description="Same definition as AnalysisResponse.indicators.season, for this bar -- a historical Spring/Summer/Autumn/Winter timeline. Null only for the very first bar (fewer than 2 daily bars available up to and including it) -- a much shorter warm-up than stochastic_k/channel_upper/channel_lower/rsi above.")
    trend_strength: TrendStrength = Field(description="Same definition/shape as AnalysisResponse.indicators.trend_strength, for this bar -- a historical Directional System/ADX timeline. Always present as an object; its own atr/plus_di/minus_di/adx fields are independently nullable during their own (per-field) warm-up window, same as AnalysisResponse.indicators.trend_strength.")
    signal: Signal = Field(description="BUY/SELL/HOLD as of this bar (docs/Analyse.md §5), computed from only this bar's own history -- never look-ahead from a later bar.")
    confidence: int = Field(description="Same 0-100 weighted composite score as AnalysisResponse.confidence, for this bar's signal. 0 whenever signal is HOLD, same convention as GET /api/stocks/{ticker}/analysis.")
    confidence_band: ConfidenceBand = Field(description="Low <40, Medium 40-70, High >70, for this bar's confidence.")
    divergence: DivergenceOut | None = Field(default=None, description="Same definition as AnalysisResponse.divergence, using only swing points confirmable from data available through this bar (no look-ahead) -- so this can differ from a later bar's divergence at the same underlying extreme dates once more history confirms a swing point AnalysisResponse.divergence.")
    kangaroo_tail: KangarooTailOut | None = Field(default=None, description="Same definition as AnalysisResponse.kangaroo_tail, restricted per-bar to only a tail whose own confirming bar has arrived by this bar (no look-ahead) -- so this stays null for every bar strictly between a tail's own date and its confirmed_date, then reports that same tail from confirmed_date onward until (if ever) a later one supersedes it.")
    obv: float = Field(description="On-Balance Volume (docs/Analyse.md §4, Elder ch. 29) -- a running total: today's full volume is added if close > prior close, subtracted if close < prior close, unchanged if flat (`app.indicators.obv.obv`). Cumulative over this ticker's *entire* available daily history, not reset to the requested `range` window -- so trimming `range` never changes an already-visible point's own value, only which points are included. Its absolute level is meaningless (it depends on how far back history happens to start) -- only its pattern of highs/lows and divergence against price matters, same as every other oscillator in this app. Not exposed on AnalysisResponse.indicators (a single latest-bar snapshot) for exactly this reason -- only here, where its shape over time is visible. Computation + exposure only -- not wired into `signal`/`confidence`, and divergence detection against it is a separate, explicit follow-up (see the backend-indicator-obv-ad task's decisions).")
    accumulation_distribution: float = Field(description="Accumulation/Distribution (docs/Analyse.md §4, Elder ch. 29) -- a running total, more finely calibrated than `obv` since it credits volume proportional to where the close landed within the day's own range rather than crediting the whole day's volume to whichever side 'won': `(close - open) / (high - low) * volume`, cumulative (`app.indicators.accumulation_distribution.accumulation_distribution`). Same cumulative-over-full-history, meaningless-absolute-level, computation-and-exposure-only caveats as `obv` above.")


class IndicatorHistoryResponse(BaseModel):
    ticker: str
    points: list[IndicatorHistoryPoint] = Field(description="Oldest-first, one entry per daily bar in the requested range. The last entry always matches GET /api/stocks/{ticker}/analysis's signal/confidence/indicators for this same ticker (same as_of date, computed from the same inputs). Screen 1 (Tide) IS point-in-time recomputed per bar, from only the weekly data as-of that bar's own calendar week -- not held fixed at today's value (see the api-stocks-indicator-history task's decisions).")


# --- /api/portfolio -------------------------------------------------------


class Equity(BaseModel):
    cash: float
    positions_value: float = Field(description="Sum of quantity x current_price across all positions (mark-to-market, not cost basis).")
    total: float = Field(description="cash + positions_value.")


class PositionOut(BaseModel):
    id: str
    ticker: str
    quantity: float
    avg_cost_basis: float
    entry_date: date
    current_price: float | None = Field(default=None, description="Null only if the latest price fetch for this ticker failed.")
    unrealized_pnl_pct: float | None = Field(default=None, description="(current_price - avg_cost_basis) / avg_cost_basis, as a percentage. Null under the same condition as current_price.")
    signal: Signal | None = Field(
        default=None,
        description="BUY/SELL/HOLD from the exact same Triple Screen signal engine "
        "GET /api/stocks/{ticker}/analysis and GET /api/watchlist use (docs/Analyse.md §5) -- "
        "not a separately-implemented buy check. Null if this position's signal couldn't be "
        "computed right now -- either its current_price fetch already failed (see "
        "current_price's own description), that fetch succeeded but the separate weekly-"
        "history fetch the signal engine additionally needs (for Screen 1/Tide) failed, or "
        "the latest daily bar has a valid close (so current_price is still available) but "
        "NaN open/high/low and so doesn't survive the signal engine's stricter filtering -- "
        "mirroring WatchlistItemOut's null-on-failure pattern rather than failing the whole "
        "request or dropping the position. See the api-portfolio-position-signal task's "
        "`decisions`.",
    )
    confidence: int | None = Field(
        default=None,
        description="Same 0-100 weighted composite score as AnalysisResponse.confidence. "
        "Null under the same condition as `signal`.",
    )
    confidence_band: ConfidenceBand | None = Field(
        default=None,
        description="Low <40, Medium 40-70, High >70. Null under the same condition as `signal`.",
    )
    entry_notes: str | None = Field(
        default=None,
        description="The free-text 'why did I take this trade' note supplied via "
        "PositionIn.entry_notes when this position was opened (Elder ch. 59 Trade Journal "
        "Section A) -- null if none was ever given.",
    )
    strategy: str | None = Field(
        default=None,
        description="The trader's own personal, named strategy/setup tag supplied via "
        "PositionIn.strategy when this position was opened (Elder ch. 55/56/58/59 -- his own "
        "examples: 'false breakout with a divergence,' 'pullback to value') -- null if none "
        "was ever given.",
    )


class PortfolioResponse(BaseModel):
    equity: Equity
    positions: list[PositionOut]


class PositionIn(BaseModel):
    ticker: str = Field(min_length=1, description="Stock ticker symbol, normalized to uppercase (leading/trailing whitespace is stripped). Adding a ticker that's already held merges into the existing position (quantity-weighted average cost basis) rather than creating a duplicate row — see the api-portfolio-add-position task's decisions.")
    quantity: float = Field(gt=0, allow_inf_nan=False, description="Number of shares being added. Must be a positive, finite number (Infinity/NaN are rejected) — this endpoint only adds to a position; use DELETE /api/portfolio/positions/{id} to remove one.")
    avg_cost_basis: float = Field(gt=0, allow_inf_nan=False, description="Price paid per share for this lot. On merge with an existing position, this is blended into a quantity-weighted average, not overwritten. Must be a positive, finite number (Infinity/NaN are rejected).")
    entry_date: date = Field(description="Date this lot was purchased. On merge with an existing position, the earlier of the two entry dates is kept.")
    entry_notes: str | None = Field(
        default=None,
        description="Optional free-text note on why this trade was taken (Elder ch. 59 Trade "
        "Journal Section A, docs/ideas.md's ch. 59 entry), e.g. 'Breakout above resistance, "
        "strong earnings beat.' On merge with an existing position for the same ticker, an "
        "incoming note is appended to the existing one (blank-line separated) rather than "
        "overwriting it, so notes from multiple buys into the same position are all kept -- "
        "see the backend-trade-journal-entry-notes task's `decisions`. Carried through "
        "unchanged to the resulting `ClosedTradeOut.entry_notes` if/when this position is "
        "later closed.",
    )
    strategy: str | None = Field(
        default=None,
        description="Optional free-text personal, named strategy/setup tag for this trade "
        "(Elder ch. 55/56/58/59, docs/ideas.md's ch. 55/56 entry -- his own examples: 'false "
        "breakout with a divergence,' 'pullback to value'). Free-text rather than a fixed, "
        "predefined list, since Elder's own framing is that a trader's strategies are "
        "personal and evolve over time -- see the backend-trade-strategy-tagging task's "
        "`decisions`. On merge with an existing position for the same ticker, an incoming "
        "`strategy` *overwrites* the existing one (unlike `entry_notes`, which appends) -- a "
        "merge with no incoming `strategy` leaves the existing one untouched. Carried through "
        "unchanged to the resulting `ClosedTradeOut.strategy` if/when this position is later "
        "closed.",
    )

    @field_validator("ticker")
    @classmethod
    def _strip_and_require_non_blank_ticker(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("ticker must not be blank or whitespace-only")
        return stripped


# --- /api/portfolio/risk ---------------------------------------------------


class RiskPosition(BaseModel):
    id: str
    ticker: str
    protective_stop: float = Field(description="Recent swing low minus 2x a volatility buffer (SafeZone concept, docs/Analyse.md §7).")
    position_risk_pct: float = Field(description="Fraction of current account equity lost if this position hits its protective_stop (the 2% rule).")
    two_percent_rule_breached: bool
    exit_flags: list[str] = Field(description="Risk-driven exit reasons, e.g. 'stop_hit', 'tide_flipped_bearish' (docs/Analyse.md §7). Independent of this stock's fresh entry signal — can be non-empty even when /analysis says HOLD.")


class RiskResponse(BaseModel):
    total_open_risk_pct: float = Field(
        description="The 6% rule total: sum of position_risk_pct across all open positions "
        "plus realized_losses_this_month_pct below (docs/Analyse.md §7's own two-part formula "
        "-- 'the sum of your losses for the current month AND the risks in open trades', per "
        "docs/ideas.md's ch. 51 cross-check). Kept under this existing field name rather than "
        "renamed, since it's the one this response has always compared against the 6% "
        "threshold — see the backend-trade-history-table task's `decisions` entry."
    )
    realized_losses_this_month_pct: float = Field(
        description="This calendar month's realized losses from closed_trades (only losing "
        "trades count; a profitable month contributes 0, never a negative offset to open "
        "risk), as a percentage of current account equity -- the component total_open_risk_pct "
        "above was missing before this field existed, per the backend-trade-history-table "
        "task. See DELETE /api/portfolio/positions/{id} for how a closed_trades row is "
        "recorded."
    )
    six_percent_rule_breached: bool
    positions: list[RiskPosition]


# --- /api/watchlist ---------------------------------------------------


class WatchlistItemOut(BaseModel):
    ticker: str
    added_at: datetime = Field(description="When this ticker was added to the watchlist (UTC).")
    signal: Signal | None = Field(
        default=None,
        description="BUY/SELL/HOLD from the exact same Triple Screen signal engine "
        "GET /api/stocks/{ticker}/analysis uses (docs/Analyse.md §5) -- not a "
        "separately-implemented buy check. Null only if the signal couldn't be computed "
        "for this ticker right now (unknown/delisted ticker, insufficient history, or the "
        "data provider being unavailable), mirroring PositionOut's current_price "
        "null-on-failure pattern -- see the api-watchlist task's `decisions`.",
    )
    confidence: int | None = Field(
        default=None,
        description="Same 0-100 weighted composite score as AnalysisResponse.confidence. "
        "Null under the same condition as `signal`.",
    )
    confidence_band: ConfidenceBand | None = Field(
        default=None,
        description="Low <40, Medium 40-70, High >70. Null under the same condition as `signal`.",
    )


class WatchlistResponse(BaseModel):
    items: list[WatchlistItemOut] = Field(
        description="Every watched ticker, ordered by when it was added (oldest first)."
    )


class BreadthResponse(BaseModel):
    tracked_ticker_count: int = Field(
        description="Distinct tickers across the watchlist and portfolio combined (union, "
        "deduplicated -- a ticker held in both counts once), i.e. the 'personal breadth' "
        "universe size. This is a cheap, no-new-data-source approximation of true market "
        "breadth (which needs a broad ticker universe this app doesn't have, e.g. the "
        "S&P 500) -- see docs/Analyse.md's Personal breadth proxy section and "
        "docs/ideas.md's ch. 34-36 entry for the practical-obstacle rationale."
    )
    bullish_count: int = Field(
        description="Of the tracked tickers whose Screen 1 (Tide) trend could be computed "
        "right now, how many are currently BULLISH."
    )
    bearish_count: int = Field(
        description="Same as bullish_count, for BEARISH."
    )
    neutral_count: int = Field(
        description="Same as bullish_count, for NEUTRAL."
    )
    unavailable_count: int = Field(
        description="Tracked tickers whose Tide trend couldn't be computed right now "
        "(unknown/delisted ticker, insufficient history, or the data provider being "
        "unavailable) -- excluded from bullish_count/bearish_count/neutral_count and from "
        "the percentages below, rather than guessed at, mirroring GET /api/watchlist's own "
        "null-signal-on-failure convention."
    )
    bullish_pct: float = Field(
        description="bullish_count as a percentage of (bullish_count + bearish_count + "
        "neutral_count), rounded to 1 decimal place. 0.0 when that denominator is 0 (an "
        "empty watchlist+portfolio, or every tracked ticker currently unavailable), rather "
        "than an undefined/NaN value. bullish_pct/bearish_pct/neutral_pct are each rounded "
        "independently, so the three don't always sum to exactly 100.0 (e.g. an even 3-way "
        "split rounds to 33.3 + 33.3 + 33.3 = 99.9) -- each value is still independently "
        "correct, not a display bug."
    )
    bearish_pct: float = Field(
        description="Same as bullish_pct, for bearish_count."
    )
    neutral_pct: float = Field(
        description="Same as bullish_pct, for neutral_count."
    )


class WatchlistItemIn(BaseModel):
    ticker: str = Field(
        min_length=1,
        description="Stock ticker symbol to watch, normalized to uppercase (leading/trailing "
        "whitespace is stripped). Adding a ticker already on the watchlist is a no-op that "
        "returns the existing entry unchanged (original added_at kept) rather than creating "
        "a duplicate row or rejecting with 409/422 -- see the api-watchlist task's `decisions`.",
    )

    @field_validator("ticker")
    @classmethod
    def _strip_and_require_non_blank_ticker(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("ticker must not be blank or whitespace-only")
        return stripped


# --- /api/portfolio/closed-trades ------------------------------------------

ExitReasonOut = Literal[
    "target_hit",
    "stop_hit",
    "reached_value_zone",
    "going_nowhere",
    "starting_to_turn",
    "couldnt_stand_the_pain",
    "recognized_junk_trade_after_entry",
    "unspecified",
]


class ClosedTradeOut(BaseModel):
    id: str
    ticker: str
    quantity: float
    entry_price: float
    entry_date: date
    exit_price: float
    exit_date: date
    realized_pnl: float = Field(
        description="quantity * (exit_price - entry_price) -- see DELETE "
        "/api/portfolio/positions/{id} for how this row is recorded."
    )
    exit_reason: ExitReasonOut = Field(
        description="Why this position was closed, from Elder's own taxonomy "
        "(docs/Analyse.md §7 / docs/ideas.md's ch. 51 cross-check) plus this app's own "
        "'unspecified' default for a trade closed with no explicit reason supplied -- see "
        "DELETE /api/portfolio/positions/{id}."
    )
    buy_grade_pct: float | None = Field(
        default=None,
        description="(entry day's high - entry_price) / (entry day's high - entry day's "
        "low), as a percentage -- how close to the entry day's low the buy actually was "
        "(Elder ch. 55 'Is This an A-Trade?', docs/Analyse.md §7 / docs/ideas.md ch. 55). "
        ">50% is 'very good'. Null whenever the entry day's own OHLC can't be found in the "
        "ticker's currently-fetchable daily history (e.g. entry_date predates that history, "
        "the fetch itself failed, or that bar was dropped as malformed) or the entry day had "
        "a zero/negative trading range -- see app.portfolio.grading.grade_closed_trade.",
    )
    sell_grade_pct: float | None = Field(
        default=None,
        description="(exit_price - exit day's low) / (exit day's high - exit day's low), as "
        "a percentage -- how close to the exit day's high the sell actually was. >50% is "
        "'very good'. Null under the same conditions as buy_grade_pct, evaluated for the "
        "exit day instead.",
    )
    trade_grade_pct: float | None = Field(
        default=None,
        description="(exit_price - entry_price) / (channel_upper - channel_lower, measured "
        "on entry_date), as a percentage -- the trade's actual gain as a fraction of the "
        "entry day's Autoenvelope/channel height (docs/Analyse.md §4, same channel "
        "AnalysisResponse.indicators.channel_upper/channel_lower expose). >=30% capture is "
        "an 'A' trade, ~10% a 'C' trade. Null whenever the entry day's channel bounds aren't "
        "available -- the ticker's fetched daily history doesn't reach back to entry_date, "
        "or entry_date falls inside the Autoenvelope's own ~100-bar warm-up window.",
    )
    trade_letter_grade: Literal["A", "B", "C", "D"] | None = Field(
        default=None,
        description="Elder's own A/B/C/D letter grade (ch. 55 footnote: 'A is excellent, B "
        "good, C mediocre, and D poor') derived from trade_grade_pct: A >= 30%, B in "
        "[20%, 30%), C in [10%, 20%), D < 10% (including a losing trade, i.e. a negative "
        "trade_grade_pct). Only trade_grade_pct gets a letter -- buy_grade_pct/sell_grade_pct "
        "have no letter-grade scale documented in the book at all, only a single '>50% = "
        "very good' anchor each, so they stay percentage-only. Null exactly when "
        "trade_grade_pct is null (see app.portfolio.grading.trade_letter_grade for the full "
        "threshold rationale/decision record).",
    )
    entry_notes: str | None = Field(
        default=None,
        description="Carried over verbatim from the position's own PositionIn.entry_notes "
        "(Elder ch. 59 Trade Journal Section A) at the moment it was closed -- null if the "
        "position never had a note recorded.",
    )
    strategy: str | None = Field(
        default=None,
        description="Carried over verbatim from the position's own PositionIn.strategy "
        "(Elder ch. 55/56/58/59 personal named strategy tag) at the moment it was closed -- "
        "null if the position never had a strategy tag recorded.",
    )
    follow_up_notes: str | None = Field(
        default=None,
        description="Free-text note from the mandatory two-months-later follow-up review "
        "(Elder ch. 59 Trade Journal Section E, docs/ideas.md's ch. 59 entry) -- reopening "
        "this trade with the benefit of hindsight and writing what it teaches. Set by POST "
        "/api/portfolio/closed-trades/{trade_id}/follow-up-review; null until that review has "
        "happened.",
    )
    follow_up_reviewed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the most recent follow-up review, set together with "
        "follow_up_notes by POST /api/portfolio/closed-trades/{trade_id}/follow-up-review. "
        "Null means this trade hasn't been reviewed yet -- exactly the condition GET "
        "/api/portfolio/closed-trades?due_for_follow_up=true filters on.",
    )


class ClosedTradesResponse(BaseModel):
    items: list[ClosedTradeOut] = Field(
        description="Every closed trade (the docs/Analyse.md §7 trade-history/ledger table), "
        "most recently exited first."
    )


# --- POST /api/portfolio/closed-trades/{trade_id}/follow-up-review ---------


class FollowUpReviewIn(BaseModel):
    follow_up_notes: str = Field(
        min_length=1,
        description="Free-text note from reopening this closed trade with hindsight, about "
        "two months after it closed (Elder ch. 59 Trade Journal Section E, docs/ideas.md's "
        "ch. 59 entry) -- what the trade actually teaches, seen with the benefit of "
        "hindsight. Required and must not be blank/whitespace-only (leading/trailing "
        "whitespace is stripped) -- unlike PositionIn.entry_notes, this endpoint's entire "
        "purpose is recording that note, so an empty one would defeat the point. Calling "
        "this endpoint again for the same trade overwrites both this field and "
        "follow_up_reviewed_at rather than appending -- see the "
        "backend-trade-journal-followup-review task's `decisions` entry.",
    )

    @field_validator("follow_up_notes")
    @classmethod
    def _strip_and_require_non_blank_follow_up_notes(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("follow_up_notes must not be blank or whitespace-only")
        return stripped


# --- /api/portfolio/trade-apgar ---------------------------------------------

FalseBreakoutStatusIn = Literal["none", "already_happened", "on_the_verge"]
PerfectionIn = Literal["neither", "one", "both"]


class TradeApgarIn(BaseModel):
    ticker: str = Field(min_length=1, description="Ticker to score. Normalized to uppercase (leading/trailing whitespace is stripped), matching PositionIn.ticker/POST /api/portfolio/positions.")
    false_breakout_status: FalseBreakoutStatusIn = Field(
        description="Manual input (Elder ch. 58, docs/ideas.md): whether a false breakout has "
        "recently happened or is currently developing for this ticker -- 'none' (0 points), "
        "'already_happened' (1 point), or 'on_the_verge' (2 points, a false breakout actively "
        "developing right now). Not auto-populated in this first version -- see this task's "
        "`decisions` entry for why `app.signals.kangaroo_tail`/`app.signals.support_resistance` "
        "aren't used to suggest a starting value here."
    )
    perfection: PerfectionIn = Field(
        description="Manual input (Elder ch. 58): whether the weekly and daily timeframes "
        "both look ideal for this setup -- 'neither' (0 points), 'one' does (1 point), or "
        "'both' do (2 points, rare per Elder's own note -- one perfect timeframe plus one "
        "merely good is fine). Inherently subjective; never auto-populated."
    )

    @field_validator("ticker")
    @classmethod
    def _strip_and_require_non_blank_ticker(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("ticker must not be blank or whitespace-only")
        return stripped


class TradeApgarQuestionOut(BaseModel):
    key: Literal["weekly_impulse", "daily_impulse", "price_vs_value", "false_breakout", "perfection"] = Field(
        description="Which of the fixed 5 questions this is, in Elder's own ch. 58 order."
    )
    label: str = Field(description="Human-readable question text.")
    value: str = Field(
        description="The underlying classification this question's score was derived from -- "
        "one of Impulse's own 'GREEN'/'RED'/'BLUE' for weekly_impulse/daily_impulse, "
        "'above_value'/'in_value_zone'/'below_value' for price_vs_value, or the caller's own "
        "TradeApgarIn.false_breakout_status/perfection value, echoed back, for the two manual "
        "questions."
    )
    score: int = Field(ge=0, le=2, description="0, 1, or 2 -- this question's own score per Elder's ch. 58 scoring table (docs/ideas.md).")
    source: Literal["auto", "manual"] = Field(
        description="'auto' -- weekly_impulse/daily_impulse/price_vs_value, derived from "
        "app.signals.engine.analyse()'s own output for `ticker` at the time of this request, "
        "not a value the caller can override. 'manual' -- false_breakout/perfection, the "
        "caller's own TradeApgarIn inputs, echoed back."
    )


class TradeApgarOut(BaseModel):
    ticker: str = Field(description="Uppercased ticker this score was computed for.")
    questions: list[TradeApgarQuestionOut] = Field(
        description="All 5 fixed questions, always in Elder's own ch. 58 order (weekly "
        "Impulse, daily Impulse, price vs. value, false breakout, perfection) -- never a "
        "variable-length or reordered list."
    )
    total_score: int = Field(ge=0, le=10, description="Sum of every question's score, 0-10.")
    go: bool = Field(
        description="Elder's own go/no-go rule (docs/ideas.md's ch. 58 entry): true only when "
        "total_score >= 7 AND no single question scored 0 -- both conditions are required "
        "together, not just the total. A trade scoring 8 total with one question at 0 still "
        "gets `go=false`."
    )


# --- /api/ibkr/status ------------------------------------------------------

IBKRGatewayState = Literal["disabled", "available", "gateway_unreachable", "not_authenticated"]


class IBKRStatusResponse(BaseModel):
    state: IBKRGatewayState = Field(
        description="Whether the optional IBKR Client Portal Gateway integration is usable "
        "right now. 'disabled' -- Settings.ibkr_enabled is False (this app's default; no "
        "attempt to reach a gateway is made at all). 'available' -- the gateway is running "
        "and its session is authenticated; IBKR-backed features (hourly bars, the market "
        "scanner) can be used. 'gateway_unreachable' -- ibkr_enabled is True but no gateway "
        "process answered at the configured base URL (most likely it isn't running). "
        "'not_authenticated' -- the gateway process is up and answering but its interactive "
        "browser login step hasn't been completed, or the session has since expired. "
        "Mirrors app.data.ibkr_provider.GatewayState exactly, plus this endpoint's own "
        "'disabled' state for when that check is never even attempted.",
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable context for `state` (the underlying transport error, "
        "or the gateway's own message) -- informational only, never required for a caller "
        "to branch on. Always null for 'disabled' and usually null for 'available'.",
    )


# --- /api/ibkr/scanner/params, /api/ibkr/scanner/run -----------------------


class IBKRScannerParamsResponse(BaseModel):
    state: IBKRGatewayState = Field(
        description="Same semantics/values as GET /api/ibkr/status's `state` -- this "
        "endpoint reuses that exact availability check rather than inventing a second one. "
        "'available' means `categories` below is populated; every other value means the "
        "scanner feature is currently unavailable (never an HTTP error) and `categories` "
        "is null.",
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable context for `state`, same convention as "
        "GET /api/ibkr/status's `detail`.",
    )
    categories: list[dict] | None = Field(
        default=None,
        description="IBKR's own `scan_type_list` from `/iserver/scanner/params`, passed "
        "through as-is (each entry's exact fields -- e.g. `code`/`display_name` -- are "
        "entirely gateway-defined and not modeled here; see the backend-market-scanner "
        "task's `decisions` entry for why this isn't hand-curated down to a fixed subset). "
        "Non-null if and only if `state` is 'available'. Use a `code` from here as the "
        "`scan_config.type` value in `POST /api/ibkr/scanner/run`.",
    )


class IBKRScannerRunRequest(BaseModel):
    scan_config: dict = Field(
        description="IBKR's own `/iserver/scanner/run` request body: `instrument`/`type`/"
        "`location`/`filter` keys, built from the option lists `GET /api/ibkr/scanner/params` "
        "returns. Passed to the gateway as-is -- this app does not validate or transform it "
        "(matching `IBKRProvider.run_scanner`'s own contract). To apply ch. 56's own "
        "liquidity-filter advice (skip illiquid names, roughly <500k-1M average daily "
        "volume), include IBKR's own volume-floor filter code from `get_scanner_params`'s "
        "filter option list here -- this endpoint does not inject one automatically (see "
        "this task's `decisions` entry).",
        examples=[{"instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR"}],
    )


class IBKRScannerResultOut(BaseModel):
    conid: int = Field(description="IBKR's own numeric contract id for this result.")
    symbol: str | None = Field(default=None, description="Ticker symbol, if the gateway supplied one.")
    company_name: str | None = Field(default=None, description="Company name, if the gateway supplied one.")
    rank: int | None = Field(
        default=None, description="This result's rank within the scan (1 = best match), if the gateway supplied one."
    )


class IBKRScannerRunResponse(BaseModel):
    state: IBKRGatewayState = Field(
        description="Same semantics/values as GET /api/ibkr/status's `state`. 'available' "
        "means `results` below reflects a completed scan; every other value means the "
        "scanner feature is currently unavailable (never an HTTP error) and `results` is "
        "null. Being rate-limited (more than 1 request/second) is a distinct, genuine error "
        "case -- see this route's `429` response -- not represented as a `state` value here.",
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable context for `state`, same convention as "
        "GET /api/ibkr/status's `detail`.",
    )
    results: list[IBKRScannerResultOut] | None = Field(
        default=None,
        description="The scan's matching contracts, most relevant first per IBKR's own "
        "`rank`. Non-null if and only if `state` is 'available' -- an empty list is a valid, "
        "successful zero-match scan, distinct from a null `results` (feature unavailable).",
    )


# --- /api/ibkr/breadth/snapshot ---------------------------------------------

_SERIES_KEY_PATTERN = r"^[a-z0-9_-]{1,40}$"


class IBKRBreadthSnapshotRequest(BaseModel):
    series_key: str = Field(
        pattern=_SERIES_KEY_PATTERN,
        description="Caller-chosen label for one side of a breadth reading (e.g. `\"nh\"`/"
        "`\"nl\"` for New High-New Low, `\"adv\"`/`\"dec\"` for Advance/Decline) -- lowercase "
        "letters/digits/underscore/hyphen, 1-40 chars. This app doesn't hardcode which IBKR "
        "scan-type code corresponds to which side of a breadth reading (unconfirmed against "
        "a live gateway, same reasoning as `POST /api/ibkr/scanner/run`'s own `scan_config`) "
        "-- the caller supplies both the label and the `scan_config` that produces it, and "
        "combines two of these readings (e.g. `nh` minus `nl`) into a spread itself.",
        examples=["nh", "nl"],
    )
    scan_config: dict = Field(
        description="Same shape as `POST /api/ibkr/scanner/run`'s `scan_config` -- passed to "
        "the gateway as-is on a cache miss (see `count` below). Ignored (not re-sent to the "
        "gateway) if `series_key` already has a recorded snapshot for today.",
        examples=[{"instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR"}],
    )


class IBKRBreadthSnapshotResponse(BaseModel):
    state: IBKRGatewayState = Field(
        description="Same semantics/values as GET /api/ibkr/status's `state`. 'available' "
        "means `count` below reflects a recorded (today's, possibly already-cached) scan "
        "result; every other value means the scanner feature is currently unavailable (never "
        "an HTTP error) and every field below is null. Being rate-limited is a distinct, "
        "genuine error case -- see this route's `429` response -- not represented here.",
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable context for `state`, same convention as "
        "GET /api/ibkr/status's `detail`.",
    )
    series_key: str = Field(description="Echoes the request's `series_key`.")
    snapshot_date: date | None = Field(
        default=None,
        description="The calendar day (server UTC) `count` was recorded for -- always "
        "today's date when `state` is 'available'. Null when `state` isn't 'available'.",
    )
    count: int | None = Field(
        default=None,
        description="`len(IBKRProvider.run_scanner(scan_config))` for today, for this "
        "`series_key` -- the number of matching contracts a single IBKR scan run returned, "
        "capped at whatever bounded, ranked shortlist size IBKR's own gateway applies to one "
        "scan request. This is an explicitly bounded approximation of a genuine full-market "
        "count, not a literal Elder NH-NL/Advance-Decline value -- see "
        "docs/Analyse.md's 'IBKR-scanner breadth approximation' section. Non-null if and only "
        "if `state` is 'available'.",
    )
    days_recorded: int = Field(
        default=0,
        description="How many calendar days (including today) have a recorded snapshot for "
        "this `series_key` so far -- lets a caller tell whether `rolling_5d`/`rolling_20d` "
        "below reflect a full window or are still null for lack of history. 0 when `state` "
        "isn't 'available'.",
    )
    rolling_5d: int | None = Field(
        default=None,
        description="Sum of `count` over the most recent 5 recorded days for this "
        "`series_key` (ending today), matching ch. 34's 'weekly NH-NL' 5-day moving total -- "
        "null until at least 5 days are recorded (`days_recorded >= 5`), rather than a "
        "misleadingly partial sum. A caller composing two series (e.g. `nh` minus `nl`) "
        "should subtract the two series' `rolling_5d` values, not re-derive a rolling sum "
        "from `count` alone.",
    )
    rolling_20d: int | None = Field(
        default=None,
        description="Same as `rolling_5d`, over the most recent 20 recorded days -- matching "
        "ch. 34's '20-day NH-NL' monthly look-back. Null until `days_recorded >= 20`.",
    )


# --- /api/daily-homework ----------------------------------------------------

HomeworkBandOut = Literal["red", "yellow", "green"]

# A plain `date: date | None = Field(...)` annotated-assignment inside a class body is a
# genuine Python gotcha (not a pydantic one): for `x: T = v`, CPython evaluates/stores `v`
# into the name `x` *before* evaluating the annotation `T` (see SETUP_ANNOTATIONS's bytecode
# ordering) -- so when the field name and the type name are both the bare word `date`, `T`
# (`date | None`) is evaluated with `date` already rebound to the `Field(...)` default,
# raising "unsupported operand type(s) for |: 'FieldInfo' and 'NoneType'". Every *other*
# `date`-typed field in this module (`OHLCVBar.date`, `HistoryRequest`-adjacent fields, etc.)
# has no default value, so it never hits this ordering bug. `_OptionalDate` sidesteps it by
# giving the annotation a name distinct from the field name.
_OptionalDate = date | None


class DailyHomeworkIn(BaseModel):
    date: _OptionalDate = Field(
        default=None,
        description="Calendar day this self-test is for. Defaults to today (server UTC "
        "date) if omitted -- a caller may also supply a past date to backfill/correct an "
        "earlier day's entry. Submitting a date that already has a recorded entry overwrites "
        "that day's scores rather than rejecting the request or creating a second row -- see "
        "this task's `decisions` entry.",
    )
    physical_state_score: int = Field(
        ge=0, le=2, description="'How do I feel physically?' 0 (poor) / 1 (okay) / 2 (good)."
    )
    yesterday_trading_score: int = Field(
        ge=0,
        le=2,
        description="'How did I trade yesterday?' 0 (poorly) / 1 (neutral, or no trades) / "
        "2 (well). GET /api/daily-homework/yesterday-trading-suggestion offers a suggested "
        "value for this field derived from yesterday's closed_trades realized P&L, but never "
        "auto-fills or overrides it -- this is always the caller's own manual answer.",
    )
    trade_planning_score: int = Field(
        ge=0, le=2, description="'Have I done my trade planning?' 0 (no) / 1 (partially) / 2 (fully)."
    )
    mood_score: int = Field(
        ge=0, le=2, description="'What is my mood?' 0 (poor) / 1 (neutral) / 2 (good)."
    )
    schedule_score: int = Field(
        ge=0,
        le=2,
        description="'How busy is my schedule today?' 0 (very busy) / 1 (somewhat busy) / "
        "2 (clear) -- a busier day leaves less attention for trading well.",
    )


class DailyHomeworkOut(BaseModel):
    date: date
    physical_state_score: int = Field(
        ge=0, le=2, description="'How do I feel physically?' 0 (poor) / 1 (okay) / 2 (good)."
    )
    yesterday_trading_score: int = Field(
        ge=0,
        le=2,
        description="'How did I trade yesterday?' 0 (poorly) / 1 (neutral, or no trades) / "
        "2 (well). See DailyHomeworkIn's field of the same name for the (never "
        "auto-applied) suggestion endpoint.",
    )
    trade_planning_score: int = Field(
        ge=0, le=2, description="'Have I done my trade planning?' 0 (no) / 1 (partially) / 2 (fully)."
    )
    mood_score: int = Field(
        ge=0, le=2, description="'What is my mood?' 0 (poor) / 1 (neutral) / 2 (good)."
    )
    schedule_score: int = Field(
        ge=0,
        le=2,
        description="'How busy is my schedule today?' 0 (very busy) / 1 (somewhat busy) / "
        "2 (clear) -- a busier day leaves less attention for trading well.",
    )
    total_score: int = Field(
        description="Sum of the five scores above, 0-10 (docs/ideas.md's ch. 57 entry)."
    )
    band: HomeworkBandOut = Field(
        description="The book's own color-banding of `total_score`: <=4 'red' (don't trade), "
        "5-6 'yellow' (trade cautiously), 7-8 'green', 9-10 'yellow' again (Elder's own note: "
        "\"with everything so perfect, any change is bound to be for the worse\") -- see "
        "app.portfolio.homework.band_for_total_score."
    )
    recorded_at: datetime = Field(
        description="When this day's entry was last recorded/updated (UTC)."
    )


class DailyHomeworkListResponse(BaseModel):
    items: list[DailyHomeworkOut] = Field(
        description="Every recorded self-test entry, most recent `date` first."
    )


class DailyHomeworkTodayResponse(BaseModel):
    entry: DailyHomeworkOut | None = Field(
        default=None,
        description="Today's (server UTC date) recorded entry, or null if today's self-test "
        "hasn't been recorded yet -- the normal, expected state at the start of every day, "
        "not an error.",
    )


class YesterdayTradingSuggestionOut(BaseModel):
    as_of_date: date = Field(
        description="The 'yesterday' this suggestion is computed for (today's date minus "
        "one calendar day, server UTC 'today')."
    )
    net_realized_pnl: float | None = Field(
        default=None,
        description="Sum of `realized_pnl` across every `closed_trades` row exited on "
        "`as_of_date`. Null if no position was closed that day -- there is nothing to base a "
        "suggestion on.",
    )
    suggested_score: int | None = Field(
        default=None,
        description="A suggested (not authoritative) `yesterday_trading_score` for "
        "`POST /api/daily-homework`, derived from `net_realized_pnl`: 2 for a net gain, 1 "
        "for exactly breakeven, 0 for a net loss. Null whenever `net_realized_pnl` is null -- "
        "this endpoint never guesses a value with nothing to base it on. The caller decides "
        "whether to use it; this app never writes `yesterday_trading_score` on the user's "
        "behalf -- see the backend-daily-homework-self-test task's `decisions` entry.",
    )


# --- shared error shape (FastAPI default, documented for clarity) ---------


class ErrorDetail(BaseModel):
    detail: str
