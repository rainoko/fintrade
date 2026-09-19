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
    trend: Trend = Field(description="Screen 1 output (docs/Analyse.md §2). NEUTRAL when weekly MACD-Histogram slope and the 13/26-week EMA relationship disagree.")
    weekly_macd_histogram_slope: Literal["rising", "falling", "flat"]


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


class AnalysisResponse(BaseModel):
    ticker: str
    as_of: date
    signal: Signal
    confidence: int = Field(description="0-100 weighted composite score (docs/Analyse.md §6). Not a statistical probability.")
    confidence_band: ConfidenceBand = Field(description="Low <40, Medium 40-70, High >70.")
    screens: Screens
    confidence_breakdown: list[ConfidenceBreakdownItem] = Field(description="Per-component scores behind `confidence`, so the signal is auditable rather than a bare number.")
    indicators: Indicators = Field(description="Latest-bar-only snapshot. For the same 9 indicator values (plus stochastic_k/force_index_2ema, which live under screens.wave here) as a historical time series across every bar instead, see GET /api/stocks/{ticker}/indicators.")
    support_resistance_zones: list[SupportResistanceZone] = Field(description="Horizontal support/resistance zones detected from swing-point clustering over the ticker's full available daily history (docs/ideas.md, Elder ch. 18) -- up to the 15 strongest by strength_score, descending. Not currently wired into signal/confidence computation or protective_stop -- informational context only (see the backend-support-resistance task's decisions for why tightening protective_stop near a zone is an explicit, separate follow-up).")
    divergence: DivergenceOut | None = Field(description="The most recent qualifying MACD-Histogram/Stochastic/RSI divergence detected between price's own swing points and each indicator's value at those dates (docs/ideas.md, Elder ch. 15/23/26/27) -- null if none currently qualifies. When more than one indicator qualifies with the same second_extreme_date (common, since all three are checked against the same price swing points), MACD-Histogram wins, then Stochastic, then RSI. Detection + exposure only -- not wired into signal/confidence_breakdown (see the backend-divergence-detection task's decisions).")
    kangaroo_tail: KangarooTailOut | None = Field(description="The most recently confirmed Kangaroo Tail reversal pattern (docs/ideas.md, Elder ch. 20 'fingers') -- a single bar's range roughly 2.5x the recent average, protruding from a tight recent range, closing back near its own open, flanked by two normal-height bars, and confirmed by the very next bar continuing in the implied direction. Null if none currently qualifies. Detection + exposure only -- not wired into signal/confidence_breakdown (see the backend-kangaroo-tail-pattern task's decisions).")


# --- /api/stocks/{ticker}/indicators ------------------------------------


class IndicatorHistoryPoint(BaseModel):
    date: date
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
    signal: Signal = Field(description="BUY/SELL/HOLD as of this bar (docs/Analyse.md §5), computed from only this bar's own history -- never look-ahead from a later bar.")
    confidence: int = Field(description="Same 0-100 weighted composite score as AnalysisResponse.confidence, for this bar's signal. 0 whenever signal is HOLD, same convention as GET /api/stocks/{ticker}/analysis.")
    confidence_band: ConfidenceBand = Field(description="Low <40, Medium 40-70, High >70, for this bar's confidence.")
    divergence: DivergenceOut | None = Field(default=None, description="Same definition as AnalysisResponse.divergence, using only swing points confirmable from data available through this bar (no look-ahead) -- so this can differ from a later bar's divergence at the same underlying extreme dates once more history confirms a swing point AnalysisResponse.divergence.")
    kangaroo_tail: KangarooTailOut | None = Field(default=None, description="Same definition as AnalysisResponse.kangaroo_tail, restricted per-bar to only a tail whose own confirming bar has arrived by this bar (no look-ahead) -- so this stays null for every bar strictly between a tail's own date and its confirmed_date, then reports that same tail from confirmed_date onward until (if ever) a later one supersedes it.")


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


class PortfolioResponse(BaseModel):
    equity: Equity
    positions: list[PositionOut]


class PositionIn(BaseModel):
    ticker: str = Field(min_length=1, description="Stock ticker symbol, normalized to uppercase (leading/trailing whitespace is stripped). Adding a ticker that's already held merges into the existing position (quantity-weighted average cost basis) rather than creating a duplicate row — see the api-portfolio-add-position task's decisions.")
    quantity: float = Field(gt=0, allow_inf_nan=False, description="Number of shares being added. Must be a positive, finite number (Infinity/NaN are rejected) — this endpoint only adds to a position; use DELETE /api/portfolio/positions/{id} to remove one.")
    avg_cost_basis: float = Field(gt=0, allow_inf_nan=False, description="Price paid per share for this lot. On merge with an existing position, this is blended into a quantity-weighted average, not overwritten. Must be a positive, finite number (Infinity/NaN are rejected).")
    entry_date: date = Field(description="Date this lot was purchased. On merge with an existing position, the earlier of the two entry dates is kept.")

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
    protective_stop: float = Field(description="Recent swing low minus a volatility buffer (SafeZone concept, docs/Analyse.md §7).")
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


class ClosedTradesResponse(BaseModel):
    items: list[ClosedTradeOut] = Field(
        description="Every closed trade (the docs/Analyse.md §7 trade-history/ledger table), "
        "most recently exited first."
    )


# --- shared error shape (FastAPI default, documented for clarity) ---------


class ErrorDetail(BaseModel):
    detail: str
