"""Day-trader-mode signal orchestration shared by `GET /api/stocks/{ticker}/analysis` and
`GET /api/watchlist` (docs/tasks/backend-day-trader-timeframe-mode-api.json -- the fourth and
last of four dependent follow-up tasks splitting docs/tasks/done/
backend-day-trader-timeframe-mode.json's original checklist item 6 out of that task).

Resolves the active `app.trading_mode.TradingModeSetting` into fetched OHLCV frames (via
`app.data.day_trader_intraday` for whichever leg(s) of the configured `TimeframeTriple` are
`MINUTE`-unit) and calls `app.signals.engine.analyse_day_trader` -- the "actual HTTP route"
`app.signals.engine.analyse_day_trader`'s own docstring and docs/architecture/Backend.md §10
both explicitly deferred to this task ("resolving *which* frames to fetch for the currently
active triple is left to a caller").

Kept in `app/api/` (not `app/data/` or `app/signals/`) since it depends on both the data layer
(`app.data.day_trader_intraday`, `app.data.ibkr_provider.IBKRProvider`) and the signal engine
(`app.signals.engine.analyse_day_trader`) -- gluing them together for an HTTP route is exactly
the API-layer orchestration job `app/api/routers/*.py` already does for the swing-mode
fetch-then-`analyse()` pipeline (see e.g. `app.api.routers.watchlist._compute_signal`), just
factored out here since two different routers (`stocks.py`/`watchlist.py`) need the identical
day-trader-mode version of that same orchestration -- matching this codebase's own "one place,
testable once" principle (`app.api.routers.watchlist`'s module docstring) rather than
duplicating it. `app/data/day_trader_intraday.py`/`app/signals/engine.py` themselves stay pure
(no new dependency on each other), matching Backend.md's existing "thin persistence/API layer
over pure domain modules" convention.

**Scope decision (this task's own `decisions` entry): only a fully-intraday triple (every leg
`MINUTE`-unit) is supported here.** `app.data.day_trader_intraday._fetch_leg` already only ever
fetches a `MINUTE`-unit leg via IBKR -- a `DAY`/`WEEK`-unit leg (e.g. a mixed triple like
`long_term="1d"`) has no established fetch path anywhere in this codebase yet (the existing
yfinance/Stooq `DataProvider` chain only ever serves the *literal* daily/weekly bar, not an
arbitrary N-day/N-week count `TimeframeInterval` otherwise allows). Building a whole new
generic multi-day/week bar-fetching pipeline is a distinct, unscoped problem this task doesn't
attempt to solve; a triple with any non-`MINUTE` leg degrades to `outcome="unavailable"` here,
the same as any other day-trader-data-unavailable condition, rather than guessing at a fetch
strategy nothing in the codebase actually implements. This still covers day-trader mode's
primary documented use case (ch. 39's own 25-min/5-min/2-min and 39-min/8-min canonical
day-trading examples are both fully intraday on every leg) -- see this task's `decisions` entry
for the full rationale and the follow-up this defers.
"""

from dataclasses import dataclass

from app.api.schemas import TimeframeTripleOut, TradingModeOut
from app.data.day_trader_intraday import (
    DayTraderLeg,
    IntradayLegResult,
    get_intraday_bars_for_triple,
)
from app.data.ibkr_provider import IBKRProvider, IBKRUnavailableError
from app.signals.engine import SignalResult, analyse_day_trader
from app.signals.timeframe import TimeframeTriple, TimeframeUnit
from app.trading_mode import TradingModeSetting

_DISABLED_DETAIL = "IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set)."

_NOT_FULLY_INTRADAY_DETAIL = (
    "The active day-trader timeframe triple has a long_term/intermediate/short_term leg that "
    "isn't a MINUTE-unit interval; fetching day-trader-mode data for a non-intraday leg isn't "
    "supported yet (see backend-day-trader-timeframe-mode-api's `decisions` entry)."
)

_LEG_ORDER: tuple[DayTraderLeg, ...] = ("long_term", "intermediate", "short_term")


@dataclass(frozen=True)
class DayTraderSignalOutcome:
    """The result of attempting to compute a day-trader-mode signal for one ticker.

    `signal_result` is populated **iff** every leg of the active triple was fetched
    successfully (mirrors `app.data.day_trader_intraday.IntradayLegResult`'s own "`ohlcv`
    populated iff `state == 'available'`" contract) -- every other case carries
    `signal_result=None` and a human-readable `unavailable_reason` instead, never a raised
    exception, matching every other IBKR-dependent feature's degrade-gracefully contract in
    this app (`app.api.routers.ibkr`, `app.data.day_trader_intraday`).
    """

    signal_result: SignalResult | None
    unavailable_reason: str | None


def trading_mode_setting_to_schema(setting: TradingModeSetting) -> TradingModeOut:
    """Maps `app.trading_mode.TradingModeSetting` (the domain type) onto `TradingModeOut`
    (the API schema) -- the same boundary-mapping pattern `app.api.routers.stocks`'s
    `_zone_to_schema`/etc use, factored out here (rather than kept as `app.api.routers.settings
    ._to_out`, its original home) since `GET /api/stocks/{ticker}/analysis` and
    `GET /api/watchlist` both now also need to echo the active trading mode on their own
    responses (this task's checklist item 1 decision) -- `app.api.routers.settings` imports
    this function instead of keeping its own duplicate copy."""
    triple_out = None
    if setting.day_trader_timeframe_triple is not None:
        triple = setting.day_trader_timeframe_triple
        triple_out = TimeframeTripleOut(
            long_term=triple.long_term.code,
            intermediate=triple.intermediate.code,
            short_term=triple.short_term.code,
            factor_of_five_warnings=triple.factor_of_five_warnings(),
        )
    return TradingModeOut(mode=setting.mode.value, day_trader_timeframe_triple=triple_out)


def _is_fully_intraday(triple: TimeframeTriple) -> bool:
    return (
        triple.long_term.unit is TimeframeUnit.MINUTE
        and triple.intermediate.unit is TimeframeUnit.MINUTE
        and triple.short_term.unit is TimeframeUnit.MINUTE
    )


def _unavailable_detail(leg_name: DayTraderLeg, leg: IntradayLegResult | None) -> str:
    if leg is not None and leg.detail is not None:
        return f"{leg_name} leg: {leg.detail}"
    return f"{leg_name} leg unavailable."


def compute_day_trader_signal(
    ticker: str,
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
) -> DayTraderSignalOutcome:
    """Fetches every leg of `triple` and, if all three are available, runs
    `app.signals.engine.analyse_day_trader` over them for `ticker`.

    Never raises: an `IBKRUnavailableError` from `resolve_conid` (the gateway itself going
    unavailable between `get_trading_mode_setting` and this call, or the resolve call failing
    transiently) is caught and reported the same way as any other unavailable leg -- matching
    `app.data.day_trader_intraday`'s own never-raises contract, which this function extends
    one step further back (conid resolution) using the same convention.

    `provider=None` (IBKR disabled, `Depends(get_ibkr_provider)`'s own contract when
    `Settings.ibkr_enabled` is `False`) degrades straight to `unavailable_reason` without
    attempting a conid resolution or leg fetch -- day-trader mode being *configured* never
    itself requires IBKR to be reachable, same as `app.data.day_trader_intraday`'s own
    documented contract.
    """
    if not _is_fully_intraday(triple):
        return DayTraderSignalOutcome(None, _NOT_FULLY_INTRADAY_DETAIL)

    if provider is None:
        return DayTraderSignalOutcome(None, _DISABLED_DETAIL)

    try:
        conid = provider.resolve_conid(ticker)
    except IBKRUnavailableError as exc:
        return DayTraderSignalOutcome(None, str(exc))

    if conid is None:
        return DayTraderSignalOutcome(
            None, f"Could not resolve an IBKR contract id for '{ticker}'."
        )

    fetched = get_intraday_bars_for_triple(triple, provider=provider, conid=conid)
    legs: dict[DayTraderLeg, IntradayLegResult | None] = {
        "long_term": fetched.long_term,
        "intermediate": fetched.intermediate,
        "short_term": fetched.short_term,
    }
    for leg_name in _LEG_ORDER:
        leg = legs[leg_name]
        if leg is None or leg.state != "available" or leg.ohlcv is None:
            return DayTraderSignalOutcome(None, _unavailable_detail(leg_name, leg))

    # mypy can't see through the loop above that every leg's `.ohlcv` is now non-`None` --
    # asserted explicitly rather than left implicit, matching this codebase's convention
    # elsewhere for narrowing an Optional after a runtime check a type checker can't follow.
    assert legs["long_term"] is not None and legs["long_term"].ohlcv is not None
    assert legs["intermediate"] is not None and legs["intermediate"].ohlcv is not None
    assert legs["short_term"] is not None and legs["short_term"].ohlcv is not None

    result = analyse_day_trader(
        ticker,
        long_term_ohlcv=legs["long_term"].ohlcv,
        intermediate_ohlcv=legs["intermediate"].ohlcv,
        short_term_ohlcv=legs["short_term"].ohlcv,
    )
    return DayTraderSignalOutcome(result, None)
