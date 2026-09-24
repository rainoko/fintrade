from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Literal, cast

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.day_trader_signal import compute_day_trader_signal, trading_mode_setting_to_schema
from app.api.dependencies import get_data_provider, get_ibkr_provider
from app.api.indicator_history_cache import IndicatorHistoryResponseCache
from app.api.schemas import (
    AnalysisResponse,
    ConfidenceBreakdownItem,
    DivergenceOut,
    ErrorDetail,
    ExtendedDataOut,
    FalseBreakoutOut,
    HistoryResponse,
    IndicatorHistoryPoint,
    IndicatorHistoryResponse,
    Indicators,
    InsiderClusterOut,
    InsiderTransactionOut,
    KangarooTailOut,
    OHLCVBar,
    ProfitTargetOut,
    Screens,
    SupportResistanceZone,
    TideScreen,
    TrendStrength,
)
from app.data.base import DataProvider, ExtendedData
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.ibkr_provider import IBKRProvider
from app.db.session import get_db
from app.indicators.accumulation_distribution import (
    accumulation_distribution as compute_accumulation_distribution,
)
from app.indicators.obv import obv as compute_obv
from app.portfolio.profit_target import ProfitTarget, suggest_profit_target
from app.signals.divergence import Divergence
from app.signals.engine import SignalResult, analyse, analyse_history, drop_malformed_daily_bars
from app.signals.insider_clusters import InsiderCluster, detect_insider_clusters
from app.signals.kangaroo_tail import KangarooTail
from app.signals.support_resistance import Zone, detect_support_resistance_zones
from app.signals.timeframe import TradingMode
from app.trading_mode import get_trading_mode_setting

# Accepted `range` query values: '<N>d' | '<N>w' | '<N>m' | '<N>y' (e.g. '1y', '6m', '90d'),
# or the literal 'max' for full available history. Matches the one example API.md gives
# ('1y') and mirrors yfinance's own period vocabulary (docs/architecture/API.md
# #get-apistocksstickerhistory) without accepting yfinance's other period spellings
# ('ytd', '5d' with no unit, etc.) that this endpoint doesn't document. See this task's
# `decisions` entry.
#
# The digit run is capped at 4 characters (max 9999) rather than left unbounded: an
# unbounded `\d+` still matches things like '999999999y' or a 20+ digit count, which
# `_trim_to_range`'s `pd.DateOffset` arithmetic can't handle (Timestamp under/overflow) --
# see docs/tasks/api-stocks-history-followups.json. Capping the digit count here means
# FastAPI's own pattern validation rejects those with the standard 422
# HTTPValidationError shape before `_trim_to_range` ever runs. `_trim_to_range` still
# guards its own arithmetic (a 4-digit count can still overflow for 'm'/'y' units, e.g.
# '9999y') so that path is never a bare 500 either.
_RANGE_PATTERN = r"^(max|\d{1,4}[dwmy])$"

# How many calendar days ahead an upcoming earnings date must fall within to set
# `ExtendedDataOut.earnings_within_warning_days` (Elder ch. 58's gap-through-the-stop risk).
# Not itself documented as a specific number of days in Analyse.md/Elder's book -- 14 days (two
# calendar weeks) was chosen as a reasonable "worth reconsidering a fresh entry, or planning
# around, right now" horizon: long enough to give real advance notice, short enough that it
# doesn't flag almost every actively-traded ticker's *next* quarterly report as "imminent". See
# this task's `decisions` entry.
_EARNINGS_WARNING_DAYS = 14

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


class _RangeOutOfBoundsError(ValueError):
    """Raised by `_trim_to_range` when a `range` value that passed `_RANGE_PATTERN` still
    can't be turned into a valid cutoff date -- e.g. '9999y', which is within the pattern's
    4-digit cap but still overflows `pd.Timestamp`'s ~1677-2262 bounds when subtracted from
    the anchor. Caught in `get_history` and mapped to the same 422 path as a
    pattern-rejected `range`, per docs/tasks/api-stocks-history-followups.json."""


# Route bodies are stubs (see the add-api-endpoint skill) — the signatures,
# response_models, and error responses below are real and drive the OpenAPI
# schema the frontend generates its types from (docs/architecture/API.md).
# Keep this contract accurate even while unimplemented: it's what lets
# frontend and backend work proceed in parallel.


@router.get(
    "/{ticker}/history",
    response_model=HistoryResponse,
    operation_id="get_stock_history",
    summary="Get OHLCV price history",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown ticker"},
        422: {
            "description": "Either of two distinct shapes, both under HTTP 422: `range` doesn't "
            "match the accepted pattern (FastAPI's standard HTTPValidationError — `detail` is a "
            "list of per-field errors), or the requested weekly interval has fewer than 26 weeks "
            "of history (`detail` is a single string, ErrorDetail) — same dual-shape pattern as "
            "`POST /api/portfolio/positions`.",
            "content": {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            {"$ref": "#/components/schemas/HTTPValidationError"},
                            {"$ref": "#/components/schemas/ErrorDetail"},
                        ],
                    },
                },
            },
        },
        503: {"model": ErrorDetail, "description": "Market data provider unavailable"},
    },
)
def get_history(
    ticker: str,
    range: str = Query(
        "1y",
        pattern=_RANGE_PATTERN,
        description="Lookback window: '<N>d' | '<N>w' | '<N>m' | '<N>y' (e.g. '1y', '6m', '90d'), "
        "or 'max' for full available history. Trimmed from the most recent bar actually "
        "returned, not from today's date.",
    ),
    interval: Literal["daily", "weekly"] = Query("daily"),
    provider: DataProvider = Depends(get_data_provider),
) -> HistoryResponse:
    """Raw OHLCV bars for charting, served from the SQLite cache (docs/architecture/Backend.md §7)
    and backfilled from yfinance/Stooq on a cache miss. Weekly bars are yfinance's native
    weekly interval, not a manual resample of daily bars, per docs/Analyse.md §9.

    `ticker` is normalized to uppercase, matching `GET /api/stocks/{ticker}/analysis` and
    `POST /api/portfolio/positions`. Only the interval actually requested is fetched (unlike
    `/analysis`, which always needs both) -- so a `weekly`-interval request is the only way
    this endpoint can itself raise the same <26-week `InsufficientHistoryError` -> 422 that
    `/analysis`'s weekly fetch enforces (`app.data.yfinance_provider.YFinanceProvider._MIN_WEEKLY_BARS`);
    see this task's `decisions` entry for why that's surfaced here too rather than only for
    computed indicators."""
    ticker = ticker.upper()
    try:
        if interval == "weekly":
            ohlcv = provider.get_weekly_ohlcv(ticker)
        else:
            ohlcv = provider.get_daily_ohlcv(ticker)
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        ohlcv = _trim_to_range(ohlcv, range)
    except _RangeOutOfBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    bars = [
        OHLCVBar(
            date=idx.date() if hasattr(idx, "date") else idx,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for idx, row in ohlcv.iterrows()
    ]
    return HistoryResponse(ticker=ticker, interval=interval, bars=bars)


def _trim_to_range(ohlcv: pd.DataFrame, range_param: str) -> pd.DataFrame:
    """Trim `ohlcv` (already the provider's full cached/fetched history -- the `DataProvider`
    protocol itself takes no date-range argument, see app/data/cache.py's module docstring) to
    the trailing `range_param` window.

    Anchored on the most recent bar actually present in `ohlcv`, not on today's wall-clock
    date: the cache can be up to 24h stale (app/data/cache.py's `_CACHE_TTL`), and a
    delisted/thinly-traded ticker's history may not extend to the present at all -- anchoring
    on "today" in either case would silently return fewer bars than the requested range implies.

    Raises `_RangeOutOfBoundsError` (never a bare `ValueError`/`OverflowError`) if `count` is
    large enough that the `pd.DateOffset` arithmetic below can't produce a valid cutoff --
    `_RANGE_PATTERN`'s 4-digit cap keeps this to the 'm'/'y' units only in practice, but the
    guard is unconditional so it's not relying on that cap alone.
    """
    if range_param == "max" or ohlcv.empty:
        return ohlcv
    count = int(range_param[:-1])
    unit = range_param[-1]
    anchor = ohlcv.index[-1]
    try:
        if unit == "d":
            # `pd.DateOffset`, not `pd.Timedelta`, for every unit here --
            # `pd.Timedelta(days=...)` / `pd.Timedelta(weeks=...)` alone (no other kwarg)
            # trip a spurious NumPy "'generic' unit" DeprecationWarning on this
            # pandas/NumPy pairing even though the arithmetic itself is correct;
            # `DateOffset` sidesteps it and reads the same.
            cutoff = anchor - pd.DateOffset(days=count)
        elif unit == "w":
            cutoff = anchor - pd.DateOffset(weeks=count)
        elif unit == "m":
            cutoff = anchor - pd.DateOffset(months=count)
        else:  # "y"
            cutoff = anchor - pd.DateOffset(years=count)
    except (ValueError, OverflowError) as exc:
        raise _RangeOutOfBoundsError(
            f"range '{range_param}' is out of bounds"
        ) from exc
    return ohlcv[ohlcv.index > cutoff]


def _zone_to_schema(zone: Zone) -> SupportResistanceZone:
    """Maps `app.signals.support_resistance.Zone` (the domain type, keeping `pd.Timestamp`
    fields per that module's own contract) onto `SupportResistanceZone` (the API schema,
    plain `datetime.date` fields) -- mirrors the `cast(Screens, ...)`/`cast(Indicators, ...)`
    boundary `get_analysis` already draws between `app.signals.engine`'s dicts and their
    schema counterparts, just via an explicit field-by-field mapping instead of a cast, since
    `Zone` is a dataclass (not already dict-shaped like `SignalResult.screens`/`.indicators`)."""
    return SupportResistanceZone(
        role=zone.role,
        upper=zone.upper,
        lower=zone.lower,
        first_touch_date=zone.first_touch_date.date(),
        last_touch_date=zone.last_touch_date.date(),
        touch_count=zone.touch_count,
        length_days=zone.length_days,
        length_category=zone.length_category,
        height_pct=zone.height_pct,
        height_category=zone.height_category,
        dollar_volume=zone.dollar_volume,
        strength_score=zone.strength_score,
        broken=zone.broken,
        break_date=zone.break_date.date() if zone.break_date is not None else None,
        false_breakout=(
            FalseBreakoutOut(
                direction=zone.false_breakout.direction,
                breakout_date=zone.false_breakout.breakout_date.date(),
                reentry_date=zone.false_breakout.reentry_date.date(),
                extreme_price=zone.false_breakout.extreme_price,
            )
            if zone.false_breakout is not None
            else None
        ),
    )


def _divergence_to_schema(divergence: Divergence) -> DivergenceOut:
    """Maps `app.signals.divergence.Divergence` (the domain type, keeping `pd.Timestamp` dates
    per that module's own contract) onto `DivergenceOut` (the API schema, plain `datetime.date`
    fields) -- same boundary-mapping pattern as `_zone_to_schema` above."""
    return DivergenceOut(
        kind=divergence.kind,
        indicator=divergence.indicator,
        first_extreme_date=divergence.first.date.date(),
        first_extreme_price=divergence.first.price,
        first_extreme_indicator_value=divergence.first.indicator_value,
        second_extreme_date=divergence.second.date.date(),
        second_extreme_price=divergence.second.price,
        second_extreme_indicator_value=divergence.second.indicator_value,
        bars_apart=divergence.bars_apart,
        centerline_crossed=divergence.centerline_crossed,
        beyond_reference_line=divergence.beyond_reference_line,
        aborted=divergence.aborted,
    )


def _kangaroo_tail_to_schema(tail: KangarooTail) -> KangarooTailOut:
    """Maps `app.signals.kangaroo_tail.KangarooTail` (the domain type, keeping `pd.Timestamp`
    dates per that module's own contract) onto `KangarooTailOut` (the API schema, plain
    `datetime.date` fields) -- same boundary-mapping pattern as `_divergence_to_schema` above."""
    return KangarooTailOut(
        direction=tail.direction,
        tail_date=tail.date.date(),
        confirmed_date=tail.confirmed_date.date(),
        high=tail.high,
        low=tail.low,
        range_multiple=tail.range_multiple,
        suggested_stop=tail.suggested_stop,
    )


def _profit_target_to_schema(target: ProfitTarget) -> ProfitTargetOut:
    """Maps `app.portfolio.profit_target.ProfitTarget` (the domain type) onto `ProfitTargetOut`
    (the API schema) -- same boundary-mapping pattern as `_zone_to_schema`/`_divergence_to_
    schema`/`_kangaroo_tail_to_schema` above (no `pd.Timestamp` fields here, so this one is a
    straight 1:1 field copy)."""
    return ProfitTargetOut(
        price=target.price,
        source=target.source,
        distance_to_stop=target.distance_to_stop,
        distance_to_target=target.distance_to_target,
        reward_risk_ratio=target.reward_risk_ratio,
        meets_minimum_reward_risk=target.meets_minimum_reward_risk,
    )


def _earnings_within_warning_days(earnings_date: date | None, today: date) -> bool:
    """Whether `earnings_date` falls within `_EARNINGS_WARNING_DAYS` calendar days from `today`
    (Elder ch. 58: a nasty earnings surprise can gap straight through a technical stop).

    Anchored on real wall-clock `today` (the caller passes `date.today()`), not `as_of`/the
    latest cached daily bar's own date: an earnings date is a real calendar event independent
    of how fresh the OHLCV cache happens to be (`app.data.cache`'s up-to-24h TTL) -- using a
    stale `as_of` here could under- or over-count the days remaining by however stale the cache
    is. `False` (never left ambiguous) when `earnings_date` is null or already in the past --
    there's nothing to warn about in either case.
    """
    if earnings_date is None:
        return False
    return today <= earnings_date <= today + timedelta(days=_EARNINGS_WARNING_DAYS)


def _extended_data_to_schema(extended: ExtendedData, *, today: date) -> ExtendedDataOut:
    """Maps `app.data.base.ExtendedData` (the data-provider-layer domain type) onto
    `ExtendedDataOut` (the API schema) -- same boundary-mapping pattern as `_zone_to_schema`/
    `_divergence_to_schema`/`_kangaroo_tail_to_schema`/`_profit_target_to_schema` above, plus
    deriving `earnings_within_warning_days` (not present on the domain type -- a pure
    presentation-layer computation, so it belongs at this mapping boundary, not in
    `app.data`)."""
    return ExtendedDataOut(
        earnings_date=extended.earnings_date,
        earnings_within_warning_days=_earnings_within_warning_days(extended.earnings_date, today),
        ex_dividend_date=extended.ex_dividend_date,
        shares_short=extended.shares_short,
        short_ratio=extended.short_ratio,
        short_percent_of_float=extended.short_percent_of_float,
        float_shares=extended.float_shares,
        insider_transactions=[
            InsiderTransactionOut(
                insider=t.insider,
                position=t.position,
                transaction_text=t.transaction_text,
                shares=t.shares,
                value=t.value,
                start_date=t.start_date,
                ownership=t.ownership,
            )
            for t in extended.insider_transactions
        ],
        unavailable_reason=extended.unavailable_reason,
    )


def _insider_cluster_to_schema(cluster: InsiderCluster) -> InsiderClusterOut:
    """Maps `app.signals.insider_clusters.InsiderCluster` (the domain type -- plain
    `datetime.date` fields already, unlike `Zone`/`Divergence`/`KangarooTail` above, since
    `InsiderTransaction.start_date` is itself a plain `date`, not a `pd.Timestamp`) onto
    `InsiderClusterOut` (the API schema) -- same boundary-mapping pattern as
    `_zone_to_schema`/`_divergence_to_schema`/`_kangaroo_tail_to_schema`/
    `_profit_target_to_schema` above, a straight 1:1 field copy here."""
    return InsiderClusterOut(
        direction=cluster.direction,
        window_start_date=cluster.window_start_date,
        window_end_date=cluster.window_end_date,
        insiders=cluster.insiders,
        transaction_count=cluster.transaction_count,
        total_shares=cluster.total_shares,
        total_value=cluster.total_value,
    )


@router.get(
    "/{ticker}/analysis",
    response_model=AnalysisResponse,
    operation_id="get_stock_analysis",
    summary="Get the Triple Screen signal, confidence, and indicator breakdown",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown ticker"},
        422: {"model": ErrorDetail, "description": "Insufficient history to compute weekly indicators"},
        503: {
            "model": ErrorDetail,
            "description": "Market data provider unavailable -- either the ordinary yfinance/"
            "Stooq daily/weekly fetch failed, or (day-trader mode only, see "
            "AnalysisResponse.trading_mode) the active day-trader timeframe triple's IBKR "
            "intraday data couldn't be fetched right now (IBKR disabled/unreachable/"
            "unauthenticated, this ticker's IBKR contract id not resolving, or the active "
            "triple having a non-intraday leg -- see backend-day-trader-timeframe-mode-api's "
            "`decisions` entry).",
        },
    },
)
def get_analysis(
    ticker: str,
    provider: DataProvider = Depends(get_data_provider),
    db: Session = Depends(get_db),
    ibkr_provider: IBKRProvider | None = Depends(get_ibkr_provider),
) -> AnalysisResponse:
    """Runs the full Triple Screen evaluation (tide, wave, trigger, Impulse gate) and the
    weighted confidence score for `ticker` (docs/Analyse.md §2-6). `confidence_breakdown`
    exposes the per-component scores so the signal is auditable, not just a bare number.

    `ticker` is normalized to uppercase (mirrors `POST /api/portfolio/positions`'s handling
    of the same field) before being passed to the data provider and echoed back in the
    response. Daily and weekly OHLCV are fetched via the SQLite-backed cache
    (`app.data.cache.CachedDataProvider`, docs/architecture/Backend.md §7); the weekly fetch
    is what actually enforces the <26-week-history -> 422 rule
    (`app.data.yfinance_provider.YFinanceProvider._MIN_WEEKLY_BARS`) -- this handler adds no
    separate minimum-history check of its own, matching `app.signals.engine.analyse`'s own
    documented degrade-gracefully-to-HOLD behavior for a short/empty daily series (see this
    task's `decisions` entry).

    `daily_ohlcv` has any malformed bar (NaN open/high/low/close -- a real observed
    unsettled-latest-bar condition) dropped via `app.signals.engine.drop_malformed_daily_bars`
    before `as_of` is derived from it, so `as_of` reflects the same freshest *real* bar that
    actually drove `analyse()` -- not a malformed bar `analyse()` itself excludes internally
    anyway (see that function's own docstring and this task's `decisions` entry).

    `profit_target` (`app.portfolio.profit_target.suggest_profit_target`, docs/Analyse.md §7)
    is only ever computed for a fresh BUY `signal` -- see that module's own docstring and the
    `backend-profit-target` task's `decisions` entry for why this app's long-only protective-
    stop formula rules out a symmetric SELL-side reward:risk ratio.

    `extended_data` (earnings/dividend dates, short interest, insider transactions -- see
    `ExtendedDataOut`'s own field descriptions) is fetched in the same try/except as
    `daily_ohlcv`/`weekly_ohlcv` above, so a `DataProviderUnavailableError` from it maps to the
    same 503 -- in practice this only happens if *both* the primary and fallback providers fail
    on this specific call, since the fallback (Stooq) provider always succeeds with an
    explicit "unsupported" result rather than raising (see `app.data.stooq_provider.
    StooqProvider.get_extended_data`'s own docstring and this task's `decisions` entry).

    `insider_clusters` (`app.signals.insider_clusters.detect_insider_clusters`, Elder ch. 37
    p. 147) is computed from `extended_data.insider_transactions` right here in the handler,
    same as `support_resistance_zones`/`zones` above -- see the backend-insider-transaction-
    clusters task's `decisions` entry for why this lives as its own top-level response field
    (a computed detection result, like `support_resistance_zones`/`divergence`/`kangaroo_tail`)
    rather than nested inside the raw `extended_data` object.

    `trading_mode`/`signal`/`confidence`/`confidence_band`/`screens`/`indicators`/
    `confidence_breakdown` (`backend-day-trader-timeframe-mode-api`): while the global trading
    mode (`app.trading_mode.get_trading_mode_setting`) is `'swing'` (this app's default, and
    every behavior before this task existed), these are computed exactly as described above --
    `analyse(ticker, daily_ohlcv, weekly_ohlcv)`, unchanged bar-for-bar. While it's
    `'day_trader'`, they're instead computed by `app.api.day_trader_signal
    .compute_day_trader_signal` -- fetching the active `TimeframeTriple`'s three legs via IBKR
    (`app.data.day_trader_intraday`) and running `app.signals.engine.analyse_day_trader` over
    them -- and this handler raises `503` instead of returning a partial/degraded response if
    that data isn't available right now (see this function's own `responses={}` 503 entry and
    `compute_day_trader_signal`'s own docstring for every reason that can happen), rather than
    ever returning `AnalysisResponse` with a `signal`/`confidence`/`screens`/`indicators` that
    don't reflect real market data -- this endpoint's `signal`/`confidence`/etc. fields are
    non-nullable specifically so a `200` always means a real, fully-computed result, in either
    mode. `support_resistance_zones`/`profit_target`/`extended_data`/`insider_clusters`/`as_of`
    are unaffected either way -- always derived from `daily_ohlcv`/`weekly_ohlcv` regardless of
    trading mode, per this task's own decision to defer the portfolio/profit-target layer's
    hard-coded weekly/daily split to a follow-up (docs/architecture/Backend.md §10)."""
    ticker = ticker.upper()
    try:
        daily_ohlcv = provider.get_daily_ohlcv(ticker)
        weekly_ohlcv = provider.get_weekly_ohlcv(ticker)
        extended = provider.get_extended_data(ticker)
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)

    trading_mode_setting = get_trading_mode_setting(db)
    result: SignalResult
    if (
        trading_mode_setting.mode is TradingMode.DAY_TRADER
        and trading_mode_setting.day_trader_timeframe_triple is not None
    ):
        outcome = compute_day_trader_signal(
            ticker, trading_mode_setting.day_trader_timeframe_triple, provider=ibkr_provider
        )
        if outcome.signal_result is None:
            raise HTTPException(
                status_code=503,
                detail=f"Day-trader mode signal data unavailable for '{ticker}': "
                f"{outcome.unavailable_reason}",
            )
        result = outcome.signal_result
    else:
        result = analyse(ticker, daily_ohlcv, weekly_ohlcv)
    # Computed directly here rather than inside `app.signals.engine.analyse()`/
    # `analyse_history()`: unlike every other `indicators`/`screens` field, zone detection
    # isn't a per-bar scalar `analyse_history()`'s precompute-and-slice pattern would benefit
    # from sharing -- it's a whole-history swing/cluster/breakout pass consumed only here (this
    # task's checklist scopes exposure to GET /api/stocks/{ticker}/analysis only, not
    # GET /api/stocks/{ticker}/indicators), so folding it into `analyse()` would pay its cost
    # on every one of `analyse_history()`'s up-to-thousands of per-bar calls for no consumer --
    # see this task's `decisions` entry.
    zones = detect_support_resistance_zones(daily_ohlcv)
    # BUY-only (see app.portfolio.profit_target's module docstring and this task's `decisions`
    # entry for why) -- reuses `zones` above (the daily support/resistance candidate) but passes
    # `weekly_ohlcv` (already fetched above) rather than `result.indicators["channel_upper"/
    # "channel_lower"]`: per Elder ch. 39 p.161 ("the value zone on a weekly chart presents a
    # good target"), the channel candidate is computed from the WEEKLY chart inside
    # `suggest_profit_target` itself, a separate pass from the DAILY channel `indicators`
    # reports for the price-chart overlay -- see the backend-profit-target-weekly-channel
    # task's `decisions` entry.
    profit_target = (
        suggest_profit_target(
            daily_ohlcv,
            zones,
            weekly_ohlcv=weekly_ohlcv,
        )
        if result.signal == "BUY"
        else None
    )

    latest_bar = daily_ohlcv.index[-1] if len(daily_ohlcv) > 0 else weekly_ohlcv.index[-1]
    as_of = latest_bar.date() if hasattr(latest_bar, "date") else latest_bar

    return AnalysisResponse(
        ticker=ticker,
        as_of=as_of,
        trading_mode=trading_mode_setting_to_schema(trading_mode_setting),
        signal=result.signal,
        confidence=result.confidence,
        confidence_band=result.confidence_band,
        # `SignalResult.screens`/`.indicators` are typed as plain `dict` in
        # app.signals.engine (the domain layer deliberately doesn't import the API
        # schema types, per docs/Architecture.md's layering) but are actually always
        # built by `analyse()` to match `Screens`/`Indicators`' shape exactly. Pydantic
        # validates the shape at construction time here regardless, so this `cast` is
        # a static-typing annotation only, not a runtime assumption -- see this task's
        # `decisions` entry.
        screens=cast(Screens, result.screens),
        confidence_breakdown=[
            ConfidenceBreakdownItem(component=c.component, weight=c.weight, score=c.score)
            for c in result.breakdown
        ],
        indicators=cast(Indicators, result.indicators),
        support_resistance_zones=[_zone_to_schema(zone) for zone in zones],
        divergence=_divergence_to_schema(result.divergence) if result.divergence is not None else None,
        kangaroo_tail=(
            _kangaroo_tail_to_schema(result.kangaroo_tail) if result.kangaroo_tail is not None else None
        ),
        profit_target=_profit_target_to_schema(profit_target) if profit_target is not None else None,
        extended_data=_extended_data_to_schema(extended, today=date.today()),
        insider_clusters=[
            _insider_cluster_to_schema(cluster)
            for cluster in detect_insider_clusters(extended.insider_transactions)
        ],
    )


@router.get(
    "/{ticker}/indicators",
    response_model=IndicatorHistoryResponse,
    operation_id="get_stock_indicator_history",
    summary="Get historical indicator values and the resulting signal for each daily bar",
    responses={
        404: {"model": ErrorDetail, "description": "Unknown ticker"},
        422: {
            "description": "Either of two distinct shapes, both under HTTP 422: `range` doesn't "
            "match the accepted pattern (FastAPI's standard HTTPValidationError -- `detail` is a "
            "list of per-field errors), or the ticker has fewer than 26 weeks of weekly history "
            "to compute Screen 1's Tide (`detail` is a single string, ErrorDetail) -- same "
            "dual-shape pattern as `GET /api/stocks/{ticker}/history`.",
            "content": {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            {"$ref": "#/components/schemas/HTTPValidationError"},
                            {"$ref": "#/components/schemas/ErrorDetail"},
                        ],
                    },
                },
            },
        },
        503: {"model": ErrorDetail, "description": "Market data provider unavailable"},
    },
)
def get_indicator_history(
    ticker: str,
    range: str = Query(
        "1y",
        pattern=_RANGE_PATTERN,
        description="Same lookback-window grammar as GET /api/stocks/{ticker}/history's `range`: "
        "'<N>d' | '<N>w' | '<N>m' | '<N>y' (e.g. '1y', '6m', '90d'), or 'max' for full available "
        "history. Trimmed from the most recent bar actually returned, not from today's date. "
        "Daily bars only -- unlike /history, this endpoint has no `interval` param, since every "
        "indicator/Screen it computes (docs/Analyse.md §4) is itself daily-cadence; see this "
        "task's `decisions` entry.",
    ),
    provider: DataProvider = Depends(get_data_provider),
    db: Session = Depends(get_db),
) -> IndicatorHistoryResponse:
    """Re-runs the Triple Screen signal engine (`app.signals.engine.analyse`, via
    `app.signals.engine.analyse_history`) once per daily bar in the requested range, each time
    using only that bar's own history (no look-ahead) -- so the frontend can plot indicator
    lines and BUY/SELL/HOLD markers over time, instead of only the latest-bar snapshot
    `GET /api/stocks/{ticker}/analysis` returns. See docs/architecture/Frontend.md §5 and this
    task's `decisions` entry for the endpoint-shape rationale, and `analyse_history`'s own
    docstring (plus `app.signals.engine._long_term_through_bar_date`) for how Screen 1/Tide is
    itself recomputed per bar from only the weekly data available as of that bar's own
    calendar week -- not held fixed at today's value.

    The computed response is served from a same-calendar-day `(ticker, range)`-keyed cache
    (`app.api.indicator_history_cache.IndicatorHistoryResponseCache`,
    docs/tasks/backend-indicator-history-performance.json) when a fresh entry exists -- the
    whole per-bar recompute below, and both OHLCV fetches, are skipped entirely on a cache hit.
    Only a successfully computed response is cached; an error response (404/422/503) never is.

    `ticker` is normalized to uppercase, matching the other `/api/stocks/*` routes. On a cache
    miss, daily and weekly OHLCV are fetched concurrently (not sequentially) since neither
    depends on the other; if either fetch fails, that failure is what's raised, matching this
    endpoint's previous sequential-fetch error priority (a failing daily fetch takes priority
    over a failing weekly one, since sequentially the daily fetch would have failed first and
    the weekly fetch would never even have started). Malformed bars (NaN OHLC, see
    `app.signals.engine.drop_malformed_daily_bars`) are dropped from `daily_ohlcv` up front,
    same as `/analysis`. The full (untrimmed) daily history is always fetched first so every
    emitted point -- including ones near the start of the requested `range` -- has correct
    indicator warm-up context; `range` only controls which already-computed points are included
    in the response, not how much history feeds the computation. The last entry in `points`
    matches `GET /api/stocks/{ticker}/analysis`'s `signal`/`confidence`/`indicators` for this
    same ticker at the same date whenever both are computed fresh (same untruncated inputs) --
    but a same-calendar-day cache hit here can still return a signal computed from an
    earlier-in-the-day OHLCV snapshot even after `/analysis`'s own (uncached) call has since
    picked up a refreshed `ohlcv_cache` row for the rest of that calendar day; see this task's
    `decisions` entry and its `-followups` task for the accepted tradeoff."""
    ticker = ticker.upper()
    response_cache = IndicatorHistoryResponseCache(db)
    cached_response = response_cache.get(ticker, range)
    if cached_response is not None:
        return cached_response

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            daily_future = executor.submit(provider.get_daily_ohlcv, ticker)
            weekly_future = executor.submit(provider.get_weekly_ohlcv, ticker)
            # Resolved in this order (daily first, then weekly) so a daily-fetch failure
            # always takes priority over a weekly-fetch failure, matching the previous
            # sequential implementation's error priority -- see this function's own docstring.
            daily_ohlcv = daily_future.result()
            weekly_ohlcv = weekly_future.result()
    except TickerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)

    try:
        visible_daily = _trim_to_range(daily_ohlcv, range)
    except _RangeOutOfBoundsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    from_index = len(daily_ohlcv) - len(visible_daily)
    history = analyse_history(ticker, daily_ohlcv, weekly_ohlcv, from_index=from_index)

    # OBV/A-D are purely causal cumulative running totals (each bar's value depends only on
    # data up to and including it, no Screen/gate machinery involved) -- computed once over
    # the full (untrimmed) `daily_ohlcv` so their cumulative level is anchored to this
    # ticker's entire available history regardless of the requested `range` (matching every
    # other indicator series here, which is why they don't need to flow through
    # `analyse`/`analyse_history` the way Screen-dependent indicators do). See this task's
    # `decisions` entry (docs/tasks/backend-indicator-obv-ad.json).
    obv_full = compute_obv(daily_ohlcv["close"], daily_ohlcv["volume"])
    accumulation_distribution_full = compute_accumulation_distribution(
        daily_ohlcv["open"], daily_ohlcv["high"], daily_ohlcv["low"], daily_ohlcv["close"], daily_ohlcv["volume"]
    )

    points = [
        IndicatorHistoryPoint(
            date=bar_date.date(),
            # Same cast-only-for-mypy pattern as `get_analysis`'s `screens=cast(Screens, ...)`
            # above -- `result.screens["tide"]` is always built by `analyse()`/`analyse_history()`
            # to match `TideScreen`'s shape exactly (`trend` + `weekly_macd_histogram_slope`);
            # Pydantic validates it at construction time regardless. See this task's `decisions`.
            tide=cast(TideScreen, result.screens["tide"]),
            ema_13=result.indicators["ema_13"],
            ema_26=result.indicators["ema_26"],
            macd_histogram=result.indicators["macd_histogram"],
            bull_power=result.indicators["bull_power"],
            bear_power=result.indicators["bear_power"],
            stochastic_k=result.screens["wave"]["stochastic_k"],
            force_index_2ema=result.screens["wave"]["force_index_2ema"],
            channel_upper=result.indicators["channel_upper"],
            channel_lower=result.indicators["channel_lower"],
            rsi=result.indicators["rsi"],
            season=result.indicators["season"],
            # Same cast-only-for-mypy pattern as `tide=cast(TideScreen, ...)` above --
            # `result.indicators["trend_strength"]` is always built by `analyse()`/
            # `analyse_history()` to match `TrendStrength`'s shape exactly; Pydantic validates
            # it at construction time regardless.
            trend_strength=cast(TrendStrength, result.indicators["trend_strength"]),
            signal=result.signal,
            confidence=result.confidence,
            confidence_band=result.confidence_band,
            divergence=_divergence_to_schema(result.divergence) if result.divergence is not None else None,
            kangaroo_tail=(
                _kangaroo_tail_to_schema(result.kangaroo_tail) if result.kangaroo_tail is not None else None
            ),
            obv=obv_full.iloc[from_index + offset],
            accumulation_distribution=accumulation_distribution_full.iloc[from_index + offset],
        )
        for offset, (bar_date, result) in enumerate(history)
    ]
    response = IndicatorHistoryResponse(ticker=ticker, points=points)
    response_cache.set(ticker, range, response)
    return response
