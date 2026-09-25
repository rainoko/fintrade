"""Day-trader-mode signal orchestration shared by `GET /api/stocks/{ticker}/analysis`,
`GET /api/watchlist`, `GET /api/stocks/{ticker}/indicators`, and `GET /api/portfolio`/
`GET /api/portfolio/risk` (docs/tasks/backend-day-trader-timeframe-mode-api.json and its own
follow-up, docs/tasks/backend-day-trader-timeframe-mode-api-followups.json).

Resolves the active `app.trading_mode.TradingModeSetting` into fetched OHLCV frames (via
`app.data.day_trader_intraday` for whichever leg(s) of the configured `TimeframeTriple` are
`MINUTE`-unit) and calls `app.signals.engine.analyse_day_trader`/`analyse_history_day_trader` --
the "actual HTTP route" both functions' own docstrings and docs/architecture/Backend.md §10
explicitly deferred to this module ("resolving *which* frames to fetch for the currently active
triple is left to a caller").

Kept in `app/api/` (not `app/data/` or `app/signals/`) since it depends on both the data layer
(`app.data.day_trader_intraday`, `app.data.ibkr_provider.IBKRProvider`) and the signal engine
(`app.signals.engine.analyse_day_trader`/`analyse_history_day_trader`) -- gluing them together
for an HTTP route is exactly the API-layer orchestration job `app/api/routers/*.py` already does
for the swing-mode fetch-then-`analyse()` pipeline (see e.g.
`app.api.routers.watchlist._compute_signal`), just factored out here since four different
routers (`stocks.py`/`watchlist.py`/`portfolio.py`) need the identical day-trader-mode version
of that same orchestration -- matching this codebase's own "one place, testable once" principle
(`app.api.routers.watchlist`'s module docstring) rather than duplicating it.
`app/data/day_trader_intraday.py`/`app/signals/engine.py` themselves stay pure (no new
dependency on each other), matching Backend.md's existing "thin persistence/API layer over pure
domain modules" convention.

**Scope decision (backend-day-trader-timeframe-mode-api's own `decisions` entry): only a
fully-intraday triple (every leg `MINUTE`-unit) is supported here.**
`app.data.day_trader_intraday._fetch_leg` already only ever fetches a `MINUTE`-unit leg via
IBKR -- a `DAY`/`WEEK`-unit leg (e.g. a mixed triple like `long_term="1d"`) has no established
fetch path anywhere in this codebase yet (the existing yfinance/Stooq `DataProvider` chain only
ever serves the *literal* daily/weekly bar, not an arbitrary N-day/N-week count
`TimeframeInterval` otherwise allows). Building a whole new generic multi-day/week
bar-fetching pipeline is a distinct, unscoped problem this module doesn't attempt to solve; a
triple with any non-`MINUTE` leg degrades to `outcome="unavailable"` here, the same as any other
day-trader-data-unavailable condition, rather than guessing at a fetch strategy nothing in the
codebase actually implements. This still covers day-trader mode's primary documented use case
(ch. 39's own 25-min/5-min/2-min and 39-min/8-min canonical day-trading examples are both fully
intraday on every leg) -- see that task's `decisions` entry for the full rationale and the
follow-up this defers.

**Per-ticker concurrency (`backend-day-trader-timeframe-mode-api-followups`'s own `decisions`
entry):** `fetch_day_trader_legs`/`compute_day_trader_signal` (below) already fetch one
ticker's own three legs *concurrently* (`get_intraday_bars_for_triple`'s
`_fetch_legs_concurrently`) -- but a caller needing this for *N* tickers in one request
(`GET /api/watchlist`, `GET /api/portfolio`, `GET /api/portfolio/risk`) would still pay N
sequential (conid-resolve + 3-leg-fetch) round trips end to end if it just looped and called
one of these functions once per ticker. `compute_day_trader_signals_concurrently`/
`fetch_day_trader_legs_concurrently` fan the whole per-ticker call out across a small thread
pool instead (`IBKRProvider`'s HTTP calls are synchronous, so this is the same "offload
blocking I/O to a thread" pattern `_fetch_legs_concurrently` already uses one level down, for
legs instead of tickers) -- see this task's `decisions` entry for the worker-count choice and
the followups this resolves (a PR #313 review finding on `GET /api/watchlist`'s own previously
fully-sequential per-ticker loop, and this task's own portfolio-endpoint latency design
question).
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pandas as pd

from app.api.schemas import TimeframeTripleOut, TradingModeOut
from app.data.day_trader_intraday import (
    DayTraderIntradayBars,
    DayTraderLeg,
    IntradayLegResult,
    get_intraday_bars_for_triple,
    get_intraday_history_bars_for_triple,
)
from app.data.ibkr_provider import IBKRProvider, IBKRUnavailableError
from app.signals.engine import SignalResult, analyse_day_trader
from app.signals.timeframe import TimeframeTriple, TimeframeUnit
from app.trading_mode import TradingModeSetting

# How many tickers' own day-trader-mode fetches `compute_day_trader_signals_concurrently`/
# `fetch_day_trader_legs_concurrently` run in parallel at once, for a caller with more tracked
# tickers than this (a large watchlist/portfolio). Not "one thread per ticker, unbounded":
# beyond a point, more concurrent threads just contend for the same IBKR gateway's own request
# handling capacity (a single local `clientportal.gw` process, not a horizontally-scaled
# service) without shortening wall-clock latency further, while still growing this process's
# own thread count for every request. 8 was chosen as a reasonable, round default for a
# still-hypothetical "large tracked-ticker list" scenario (matching `IBKRProvider.resolve_conid`
# in `app.data.day_trader_intraday`'s own precedent of picking small, un-configurable constants
# for concurrency knobs rather than exposing a tuning parameter this app has no evidence anyone
# would ever need to change) -- not measured against a real slow/high-latency gateway, since no
# sandboxed environment has one to measure against (matching `app.data.ibkr_provider`'s own
# documented testing constraint). See this task's `decisions` entry.
_MAX_CONCURRENT_TICKER_FETCHES = 8

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


@dataclass(frozen=True)
class DayTraderLegsOutcome:
    """The result of attempting to fetch every leg of the active day-trader triple for one
    ticker -- `compute_day_trader_signal`'s own fetch step, factored out so a caller that needs
    the raw OHLCV itself (not just the resulting `SignalResult`) can reuse it:
    `app.api.routers.stocks.get_indicator_history`'s day-trader-mode branch (feeding
    `app.signals.engine.analyse_history_day_trader`) and `app.api.routers.portfolio.get_risk`
    (feeding `app.portfolio.risk.protective_stop`/`app.portfolio.profit_target
    .suggest_profit_target`/`app.portfolio.exits.evaluate_exit_flags` -- see
    docs/tasks/backend-day-trader-timeframe-mode-portfolio-risk.json's own `decisions` entry for
    why those three functions already generalize to whichever OHLCV plays the intermediate/
    long-term role, once a caller hands them day-trader-mode data instead of daily/weekly).

    `long_term_ohlcv`/`intermediate_ohlcv`/`short_term_ohlcv` are populated **iff**
    `unavailable_reason is None` (mirrors `DayTraderSignalOutcome`'s own
    `signal_result`-iff-no-`unavailable_reason` contract, and
    `app.data.day_trader_intraday.IntradayLegResult`'s "`ohlcv` populated iff
    `state == 'available'`" contract one layer down) -- never a raised exception.
    """

    long_term_ohlcv: pd.DataFrame | None
    intermediate_ohlcv: pd.DataFrame | None
    short_term_ohlcv: pd.DataFrame | None
    unavailable_reason: str | None


def _resolve_and_fetch_legs(
    ticker: str,
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
    fetch_bars: Callable[[TimeframeTriple, IBKRProvider, int], DayTraderIntradayBars],
) -> DayTraderLegsOutcome:
    """Shared conid-resolve-then-fetch-then-validate core of `fetch_day_trader_legs`/
    `fetch_day_trader_history_legs` -- the two differ only in which
    `app.data.day_trader_intraday` fetch function (and its own default `lookback_days`) they
    pass as `fetch_bars`. Never raises: an `IBKRUnavailableError` from `resolve_conid` (the
    gateway itself going unavailable between `get_trading_mode_setting` and this call, or the
    resolve call failing transiently) is caught and reported the same way as any other
    unavailable leg -- matching `app.data.day_trader_intraday`'s own never-raises contract,
    which this function extends one step further back (conid resolution) using the same
    convention. `provider=None` (IBKR disabled) degrades straight to `unavailable_reason`
    without attempting a conid resolution or leg fetch at all -- day-trader mode being
    *configured* never itself requires IBKR to be reachable, same as
    `app.data.day_trader_intraday`'s own documented contract.
    """
    if not _is_fully_intraday(triple):
        return DayTraderLegsOutcome(None, None, None, _NOT_FULLY_INTRADAY_DETAIL)

    if provider is None:
        return DayTraderLegsOutcome(None, None, None, _DISABLED_DETAIL)

    try:
        conid = provider.resolve_conid(ticker)
    except IBKRUnavailableError as exc:
        return DayTraderLegsOutcome(None, None, None, str(exc))

    if conid is None:
        return DayTraderLegsOutcome(
            None, None, None, f"Could not resolve an IBKR contract id for '{ticker}'."
        )

    fetched = fetch_bars(triple, provider, conid)
    legs: dict[DayTraderLeg, IntradayLegResult | None] = {
        "long_term": fetched.long_term,
        "intermediate": fetched.intermediate,
        "short_term": fetched.short_term,
    }
    for leg_name in _LEG_ORDER:
        leg = legs[leg_name]
        if leg is None or leg.state != "available" or leg.ohlcv is None:
            return DayTraderLegsOutcome(None, None, None, _unavailable_detail(leg_name, leg))

    # mypy can't see through the loop above that every leg's `.ohlcv` is now non-`None` --
    # asserted explicitly rather than left implicit, matching this codebase's convention
    # elsewhere for narrowing an Optional after a runtime check a type checker can't follow.
    assert legs["long_term"] is not None and legs["long_term"].ohlcv is not None
    assert legs["intermediate"] is not None and legs["intermediate"].ohlcv is not None
    assert legs["short_term"] is not None and legs["short_term"].ohlcv is not None

    return DayTraderLegsOutcome(
        legs["long_term"].ohlcv,
        legs["intermediate"].ohlcv,
        legs["short_term"].ohlcv,
        None,
    )


def fetch_day_trader_legs(
    ticker: str,
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
) -> DayTraderLegsOutcome:
    """The **live-signal-snapshot** leg fetch (`app.data.day_trader_intraday
    .get_intraday_bars_for_triple`'s own default `lookback_days`) -- `compute_day_trader_signal`
    below is a thin wrapper over this plus `app.signals.engine.analyse_day_trader`. See
    `DayTraderLegsOutcome`'s own docstring for why this is exposed separately (a caller that
    needs the raw OHLCV, not just a `SignalResult`)."""
    return _resolve_and_fetch_legs(
        ticker,
        triple,
        provider=provider,
        fetch_bars=lambda t, p, conid: get_intraday_bars_for_triple(t, provider=p, conid=conid),
    )


def fetch_day_trader_history_legs(
    ticker: str,
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
    lookback_days: int | None = None,
) -> DayTraderLegsOutcome:
    """The **walk-forward-history** leg fetch (`app.data.day_trader_intraday
    .get_intraday_history_bars_for_triple`) -- `GET /api/stocks/{ticker}/indicators`'s
    day-trader-mode branch's own fetch step, feeding `app.signals.engine
    .analyse_history_day_trader`'s per-bar replay. `lookback_days=None` (the default) uses
    `get_intraday_history_bars_for_triple`'s own default (mirroring swing mode's `analyse_history`
    convention of always fetching a large, fixed amount of available history and letting the
    caller's own `range` trim only what's *returned*, not what's fetched -- see this task's
    `decisions` entry for why `GET /api/stocks/{ticker}/indicators`'s own `range` query param
    doesn't translate into a smaller explicit `lookback_days` request here)."""

    def fetch_bars(t: TimeframeTriple, p: IBKRProvider, conid: int) -> DayTraderIntradayBars:
        if lookback_days is None:
            return get_intraday_history_bars_for_triple(t, provider=p, conid=conid)
        return get_intraday_history_bars_for_triple(
            t, provider=p, conid=conid, lookback_days=lookback_days
        )

    return _resolve_and_fetch_legs(ticker, triple, provider=provider, fetch_bars=fetch_bars)


def compute_day_trader_signal(
    ticker: str,
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
) -> DayTraderSignalOutcome:
    """Fetches every leg of `triple` (`fetch_day_trader_legs` above) and, if all three are
    available, runs `app.signals.engine.analyse_day_trader` over them for `ticker`. Never
    raises -- see `fetch_day_trader_legs`'s own docstring for the full degrade-gracefully
    contract this inherits unchanged."""
    legs = fetch_day_trader_legs(ticker, triple, provider=provider)
    if legs.unavailable_reason is not None:
        return DayTraderSignalOutcome(None, legs.unavailable_reason)

    # `fetch_day_trader_legs`'s own `unavailable_reason is None` contract guarantees all three
    # OHLCV frames are populated here -- narrowed explicitly for mypy, matching this module's
    # existing convention elsewhere (see `_resolve_and_fetch_legs`'s own asserts).
    assert legs.long_term_ohlcv is not None
    assert legs.intermediate_ohlcv is not None
    assert legs.short_term_ohlcv is not None

    result = analyse_day_trader(
        ticker,
        long_term_ohlcv=legs.long_term_ohlcv,
        intermediate_ohlcv=legs.intermediate_ohlcv,
        short_term_ohlcv=legs.short_term_ohlcv,
    )
    return DayTraderSignalOutcome(result, None)


def _fan_out_per_ticker[T](
    tickers: Sequence[str],
    fn: Callable[[str], T],
    *,
    max_workers: int = _MAX_CONCURRENT_TICKER_FETCHES,
) -> dict[str, T]:
    """Runs `fn(ticker)` for every distinct ticker in `tickers` concurrently (a small thread
    pool -- see `_MAX_CONCURRENT_TICKER_FETCHES`'s own comment), returning a plain
    `{ticker: result}` dict rather than a list preserving `tickers`' own order -- callers
    (`get_watchlist`/`get_watchlist_breadth`/`get_portfolio`/`get_risk`) look a result up by
    ticker, not by position. De-duplicates `tickers` first (via `dict.fromkeys`, which preserves
    first-seen order) so a ticker appearing more than once (e.g. `GET /api/watchlist/breadth`'s
    watchlist-union-portfolio ticker set, or a ticker somehow tracked twice) is only ever fetched
    once."""
    unique = list(dict.fromkeys(tickers))
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(unique), max_workers)) as executor:
        futures = {ticker: executor.submit(fn, ticker) for ticker in unique}
        return {ticker: future.result() for ticker, future in futures.items()}


def compute_day_trader_signals_concurrently(
    tickers: Sequence[str],
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
) -> dict[str, DayTraderSignalOutcome]:
    """`compute_day_trader_signal` for every distinct ticker in `tickers`, fanned out across a
    small thread pool instead of a sequential per-ticker loop -- see this module's own docstring
    ("Per-ticker concurrency") for why. Used by `GET /api/watchlist`/`GET /api/watchlist/breadth`
    (`app.api.routers.watchlist`) and `GET /api/portfolio` (`app.api.routers.portfolio`)."""
    return _fan_out_per_ticker(
        tickers, lambda ticker: compute_day_trader_signal(ticker, triple, provider=provider)
    )


def fetch_day_trader_legs_concurrently(
    tickers: Sequence[str],
    triple: TimeframeTriple,
    *,
    provider: IBKRProvider | None,
) -> dict[str, DayTraderLegsOutcome]:
    """`fetch_day_trader_legs` for every distinct ticker in `tickers`, fanned out the same way
    `compute_day_trader_signals_concurrently` does. Used by `GET /api/portfolio/risk`
    (`app.api.routers.portfolio.get_risk`), which needs the raw `long_term_ohlcv`/
    `intermediate_ohlcv` OHLCV itself (for `protective_stop`/`suggest_profit_target`/
    `evaluate_exit_flags`), not a `SignalResult` -- see `DayTraderLegsOutcome`'s own docstring.
    `short_term_ohlcv` is fetched (and included in the result) even though none of those three
    risk/profit-target/exit functions read it -- reusing the exact same fully-intraday-triple
    3-leg fetch `compute_day_trader_signal` uses, rather than inventing a second, leaner 2-leg
    fetch pipeline solely for this caller, was judged the better trade-off: one degrade-
    gracefully/concurrency code path to test and maintain, at the cost of one IBKR round trip
    this specific caller doesn't strictly need (still fetched *concurrently* alongside the two
    it does need, not as a further-added sequential cost) -- see this task's `decisions` entry.
    """
    return _fan_out_per_ticker(
        tickers, lambda ticker: fetch_day_trader_legs(ticker, triple, provider=provider)
    )
