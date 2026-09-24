"""Day-trader mode: wire actual IBKR intraday data fetching for whichever leg(s) of the
active day-trader `TimeframeTriple` (`app.signals.timeframe`, `app.trading_mode`) need it
(docs/tasks/backend-day-trader-timeframe-mode-ibkr-intraday.json -- second of four dependent
follow-up tasks splitting docs/tasks/done/backend-day-trader-timeframe-mode.json's original
checklist item 4 out of that task).

**Genuine open design problem this module resolves** (see this task's own `decisions` entry
for the full writeup): IBKR's `/iserver/marketdata/history` endpoint
(`app.data.ibkr_provider.IBKRProvider.get_hourly_bars`) only accepts a fixed,
non-composable set of `bar` values (`_VALID_BAR_INTERVALS` -- 1/2/3/5/10/15/30 min, 1/2/3/4/8h,
1d/1w/1m), while `TimeframeInterval` is fully user-configurable (any positive integer count of
minutes/days/weeks). This module reconciles the two by fetching the *coarsest IBKR-supported
minute-based granularity that evenly divides the requested interval's minute count* (see
`_select_ibkr_bar_size`) and resampling client-side into the exact requested bar width -- mirroring
`app.data.stooq_provider.StooqProvider._resample_weekly`'s own daily-to-weekly resampling
precedent, generalized from a fixed calendar-week bucket to an arbitrary minute-count one.

Only `MINUTE`-unit legs of the triple need this module at all: a `DAY`/`WEEK`-unit leg (e.g.
an intermediate leg configured as `"1d"`) is already served by the existing always-on
yfinance/Stooq daily/weekly pipeline (`app.data.base.DataProvider`), the same as every leg of
swing mode's own weekly/daily triple -- IBKR is only needed for genuinely intraday bars no
other provider in this app can supply. `get_intraday_bars_for_triple` below reflects this: it
returns `None` for a leg whenever that leg's own unit isn't `MINUTE`, for all three legs
(`long_term`/`intermediate`/`short_term`) -- never guaranteed for any particular leg by
`TimeframeTriple`'s own validation, though `short_term` being intraday is day-trader mode's
usual/expected case.

**`long_term` fetching** (`backend-day-trader-timeframe-mode-signal-engine`, resolving a gap
this task's own PR #311 review flagged as a non-blocking finding -- see
`backend-day-trader-timeframe-mode-ibkr-intraday-followups.json`'s checklist and this task's
own `decisions` entry): the original version of this module (PR #311) only ever fetched
`short_term`/`intermediate`, on the reasoning that day-trader mode's "usual case" keeps
`long_term` on a slower, non-intraday timeframe. That's true for a mixed triple (e.g.
`long_term="1d"`), but **not** for ch. 39's own canonical day-trading examples -- 25-min/
5-min/2-min and 39-min/8-min are both *fully intraday* triples, where `long_term` is just as
much a `MINUTE`-unit leg as the other two. `get_intraday_bars_for_triple` now fetches all
three legs uniformly via the same `_fetch_leg` helper, so a fully-intraday triple is fully
supported, not silently missing its Tide/Screen-1 data.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from sqlalchemy.orm import Session

from app.data.base import resample_ohlcv
from app.data.ibkr_provider import IBKRBar, IBKRProvider, IBKRUnavailableError
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TimeframeUnit, TradingMode
from app.trading_mode import get_trading_mode_setting

# IBKR's own documented minute-and-hour-based `bar` values (`IBKRProvider
# ._VALID_BAR_INTERVALS`), keyed by their length in minutes -- the day/week-based values
# (`"1d"`/`"1w"`/`"1m"`) are deliberately excluded here since a `MINUTE`-unit
# `TimeframeInterval` (the only kind this module ever fetches for -- see this module's own
# docstring) is never usefully expressed as a whole number of IBKR trading days/weeks/months.
_IBKR_MINUTE_BAR_SIZES: dict[int, str] = {
    1: "1min",
    2: "2min",
    3: "3min",
    5: "5min",
    10: "10min",
    15: "15min",
    30: "30min",
    60: "1h",
    120: "2h",
    180: "3h",
    240: "4h",
    480: "8h",
}

_DISABLED_DETAIL = "IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set)."

# The distinguishable states a caller of this module can observe for one leg -- `"disabled"`
# and `"gateway_unreachable"`/`"not_authenticated"` mirror `app.data.ibkr_provider
# .GatewayState` + `app.api.routers.ibkr`'s existing `"disabled"` convention exactly (this
# module must degrade exactly the same way every other IBKR-dependent feature in this app
# does -- checklist item 3); `"unavailable"` is this module's equivalent of
# `app.api.routers.ibkr._resolve_scanner_unavailable`'s `HTTPException(503)` case (the
# gateway/session itself is fine, but this specific history call failed transiently) --
# there's no HTTP layer here to raise a 503 from, so it's surfaced as a fourth state instead.
IntradayAvailability = Literal["available", "disabled", "gateway_unreachable", "not_authenticated", "unavailable"]

DayTraderLeg = Literal["long_term", "intermediate", "short_term"]


@dataclass(frozen=True)
class IntradayLegResult:
    """The outcome of fetching one `MINUTE`-unit leg of the active day-trader triple.

    `ohlcv` (columns: open, high, low, close, volume; indexed by UTC timestamp, oldest-first
    -- the same shape `app.data.base.DataProvider` implementations return, so a future
    consumer of this module, e.g. `backend-day-trader-timeframe-mode-signal-engine`, can treat
    it identically) is populated **iff** `state == "available"`; every other state carries
    `ohlcv=None` and a human-readable `detail` instead, never a raised exception -- checklist
    item 3's "never a raw exception surfaced to a caller" requirement.

    `ibkr_bar_size` records the actual IBKR-native granularity fetched before any
    client-side resampling (e.g. `"5min"` for a requested `interval.code == "25m"`) --
    useful for logging/debugging the reconciliation this module performs, not something a
    caller needs to act on.
    """

    leg: DayTraderLeg
    interval: TimeframeInterval
    ibkr_bar_size: str
    state: IntradayAvailability
    detail: str | None
    ohlcv: pd.DataFrame | None


@dataclass(frozen=True)
class DayTraderIntradayBars:
    """The result of fetching intraday bars for whichever leg(s) of a `TimeframeTriple`
    need IBKR data. Each field is `None` when that leg's unit isn't `MINUTE` (it doesn't need
    IBKR at all -- see this module's own docstring); all three fields are `None` under exactly
    the same per-leg condition (that leg's own unit isn't `MINUTE`), even though day-trader
    mode's usual case has `short_term` (and often `intermediate`) always be intraday while
    `long_term` more often isn't -- `TimeframeTriple` itself doesn't enforce any of that, and a
    fully-intraday triple (ch. 39's own 25-min/5-min/2-min or 39-min/8-min examples, generalized
    to a third fully-configurable leg) needs `long_term` fetched here too -- see this module's
    own docstring."""

    long_term: IntradayLegResult | None
    short_term: IntradayLegResult | None
    intermediate: IntradayLegResult | None


def _select_ibkr_bar_size(target_minutes: int) -> tuple[str, int]:
    """The coarsest (largest) IBKR-supported bar interval that (a) is `<= target_minutes` and
    (b) evenly divides it, so the resampling in `_resample_to_target` below produces clean,
    fully-formed bins rather than partial ones misaligned to the requested bar width. The
    *largest* such candidate is chosen (not the finest available overall) to minimize how many
    raw bars need to be fetched and resampled -- e.g. a 30-minute target with `"5min"` bars
    available should fetch `"5min"` bars and resample 6:1, not fetch `"1min"` bars and
    resample 30:1 for the identical result.

    Always returns a result: `1` (`"1min"`) evenly divides every positive integer, so it's
    always at least one candidate even when the target isn't a multiple of any coarser
    supported interval (e.g. a 7-minute target only evenly divides by 1).

    Returns:
        A `(bar_size, chosen_minutes)` pair -- `bar_size` is the string to pass as
        `IBKRProvider.get_hourly_bars`'s `bar_size`; `chosen_minutes` is that bar size's own
        length in minutes, so the caller can tell whether resampling is actually needed
        (`chosen_minutes == target_minutes` means an exact match, no resampling required).
    """
    candidates = [minutes for minutes in _IBKR_MINUTE_BAR_SIZES if target_minutes % minutes == 0]
    chosen_minutes = max(candidates)
    return _IBKR_MINUTE_BAR_SIZES[chosen_minutes], chosen_minutes


def _bars_to_frame(bars: list[IBKRBar]) -> pd.DataFrame:
    """Converts `IBKRProvider.get_hourly_bars`'s `list[IBKRBar]` (already sorted oldest-first)
    into the `app.data.base.DataProvider`-shaped `pd.DataFrame` this module returns."""
    if not bars:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], name="date")
        )
    return pd.DataFrame(
        {
            "open": [bar.open for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
            "volume": [bar.volume for bar in bars],
        },
        index=pd.DatetimeIndex([bar.timestamp for bar in bars], name="date"),
    )


def _resample_to_target(frame: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """Resamples `frame` (fetched at some finer IBKR-native granularity, per
    `_select_ibkr_bar_size`) into `target_minutes`-wide bins, via the same shared
    `app.data.base.resample_ohlcv` helper `StooqProvider._resample_weekly` uses for its own
    daily-to-weekly resampling -- generalized here from a fixed calendar-week bucket to an
    arbitrary minute-count one (see this module's own docstring).

    Bin boundaries are pandas' own default resample origin (aligned to midnight, not to the
    US market's 9:30 ET open) -- an approximation, not a claim that every bin lines up exactly
    with a real intraday session boundary, matching `TimeframeInterval.approx_trading_minutes`'s
    own documented "adequate for this guideline-strength comparison, not a precise calendar
    computation" caveat elsewhere in this feature.
    """
    return resample_ohlcv(frame, f"{target_minutes}min")


def _fetch_leg(
    leg: DayTraderLeg,
    interval: TimeframeInterval,
    *,
    provider: IBKRProvider | None,
    conid: int,
    lookback_days: int,
) -> IntradayLegResult | None:
    if interval.unit is not TimeframeUnit.MINUTE:
        # A day/week-unit leg doesn't need IBKR at all -- see this module's own docstring.
        return None

    bar_size, chosen_minutes = _select_ibkr_bar_size(interval.count)

    if provider is None:
        return IntradayLegResult(
            leg=leg,
            interval=interval,
            ibkr_bar_size=bar_size,
            state="disabled",
            detail=_DISABLED_DETAIL,
            ohlcv=None,
        )

    try:
        raw_bars = provider.get_hourly_bars(conid, lookback_days=lookback_days, bar_size=bar_size)
    except IBKRUnavailableError as exc:
        # Mirrors app.api.routers.ibkr._resolve_scanner_unavailable's exact reasoning: a
        # fresh gateway-status check distinguishes "the gateway/session itself isn't
        # available" (this leg's failure is just a symptom) from "the gateway is fine, but
        # this specific history call failed transiently" (state="unavailable" -- this
        # module's equivalent of that router's HTTPException(503), since there's no HTTP
        # layer here to raise one from).
        status = provider.get_gateway_status()
        if status.state == "available":
            return IntradayLegResult(
                leg=leg,
                interval=interval,
                ibkr_bar_size=bar_size,
                state="unavailable",
                detail=str(exc),
                ohlcv=None,
            )
        return IntradayLegResult(
            leg=leg,
            interval=interval,
            ibkr_bar_size=bar_size,
            state=status.state,
            detail=status.detail,
            ohlcv=None,
        )

    frame = _bars_to_frame(raw_bars)
    if chosen_minutes != interval.count:
        frame = _resample_to_target(frame, interval.count)

    return IntradayLegResult(
        leg=leg,
        interval=interval,
        ibkr_bar_size=bar_size,
        state="available",
        detail=None,
        ohlcv=frame,
    )


def get_intraday_bars_for_triple(
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
    conid: int,
    lookback_days: int = 30,
) -> DayTraderIntradayBars:
    """Fetches intraday bars for whichever leg(s) of `triple` are `MINUTE`-unit (checklist
    item 2 of `backend-day-trader-timeframe-mode-ibkr-intraday`; extended to also fetch
    `long_term` by `backend-day-trader-timeframe-mode-signal-engine` -- see this module's own
    docstring) -- `provider=None` (matching `app.api.dependencies.get_ibkr_provider`'s own
    `Settings.ibkr_enabled=False` contract) degrades every applicable leg to
    `state="disabled"` rather than raising, so day-trader mode being *configured* never
    itself requires IBKR to be reachable (checklist item 3).

    The three legs are fetched **concurrently** (a small thread pool -- `IBKRProvider`'s HTTP
    calls are synchronous, so this is the same "offload blocking I/O to a thread" pattern as
    everywhere else in this codebase that overlaps otherwise-independent synchronous network
    calls) rather than sequentially, now that `app.api.day_trader_signal
    .compute_day_trader_signal` is a real caller requiring every leg to be `MINUTE`-unit (a
    fully-intraday triple): a request-latency-sensitive caller (`GET /api/stocks/{ticker}
    /analysis`, `GET /api/watchlist`) would otherwise pay three sequential IBKR round-trips
    per ticker instead of roughly one (see this task's own `decisions` entry for the
    measurement/tradeoff writeup). Each leg's own fetch is fully independent of the others'
    (no shared mutable state, no ordering requirement between them), so this is a
    straightforward fan-out/fan-in with no synchronization concerns beyond the thread pool
    itself; `IntradayLegResult`/`DayTraderIntradayBars` are both frozen dataclasses, and
    `_fetch_leg` never mutates anything outside its own local scope.

    `conid` is the IBKR contract id already resolved for the ticker being analyzed
    (`IBKRProvider.resolve_conid`) -- resolving it is the caller's responsibility, not this
    function's; a caller with no resolved conid (e.g. `resolve_conid` returned `None`) has
    nothing meaningful to pass here and shouldn't call this function at all for that ticker.
    """
    legs: tuple[tuple[DayTraderLeg, TimeframeInterval], ...] = (
        ("long_term", triple.long_term),
        ("short_term", triple.short_term),
        ("intermediate", triple.intermediate),
    )
    with ThreadPoolExecutor(max_workers=len(legs)) as executor:
        futures = {
            leg: executor.submit(
                _fetch_leg, leg, interval, provider=provider, conid=conid, lookback_days=lookback_days
            )
            for leg, interval in legs
        }
        results = {leg: future.result() for leg, future in futures.items()}
    return DayTraderIntradayBars(
        long_term=results["long_term"],
        short_term=results["short_term"],
        intermediate=results["intermediate"],
    )


def get_active_day_trader_intraday_bars(
    db: Session,
    *,
    provider: IBKRProvider | None,
    conid: int,
    lookback_days: int = 30,
) -> DayTraderIntradayBars | None:
    """`get_intraday_bars_for_triple` above, but reading the active triple itself from the
    global trading-mode setting (`app.trading_mode.get_trading_mode_setting`) rather than
    requiring the caller to already have one in hand -- the literal shape checklist item 2
    describes.

    Returns `None` (not an empty `DayTraderIntradayBars`) when the app isn't currently in
    `TradingMode.DAY_TRADER`, or is but has never had a triple configured (both read directly
    off `TradingModeSetting`, no IBKR call attempted) -- a `None` triple/wrong mode is a
    "this doesn't apply right now" outcome distinct from "day-trader mode is active but IBKR
    itself is unavailable" (which still returns a real `DayTraderIntradayBars`, just with
    every applicable leg's `state` reflecting the unavailability -- see
    `get_intraday_bars_for_triple`).
    """
    setting = get_trading_mode_setting(db)
    if setting.mode is not TradingMode.DAY_TRADER or setting.day_trader_timeframe_triple is None:
        return None
    return get_intraday_bars_for_triple(
        setting.day_trader_timeframe_triple,
        provider=provider,
        conid=conid,
        lookback_days=lookback_days,
    )
