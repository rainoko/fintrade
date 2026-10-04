"""Optional IBKR Client Portal Web API provider (docs/tasks/backend-ibkr-data-provider.json,
docs/ideas.md's "Decided: add IBKR's Client Portal Web API" entry).

``IBKRProvider`` itself is still conid-keyed (not ticker-keyed) and still does **not**
implement the ``DataProvider`` protocol (app/data/base.py) directly -- its methods
(hourly/daily/weekly bars for one IBKR contract ID, a market-breadth scanner) take a
``conid``, not a ``ticker``, so they don't satisfy that protocol's
``get_daily_ohlcv(ticker)``/``get_weekly_ohlcv(ticker)`` signatures as-is.
``app.data.ibkr_data_provider.IBKRDataProvider`` is the ticker-keyed adapter
(``resolve_conid`` + this class's ``get_daily_bars``/``get_weekly_bars``) that actually
satisfies the protocol.

**This module's own "poor fit as a primary data source" design decision has been
reversed** by `backend-ibkr-primary-data-provider` (see that task's `decisions` entry for
the full rationale and live-gateway research this reversal is based on): when the
gateway is connected/authenticated, `app.api.dependencies.get_data_provider` now sources
daily/weekly OHLCV from IBKR exclusively (via `IBKRDataProvider`) rather than
yfinance/Stooq, falling back to the original yfinance-primary/Stooq-fallback behavior
only when IBKR isn't connected. The structural reason the original decision gave --
the gateway's interactive-login/session-keepalive requirements make it unlike
`YFinanceProvider`'s always-on nature -- still holds and still motivates the *fallback*
behavior (an app with no locally-running, authenticated gateway must keep working
exactly as before), it just no longer rules IBKR out as primary *when* that gateway
happens to be up: a human already keeping their own IBKR Gateway logged in is a
reasonable thing for this self-hosted app to take advantage of, and doing so was the
literal, explicit user request this task implements.

**Structural constraint this whole module is designed around** (this task's own
`description`): the gateway is a persistent local process (`clientportal.gw`) that
requires a one-time interactive browser login IBKR explicitly does not support
automating, and the session must be kept alive with a periodic ``/tickle`` call -- this
is why the app only ever *uses* IBKR opportunistically (gated behind a live
`get_gateway_status()` check, see below) rather than *requiring* it, and degrades
gracefully (a typed `GatewayStatus`, never an opaque exception) whenever the gateway
isn't running or isn't authenticated. See `docs/architecture/Backend.md`'s IBKR section
for the human setup walkthrough (downloading/running the gateway, the browser login
step, `FINTRADE_IBKR_ENABLED`).

**Testing constraint** (also this task's own `description`): no sandboxed/CI environment
has a live authenticated gateway to test against, so every test in
tests/unit/data/test_ibkr_provider.py mocks HTTP at the ``_request`` boundary against the
documented Web API request/response shapes -- this task's `decisions` entry records that
live-gateway behavior (the actual response shapes, the interactive login flow, and any
undocumented quirks) is unverified here and deferred to manual testing by the user
against a real running gateway.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.models import IBKRConidCacheORM
from app.time_utils import utcnow

logger = logging.getLogger(__name__)

# IBKR's own default: the gateway listens locally, over HTTPS with a self-signed cert
# (hence `verify=False` on the client below -- there's no real TLS trust chain to check
# against a `localhost` gateway process, and IBKR's own docs have users click through the
# browser warning for the same reason).
DEFAULT_BASE_URL = "https://localhost:5000/v1/api"

# docs/ideas.md: "max 1,000 data points per call" on /iserver/marketdata/history.
_MAX_BARS_PER_PAGE = 1000

# `get_daily_bars`/`get_weekly_bars`'s own single-request `period` values --
# `backend-ibkr-primary-data-provider`'s checklist item 1 live-gateway research (this
# task's `decisions` entry) confirmed `/iserver/marketdata/history` hard-caps a
# `bar="1d"` response at `_MAX_BARS_PER_PAGE` regardless of how much history a larger
# `period` requests (every value from `"4y"` up through `"max"` returned the identical
# ~999-bar response against a live gateway), so any `period` at or past that ceiling
# already returns IBKR's full available daily history in one request -- `"10y"` is
# comfortably past it with headroom to spare. `bar="1w"` has a materially deeper ceiling
# (confirmed live: `"20y"` returned 1,000 weekly bars, ~19 calendar years) -- both are
# single-request values, not paginated further; see `get_daily_bars`'s own docstring for
# why this doesn't reuse `get_hourly_bars`'s pagination loop.
_DAILY_BARS_PERIOD = "10y"
_WEEKLY_BARS_PERIOD = "20y"

# `get_hourly_bars`'s default bar size -- kept for backward compatibility with every
# existing caller (none of which pass `bar_size` explicitly yet, per this task's own
# `decisions` entry).
_BAR_INTERVAL = "1h"

# IBKR's own documented set of accepted `bar` values for `/iserver/marketdata/history`
# (Web API reference for that endpoint: `bar` is one of a fixed enumerated list, not an
# arbitrary duration string -- there is no way to request e.g. a 39-minute bar the way
# docs/ideas.md's "Switchable trading mode" note speculated about, since IBKR's `bar`
# values aren't freely composable). This task's own `decisions` entry records which of
# these are confirmed against IBKR's published docs vs. genuinely untested against a
# live gateway, per this module's mocked-only testing constraint.
_VALID_BAR_INTERVALS: frozenset[str] = frozenset(
    {
        "1min",
        "2min",
        "3min",
        "5min",
        "10min",
        "15min",
        "30min",
        "1h",
        "2h",
        "3h",
        "4h",
        "8h",
        "1d",
        "1w",
        "1m",
    }
)

# The step to walk the pagination cursor back by, per bar size -- must equal one bar's
# worth of time so the next page's `startTime` sits just before (not re-fetching) the
# earliest bar already collected, without also skipping bars in between for anything
# finer than the `1h` this pagination logic was originally written against. `"1m"`
# (IBKR's monthly bar) has no fixed `timedelta` length (a calendar month is 28-31 days),
# so it uses a 27-day *underestimate* rather than a 30-day approximation -- the cursor
# step only needs to be `<=` the true bar-to-bar gap: an underestimate just means the
# next page's `startTime` sits a few days earlier than the previous page's earliest bar,
# causing a handful of redundant re-fetched bars that `get_hourly_bars`'s `collected`
# dict already deduplicates by timestamp, whereas an overestimate like the shortest
# possible month (28 days) minus a day of margin could sit *after* the actual preceding
# bar's timestamp and skip it -- the same pagination bug this constant exists to prevent
# for every other bar size (docs/tasks/backend-ibkr-bar-interval-param-followups.json).
# No caller of this provider requests monthly bars today (`_MAX_BARS_PER_PAGE` means a
# second page only triggers after ~83 years of requested lookback), so this is
# unreachable in practice, but a safe-by-construction constant costs nothing.
_BAR_INTERVAL_STEP: dict[str, timedelta] = {
    "1min": timedelta(minutes=1),
    "2min": timedelta(minutes=2),
    "3min": timedelta(minutes=3),
    "5min": timedelta(minutes=5),
    "10min": timedelta(minutes=10),
    "15min": timedelta(minutes=15),
    "30min": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "3h": timedelta(hours=3),
    "4h": timedelta(hours=4),
    "8h": timedelta(hours=8),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=27),
}

# Safety bound on how many pages `get_hourly_bars` will walk backward, independent of
# `lookback_days` -- caps worst-case request volume (and, if the pagination cursor logic
# ever had a bug that stalled forward progress, guarantees termination) rather than
# looping until a caller-supplied `lookback_days` is satisfied no matter how large. 20
# pages * 1,000 hourly bars/page is ~833 days of history, comfortably past any
# `lookback_days` this app's Screen 3 entry-timing use case needs (docs/ideas.md's own
# framing: "recent-bar entry timing, not deep history").
_MAX_PAGINATION_PAGES = 20


def max_lookback_days_for_bar_size(bar_size: str) -> float:
    """The most calendar days of history `get_hourly_bars(bar_size=bar_size)` can *ever* return,
    given `_MAX_PAGINATION_PAGES`'s own safety bound on page count -- `_MAX_PAGINATION_PAGES *
    _MAX_BARS_PER_PAGE` bars total, each `_BAR_INTERVAL_STEP[bar_size]` apart.
    `get_hourly_bars` already silently self-limits to this regardless of whatever
    `lookback_days` it's asked for (its own pagination loop simply stops issuing further
    requests once the page cap is hit) -- this function exists so a caller that wants to
    request a specific amount of look-back history at a specific granularity (day-trader
    mode's walk-forward historical-replay fetch, `app.data.day_trader_intraday
    .get_intraday_history_bars_for_triple`, `backend-day-trader-timeframe-mode-history`) can
    know in advance how much of that request is actually achievable, rather than silently
    getting back fewer bars than asked for with no way to tell why. A finer `bar_size` (e.g.
    `"1min"`) covers proportionally *less* real calendar time before hitting the same 20-page
    cap than a coarser one (e.g. `"1h"`) -- see `_MAX_PAGINATION_PAGES`'s own comment for the
    `"1h"`-anchored ~833-day figure this generalizes.

    Revisiting `_MAX_PAGINATION_PAGES`/`_MAX_BARS_PER_PAGE` themselves (raising the achievable
    window for a feature that genuinely needs deeper finer-grained history) is explicitly out
    of scope for whatever caller uses this function -- see `get_hourly_bars`'s own docstring,
    which already flagged this as a distinct, unscoped problem before this function existed.

    Raises:
        ValueError: `bar_size` isn't one of `_VALID_BAR_INTERVALS`.
    """
    if bar_size not in _VALID_BAR_INTERVALS:
        raise ValueError(
            f"Unsupported IBKR bar interval {bar_size!r}; must be one of {sorted(_VALID_BAR_INTERVALS)}"
        )
    total_span = _MAX_PAGINATION_PAGES * _MAX_BARS_PER_PAGE * _BAR_INTERVAL_STEP[bar_size]
    return total_span / timedelta(days=1)


# Safety bound on how many pages `get_account_positions` will walk forward through
# `GET /portfolio/{accountId}/positions/{pageId}` -- unlike `_MAX_PAGINATION_PAGES` above
# (sized against a *known* per-page bar count), this provider has no live gateway to
# confirm IBKR's actual per-page position count against (this task's own `decisions`
# entry), so the pagination loop below deliberately does NOT hardcode a page size at all:
# it simply keeps requesting the next `pageId` until a page comes back empty, exactly as
# IBKR's own documented convention for this endpoint describes. This constant only
# guarantees termination (and bounds worst-case request volume) if that "empty page ends
# it" signal is ever wrong against a real gateway -- 50 pages is generous headroom for any
# real personal brokerage account (community-reported page sizes for this endpoint are in
# the tens of positions per page, so 50 pages covers well over a thousand held positions).
_MAX_ACCOUNT_POSITIONS_PAGES = 50

# `_resolve_stk_conid`'s disambiguation preference when a bare symbol search returns more
# than one distinct STK conid. Confirmed live during `backend-ibkr-primary-data-provider`'s
# PR #369 review follow-up research (this task's `decisions` entry carries the full
# request/response detail): a bare `/iserver/secdef/search` for AAPL returns FOUR distinct
# STK conids -- the NASDAQ primary listing plus IBKR's own international feeder-exchange
# programs for popular US names (a TSE-CDR cross-listing, a MEXI/Mexico-exchange listing,
# an EBS listing) -- and the same shape (one US-primary listing plus 2-4 feeder-exchange
# listings) was confirmed for MSFT/GOOGL/TSLA/NVDA/AMZN/IBM/KO/F/GE/SPY/QQQ/CROX/CELH/RUN/
# PLTR/SNOW/ZS/COIN, i.e. this is the norm for heavily-tracked US tickers, not a rare edge
# case -- so the prior "more than one candidate degrades to None" rule made IBKR-primary
# mode 404 on the app's single most common example ticker (and most other popular US
# mega-caps) the instant a gateway connects. Each search-result candidate carries a
# top-level `description` field naming the exchange that specific listing trades on
# (confirmed live, NOT nested under `sections` -- a `sections` entry's own `exchange` key,
# where present at all, names where that section's *derivatives* trade, not the underlying
# listing itself) -- `"NASDAQ"`/`"NYSE"`/`"ARCA"` for the primary US listing of every ticker
# above, versus `"TSE"`/`"MEXI"`/`"EBS"`/`"GETTEX"`/`"FWB"`/`"VALUE"`/`"BVME"`/`"ASX"`/
# `"PURE"`/`"AQSE"`/`"LSEETF"`/`"IBIS"`/`"CDE"` for every feeder-exchange listing observed.
# `"AMEX"`/`"BATS"` are included even though not confirmed live (no candidate ticker
# tried happened to list there) since they're IBKR's other two well-documented primary
# US equity exchanges alongside the two confirmed ones.
_US_PRIMARY_EXCHANGES: frozenset[str] = frozenset({"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"})

# docs/ideas.md: "`params` is rate-limited to 1 request per 15 minutes (cache it)".
_SCANNER_PARAMS_TTL_SECONDS = 15 * 60.0

# docs/ideas.md: "`run` to 1 request per second".
_SCANNER_RUN_MIN_INTERVAL_SECONDS = 1.0

# `_request`'s single-quick-retry policy (`backend-ibkr-request-retry`) -- confirmed via
# this session's own direct observation while working `backend-ibkr-primary-data-provider`:
# the configured gateway flipped between unreachable, HTTP 400, HTTP 401, and
# 200-authenticated states multiple times within a ~20-minute window, genuine empirical
# transient flakiness rather than a hypothetical concern. `_REQUEST_MAX_ATTEMPTS = 2` (the
# original attempt plus exactly one retry, not an open-ended backoff loop) is deliberately
# minimal: every flip this session actually observed was a fast failure (an immediate
# connection refusal or an immediate non-200 response), not a slow one, so a single quick
# retry is already enough to plausibly absorb one of those -- a second or third retry would
# only add latency for a case with no evidence it would ever succeed where the first retry
# didn't. `_REQUEST_RETRY_DELAY_SECONDS = 0.3` (300ms) sits in the middle of this task's own
# description's suggested 200-500ms range: long enough to give a flapping gateway process a
# moment to settle, short enough that doubling it (one retry) stays well under what a caller
# fanning out several concurrent IBKR calls (`app.api.routers.stocks.get_analysis`'s daily/
# weekly/extended `ThreadPoolExecutor`, `app.data.day_trader_intraday`'s per-leg fan-out)
# would notice against its own timeout expectations. See `_request`'s own docstring and
# this task's `decisions` entry for which failure types this retries vs. doesn't.
_REQUEST_MAX_ATTEMPTS = 2
_REQUEST_RETRY_DELAY_SECONDS = 0.3

# `backend-ibkr-primary-data-provider`'s checklist item 3: once IBKR can be this app's
# *primary* data source, `app.api.dependencies.get_data_provider` needs to check "is IBKR
# connected" on every single incoming request (unlike `get_ibkr_provider`'s existing
# callers, which only ever call this a handful of times per request at most) -- caching
# `get_gateway_status()` itself (rather than only `get_scanner_params`, the one existing
# cached call) means that per-request check, and every data-fetching method's own
# internal `_require_available()` guard, share one cached result instead of each costing
# a separate live `GET /iserver/auth/status` round trip. 5 seconds (vs. `_SCANNER_PARAMS_
# TTL_SECONDS`'s 15 minutes, which exists to respect an IBKR-documented per-endpoint rate
# limit rather than for latency) is deliberately short: unlike the scanner params list,
# there's no documented rate limit on `/iserver/auth/status` to respect, so this is a pure
# latency/freshness trade-off, and the session's own live-gateway research for this task
# observed the gateway's authenticated state change within *minutes* (not seconds) across
# a resumed session -- a few seconds of staleness is a cost the whole point of this cache
# is willing to pay (collapsing a request's own fan-out of several per-ticker data calls,
# or a tight sequence of HTTP requests, into effectively one real status check) without
# meaningfully risking a stale "available" surviving past the next request. This also
# means `GET /api/ibkr/status` (app.api.routers.ibkr) can now serve a response up to this
# many seconds stale -- accepted as a minor, documented trade-off rather than threading a
# "bypass the cache" parameter through just for that one read-only status endpoint. See
# this task's `decisions` entry.
_GATEWAY_STATUS_TTL_SECONDS = 5.0

# Same task's checklist item 2: an IBKR conid (`resolve_conid`) only changes on a genuine
# listing event (a new IPO's conid, a re-listing after a symbol change) -- never
# intraday -- so caching a resolution for a full day costs essentially no staleness risk
# while saving a `/iserver/secdef/search` round trip (plus the ambiguity-scan work
# `_resolve_stk_conid` does over its response) on every single call for a ticker this
# process has already resolved. 24h matches `app.data.cache._CACHE_TTL`'s own OHLCV
# freshness window -- there's no reason for this cache to be fresher than the OHLCV data
# it's resolved in service of. A `None` (unknown/ambiguous) result is cached too, on the
# same TTL: re-querying every call for a ticker IBKR has already definitively failed to
# resolve would defeat the point of caching for exactly the tickers most likely to be
# requested repeatedly (e.g. a cross-listed ticker a watchlist polls regularly -- see this
# task's `decisions` entry on `_resolve_stk_conid`'s existing ambiguity behavior for a
# live example found during this task's own research).
_CONID_CACHE_TTL_SECONDS = 24 * 60 * 60.0

# `backend-ibkr-conid-db-cache`: `_CONID_CACHE_TTL_SECONDS` above only ever protected a
# single process's lifetime -- every restart (a deploy, a crash, a dev-container rebuild)
# lost every resolution and re-paid the live `/iserver/secdef/search` + ambiguity-scan
# cost on next use, even though a *successful* conid resolution is, for all practical
# purposes, permanent (only a genuine re-listing/delisting event changes it, never a
# routine restart). `IBKRConidCacheORM` (app/db/models.py) persists exactly that
# successful-resolution case so it survives a restart; see that model's own docstring for
# the full rationale, and `resolve_conid`'s docstring for how it's layered under the
# existing in-memory cache (fast path) as a fallback (survives-restart path) ahead of a
# live call. See this task's `decisions` entry.

GatewayState = Literal["available", "gateway_unreachable", "not_authenticated"]


@dataclass(frozen=True)
class GatewayStatus:
    """Result of `IBKRProvider.get_gateway_status` -- the app-wide "is this optional
    provider usable right now" check, checklist item 2's distinguishable states:

    - ``available``: gateway is running and `/iserver/auth/status` reports an
      authenticated session -- data-fetching methods can be called.
    - ``gateway_unreachable``: no process is listening at the configured base URL (or it
      returned something other than a normal 200 JSON response) -- most likely the
      gateway simply isn't running.
    - ``not_authenticated``: the gateway process is up and answering, but its own
      response says the browser login step hasn't been completed (or the session has
      since expired) -- distinct from `gateway_unreachable` since the fix is "log in at
      https://localhost:5000/", not "start the gateway".

    `detail` carries whatever human-readable context is available (the transport error
    string, or the gateway's own `message` field) for logging/surfacing to a caller --
    never required for a caller to branch on, only `state` is.
    """

    state: GatewayState
    detail: str | None = None


@dataclass(frozen=True)
class IBKRBar:
    """One OHLCV bar from `/iserver/marketdata/history` (docs/ideas.md), at whatever
    granularity `get_hourly_bars`'s `bar_size` parameter requested (`"1h"` by default --
    `backend-ibkr-bar-interval-param`)."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ScannerResult:
    """One contract returned by `/iserver/scanner/run` (docs/ideas.md's market-scanner
    entry -- 52-week-high/low, hot-by-volume, etc.). Deliberately minimal: this task's
    checklist scope is "the scanner query + a sensible caching layer", not modeling every
    field IBKR's scanner response can carry -- a future consumer needing more (e.g. the
    contract's exchange) can extend this dataclass then, see this task's `decisions`
    entry.
    """

    conid: int
    symbol: str | None
    company_name: str | None
    rank: int | None


@dataclass(frozen=True)
class IBKRAccountPosition:
    """One equity position from `GET /portfolio/{accountId}/positions/{pageId}`
    (`get_account_positions`, `backend-ibkr-portfolio-preload`'s checklist item 1) --
    `ticker` is already resolved to the plain symbol string every other consumer in this
    app keys a position by (`app.db.models.PositionORM.ticker`), not the raw IBKR conid
    alone -- see `get_account_positions`'s own docstring for how and why. Only ever
    constructed for a `"STK"`-asset-class row with a positive `quantity` and a resolvable
    ticker -- `_parse_account_positions` drops every other row (options/futures/warrants,
    a flat/short/closed-out position, or a row this app couldn't derive a clean ticker
    string from) rather than representing it with a null field, matching `ScannerResult`'s
    own "drop what we can't use" precedent in this module. `avg_cost` stays independently
    nullable (unlike the other three fields) since IBKR's own response can omit it even
    for an otherwise-well-formed STK row; a position with no known cost basis is excluded
    entirely from both the preview and the import path, not surfaced as an unimportable
    candidate (see `app.api.routers.ibkr._valid_import_candidates`)."""

    conid: int
    ticker: str
    quantity: float
    avg_cost: float | None


class IBKRUnavailableError(Exception):
    """Raised when a data-fetching method (`get_hourly_bars`/`get_scanner_params`/
    `run_scanner`) can't complete: either the gateway itself is confirmed not
    `available` (see `GatewayStatus`) before any request is attempted, or a genuine
    per-call failure occurs against a gateway that was reachable a moment ago (transport
    error, non-200 response, or an unparseable body). Callers that want the softer
    "is it up right now" signal without an exception should call `get_gateway_status()`
    directly instead -- that method never raises this.
    """


class IBKRRateLimitedError(Exception):
    """Raised by `run_scanner` when called again sooner than the Web API's documented 1
    request/second limit allows since this instance's own last call -- enforced
    client-side (a monotonic-clock check, no network round-trip) so a caller finds out
    immediately rather than spending a real HTTP request IBKR's own gateway would likely
    reject anyway. Not raised by `get_scanner_params` -- that method's 1-req/15-min limit
    is instead handled by simply serving the cached result (see `_SCANNER_PARAMS_TTL_SECONDS`),
    since a stale-but-still-valid scanner-parameter list is a perfectly good answer,
    unlike a scan result which is meaningfully time-sensitive. See this task's
    `decisions` entry.
    """

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"IBKR scanner run rate-limited; retry again in {retry_after:.2f}s")


class IBKRProvider:
    """Optional secondary market-data source: hourly bars + the market scanner, via a
    locally-run IB Gateway (Client Portal Gateway), plus `resolve_conid` for turning a
    plain ticker symbol into the IBKR conid those two capabilities actually key off of
    (docs/tasks/backend-ibkr-symbol-resolution.json). See this module's own docstring for
    why it's a distinct class rather than a `DataProvider` implementation, and
    `docs/architecture/Backend.md` for the human setup walkthrough.

    Entirely inert until constructed and used -- nothing in the rest of the app imports
    or calls this class today (`app.api.dependencies.get_ibkr_provider` is the only
    current caller, itself unused by any route yet, gated behind `Settings.ibkr_enabled`
    which defaults to `False`), matching this task's "app works exactly as today with no
    IBKR setup at all" requirement.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        """`client`, `clock`, and `sleep` are injectable purely for testability (per this
        task's mocked-HTTP-only testing constraint) -- production callers should leave all
        three at their defaults. `clock` uses `time.monotonic` (not wall-clock time) since
        it only ever measures elapsed intervals for the two rate limits, never an absolute
        timestamp; a test can inject a simple counter instead of a real clock to make
        rate-limit behavior deterministic without sleeping. `sleep` backs `_request`'s own
        single-quick-retry delay (`backend-ibkr-request-retry`) -- a test exercising the
        retry path injects a no-op/recording stub instead of a real `time.sleep` so the
        suite doesn't actually pause for `_REQUEST_RETRY_DELAY_SECONDS` on every retry test.

        `session_factory` (`backend-ibkr-conid-db-cache`) is how `resolve_conid` reaches
        `IBKRConidCacheORM` -- a zero-arg callable returning a fresh `Session` each time it's
        called, e.g. `app.db.session.SessionLocal` itself (not a pre-opened `Session`
        instance), because this class is constructed once as a process-wide singleton
        (`app.api.dependencies._get_ibkr_provider_singleton`) that long outlives any single
        request's own DB session -- mirrors `app.api.dependencies.get_data_provider_factory`'s
        own "open a session, use it, close it" pattern for the same reason (a long-lived
        object that can't hold one request-scoped `Session` open indefinitely). Defaults to
        `None`, which disables the DB cache entirely (every test in this module that doesn't
        care about it keeps working unmodified, and `resolve_conid` falls straight through to
        the in-memory cache + live call exactly as before this task) -- production wiring
        passes `SessionLocal`.
        """
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(verify=False, timeout=timeout)
        self._owns_client = client is None
        self._clock = clock
        self._sleep = sleep
        self._session_factory = session_factory
        self._scanner_params_cache: tuple[float, dict] | None = None
        self._last_scanner_run_at: float | None = None
        self._gateway_status_cache: tuple[float, GatewayStatus] | None = None
        # Double-checked locking around `_gateway_status_cache`'s own check-fetch-store
        # sequence (`get_gateway_status`, `backend-ibkr-primary-data-provider-followups`)
        # -- there's only ever one gateway-status cache entry (unlike `_conid_cache`
        # below, which is keyed per ticker), so a single lock for the whole sequence
        # doesn't cost any cross-ticker concurrency: every caller is checking the exact
        # same fact. Without it, a cold-cache race (every concurrent request's
        # `_is_ibkr_connected()` plus every per-ticker fetch's own `_require_available()`
        # guard, now far more concurrent traffic than this class's one pre-existing
        # cache -- `_scanner_params_cache` -- ever saw) lets several threads all observe
        # a miss and each issue its own redundant `GET /iserver/auth/status` call, with
        # whichever write lands last silently overwriting the others' -- wasted gateway
        # round trips, not a wrong-answer bug (see this task's own checklist), but worth
        # closing given how much more concurrent traffic this cache now sees. Mirrors
        # `app.api.dependencies._get_ibkr_provider_singleton`'s own double-checked-locking
        # rationale and shape.
        self._gateway_status_lock = threading.Lock()
        self._conid_cache: dict[str, tuple[float, int | None]] = {}
        # Per-ticker locks for `_conid_cache`'s own check-fetch-store sequence
        # (`resolve_conid`), guarded by `_conid_cache_locks_lock` only while looking up
        # or creating the per-ticker lock itself -- deliberately NOT one single lock for
        # the whole cache (unlike `_gateway_status_lock` above): `IBKRDataProvider.
        # get_daily_ohlcv`/`get_weekly_ohlcv` resolve a *different* ticker's conid inside
        # each leg of `enrich_positions_with_price`/day-trader-mode's per-ticker
        # `ThreadPoolExecutor` fan-out, so serializing every ticker's resolution behind
        # one lock (holding it for the full `_request` round trip) would silently
        # re-introduce the exact sequential-fetch cost that fan-out exists to avoid.
        # Locking only per ticker still closes the same-ticker race the single-lock
        # gateway-status case has (two threads racing to resolve the same cold ticker)
        # without serializing unrelated tickers against each other.
        self._conid_cache_locks: dict[str, threading.Lock] = {}
        self._conid_cache_locks_lock = threading.Lock()

    def close(self) -> None:
        """Release the underlying HTTP client -- a no-op if this instance was
        constructed with an injected `client` (tests), since that client's lifecycle
        belongs to whoever created it, not to this instance."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> IBKRProvider:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def get_gateway_status(self) -> GatewayStatus:
        """Whether the gateway is up and authenticated, via `/iserver/auth/status`
        (checklist item 2). Never raises -- every failure mode this method can observe
        (gateway not running, unreachable, or answering but not logged in) is
        represented as a `GatewayStatus` value instead, since "is this optional feature
        usable right now" is exactly the kind of check a caller wants to make without a
        try/except.

        Cached for `_GATEWAY_STATUS_TTL_SECONDS` (see that constant's own comment for the
        full rationale) -- `backend-ibkr-primary-data-provider`'s checklist item 3. Every
        other method on this class that gates on availability (`_require_available`)
        calls this same method, so they transparently share this cache too: once
        `app.api.dependencies.get_data_provider` has checked connectivity for a request,
        an actual data-fetching call moments later doesn't pay for a second live round
        trip to confirm the same thing again.

        Double-checked locking around the whole check-fetch-store sequence
        (`_gateway_status_lock`, `backend-ibkr-primary-data-provider-followups`) so a
        concurrent cold-cache race can't make more than one thread issue the real
        `GET /iserver/auth/status` call -- see that lock's own comment (`__init__`).
        """
        cached = self._gateway_status_cache
        if cached is not None:
            cached_at, status = cached
            if self._clock() - cached_at < _GATEWAY_STATUS_TTL_SECONDS:
                return status

        with self._gateway_status_lock:
            # Re-check under the lock: another thread may have already refreshed the
            # cache while this one was waiting to acquire it.
            cached = self._gateway_status_cache
            if cached is not None:
                cached_at, status = cached
                if self._clock() - cached_at < _GATEWAY_STATUS_TTL_SECONDS:
                    return status

            try:
                payload = self._request("GET", "/iserver/auth/status")
            except IBKRUnavailableError as exc:
                status = GatewayStatus(state="gateway_unreachable", detail=str(exc))
                self._gateway_status_cache = (self._clock(), status)
                return status

            if not isinstance(payload, dict) or not payload.get("authenticated"):
                detail = payload.get("message") if isinstance(payload, dict) else None
                status = GatewayStatus(state="not_authenticated", detail=detail)
            else:
                status = GatewayStatus(state="available")
            self._gateway_status_cache = (self._clock(), status)
            return status

    def tickle(self) -> None:
        """Keep the gateway session alive via `GET /tickle`
        (docs/architecture/Backend.md §8: "keep the session alive with a periodic GET
        /tickle call roughly once a minute" -- `backend-ibkr-tickle-keepalive`). Goes
        through `_request` like every other method on this class, so a transport
        error/non-200/unparseable body surfaces as the same `IBKRUnavailableError`; the
        response body itself carries nothing this method's callers need (IBKR's own docs
        don't document a meaningful payload beyond confirming the ping succeeded), so it's
        discarded rather than returned.

        Deliberately does **not** call `_require_available()` first, unlike
        `get_hourly_bars`/`get_scanner_params`/`run_scanner`/`resolve_conid` -- those
        methods gate on availability because a data-fetching call against an
        unauthenticated gateway is pointless and would fail anyway, but `/tickle`'s whole
        purpose *is* refreshing a session that's expected to still be authenticated.
        Gating it behind `_require_available()` would call `GET /iserver/auth/status`
        immediately before every single `/tickle`, doubling the request volume against
        the gateway for no benefit -- if the session has actually expired, `/tickle`
        itself will simply fail the same way `_require_available()`'s own status check
        would have. See this task's `decisions` entry.

        Raises:
            IBKRUnavailableError: the gateway is unreachable, or the request fails.
        """
        self._request("GET", "/tickle")

    def get_hourly_bars(
        self, conid: int, *, lookback_days: int = 30, bar_size: str = _BAR_INTERVAL
    ) -> list[IBKRBar]:
        """OHLCV bars for IBKR contract id `conid`, covering roughly the last
        `lookback_days` days -- the Screen 3 intraday entry-timing mechanism this task's
        `description` names. Walks `/iserver/marketdata/history`'s `startTime` parameter
        backward across as many calls as needed, since a single call returns at most
        `_MAX_BARS_PER_PAGE` (1,000) points (~41 days at the default `"1h"` `bar_size`) --
        checklist item 3.

        `bar_size` (`backend-ibkr-bar-interval-param`) selects the granularity via
        `/iserver/marketdata/history`'s own `bar` query parameter, defaulting to `"1h"`
        so every existing caller's behavior is unchanged. Must be one of
        `_VALID_BAR_INTERVALS` (IBKR's documented enumerated set) -- this method still
        keeps its `get_hourly_bars` name (rather than a generic `get_bars`) since that
        default remains the only granularity any real caller uses today; see this task's
        `decisions` entry. `_MAX_PAGINATION_PAGES`'s 20-page safety bound was sized
        against `"1h"` bars (~833 days of history); a finer `bar_size` (e.g. `"5min"`)
        covers proportionally less history before hitting that same page cap -- a day-
        trader-mode feature that actually needs deep finer-grained history would need to
        revisit that bound, out of scope here (see this task's `description`).

        `conid` is `int` (not `str`) to match `resolve_conid`'s return type and
        `ScannerResult.conid` -- this class's one consistent in-memory representation of
        an IBKR contract id, converted to a string only at this method's own HTTP
        request boundary (query params are always strings on the wire). See
        `backend-ibkr-symbol-resolution-followups`'s `decisions` entry for why this
        method's signature changed rather than `resolve_conid`'s.

        Raises:
            ValueError: `bar_size` isn't one of IBKR's documented accepted bar values.
            IBKRUnavailableError: the gateway isn't `available` (see `get_gateway_status`),
                or a request made while paginating fails.
        """
        if bar_size not in _VALID_BAR_INTERVALS:
            raise ValueError(
                f"Unsupported IBKR bar interval {bar_size!r}; must be one of "
                f"{sorted(_VALID_BAR_INTERVALS)}"
            )
        self._require_available()
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        collected: dict[datetime, IBKRBar] = {}
        start_time: str | None = None
        for _ in range(_MAX_PAGINATION_PAGES):
            params: dict[str, str] = {"conid": str(conid), "bar": bar_size}
            if start_time is None:
                # First page: no cursor yet, so ask for the whole requested span via
                # `period` -- if `lookback_days` implies more than 1,000 hourly bars,
                # IBKR simply caps the response at that page size server-side, which the
                # loop below then continues paginating from.
                params["period"] = f"{max(lookback_days, 1)}d"
            else:
                params["startTime"] = start_time

            payload = self._request("GET", "/iserver/marketdata/history", params=params)
            raw_row_count = len(payload.get("data") or []) if isinstance(payload, dict) else 0
            page_bars = _parse_bars(payload)
            if not page_bars:
                break

            new_bars = [bar for bar in page_bars if bar.timestamp not in collected]
            for bar in new_bars:
                collected[bar.timestamp] = bar

            earliest = min(bar.timestamp for bar in page_bars)
            # The full-page/short-page decision below is deliberately based on the raw
            # response's row count, not `len(page_bars)` (the post-`_parse_bars` count,
            # which drops malformed rows) -- otherwise a single malformed row in an
            # otherwise-full page would make this look like a short/final page and stop
            # pagination early, silently truncating history with no error surfaced.
            if earliest <= cutoff or raw_row_count < _MAX_BARS_PER_PAGE or not new_bars:
                # Reached the requested lookback window, the source has no more bars
                # further back than this page, or this page brought back nothing new
                # (a non-advancing cursor -- stop rather than loop without progress).
                break
            # Walk the cursor to just before the earliest bar this page returned, so the
            # next page doesn't re-fetch it -- stepped by one `bar_size`-worth of time
            # (not a hardcoded hour) so a finer interval than the `"1h"` this logic was
            # originally written against doesn't skip bars in the gap.
            start_time = (earliest - _BAR_INTERVAL_STEP[bar_size]).strftime("%Y%m%d-%H:%M:%S")

        return sorted((bar for bar in collected.values() if bar.timestamp >= cutoff), key=lambda b: b.timestamp)

    def get_daily_bars(self, conid: int) -> list[IBKRBar]:
        """Daily OHLCV bars for IBKR contract id `conid` -- the data
        `app.data.ibkr_data_provider.IBKRDataProvider.get_daily_ohlcv` needs
        (`backend-ibkr-primary-data-provider`'s checklist items 1/5).

        A single `/iserver/marketdata/history` call at `bar="1d"`/`period=_DAILY_BARS_
        PERIOD` -- deliberately does **not** reuse `get_hourly_bars`'s pagination loop,
        for two reasons this task's `decisions` entry records in full: (1) `_DAILY_BARS_
        PERIOD` was chosen specifically because it already sits at or past IBKR's own
        confirmed-live response ceiling for this bar size, so a second page would never
        have anything left to return; and (2) `get_hourly_bars`'s own "a short page (fewer
        than `_MAX_BARS_PER_PAGE` rows) means there's nothing further back" pagination-stop
        heuristic was observed live to be actually wrong for `bar="1d"` specifically --
        combining `startTime` with `period` on a follow-up request returned *additional*
        older bars even though the first page's row count was already just under
        `_MAX_BARS_PER_PAGE`. Inheriting that loop here would silently under-report history
        by one page's worth in exactly the case this method exists to serve well; a single,
        unpaginated request sidesteps that bug entirely rather than risk reproducing it, and
        `docs/Analyse.md`'s own documented minimum (~200 trading days) is comfortably
        covered by one page regardless (confirmed live: ~999 daily bars, ~4 calendar years).

        Returns bars ordered oldest-first (`_parse_bars`' own ordering, matching every
        source IBKR returns by default) -- the same ordering the `DataProvider` protocol
        requires (app/data/base.py).

        Raises:
            IBKRUnavailableError: the gateway isn't `available` (see `get_gateway_status`),
                or the request fails.
        """
        self._require_available()
        payload = self._request(
            "GET",
            "/iserver/marketdata/history",
            params={"conid": str(conid), "bar": "1d", "period": _DAILY_BARS_PERIOD},
        )
        return _parse_bars(payload)

    def get_weekly_bars(self, conid: int) -> list[IBKRBar]:
        """Weekly OHLCV bars for IBKR contract id `conid` -- `get_daily_bars`'s sibling for
        `IBKRDataProvider.get_weekly_ohlcv`. Same single-request shape (`bar="1w"`,
        `period=_WEEKLY_BARS_PERIOD`) and the same reasons for not pagination -- see
        `get_daily_bars`'s own docstring; confirmed live to return up to 1,000 weekly bars
        (~19 calendar years), comfortably past Screen 1's 26-week minimum
        (`app.data.yfinance_provider._MIN_WEEKLY_BARS`).

        Raises:
            IBKRUnavailableError: the gateway isn't `available` (see `get_gateway_status`),
                or the request fails.
        """
        self._require_available()
        payload = self._request(
            "GET",
            "/iserver/marketdata/history",
            params={"conid": str(conid), "bar": "1w", "period": _WEEKLY_BARS_PERIOD},
        )
        return _parse_bars(payload)

    def get_scanner_params(self) -> dict:
        """The market scanner's valid filter/instrument/location/scan-type options, from
        `/iserver/scanner/params` -- cached for `_SCANNER_PARAMS_TTL_SECONDS` (15 minutes,
        matching the documented 1-req/15-min limit) since this option list changes rarely
        enough that serving a stale-but-recent cached copy is a perfectly good answer,
        unlike `run_scanner`'s actual results (checklist item 4).

        Raises:
            IBKRUnavailableError: the gateway isn't `available`, or the request fails --
                only reached on a cache miss/expiry.
        """
        cached = self._scanner_params_cache
        if cached is not None:
            cached_at, payload = cached
            if self._clock() - cached_at < _SCANNER_PARAMS_TTL_SECONDS:
                return payload

        self._require_available()
        raw_payload = self._request("GET", "/iserver/scanner/params")
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        self._scanner_params_cache = (self._clock(), payload)
        return payload

    def run_scanner(self, scan_config: dict) -> list[ScannerResult]:
        """Run the market scanner via `POST /iserver/scanner/run` with `scan_config` as
        the request body (IBKR's own documented shape: `instrument`/`type`/`location`/
        `filter` keys, taken as-is from `get_scanner_params`'s option lists -- this
        provider doesn't validate `scan_config` itself, since the option universe is
        entirely gateway-defined and versioned by IBKR, not something worth duplicating
        here). This is the real market-breadth mechanism docs/ideas.md names (52-week
        high/low, hot-by-volume) -- checklist item 4.

        Raises:
            IBKRUnavailableError: the gateway isn't `available`, or the request fails.
            IBKRRateLimitedError: called again sooner than 1 second since this instance's
                own last `run_scanner` call (see this class's own docstring, and
                `IBKRRateLimitedError`'s).
        """
        # The cheap client-side throttle check runs FIRST, before `_require_available`
        # (which itself makes a real `GET /iserver/auth/status` HTTP call) -- otherwise a
        # caller retrying within the same second would still pay for a real HTTP round
        # trip on every call before ever reaching the rate-limit check, defeating the
        # whole "no network round-trip" point of `IBKRRateLimitedError` (see its own
        # docstring).
        now = self._clock()
        if self._last_scanner_run_at is not None:
            elapsed = now - self._last_scanner_run_at
            if elapsed < _SCANNER_RUN_MIN_INTERVAL_SECONDS:
                raise IBKRRateLimitedError(retry_after=_SCANNER_RUN_MIN_INTERVAL_SECONDS - elapsed)

        self._require_available()
        payload = self._request("POST", "/iserver/scanner/run", json=scan_config)
        self._last_scanner_run_at = self._clock()
        return _parse_scanner_results(payload)

    def resolve_conid(self, ticker: str) -> int | None:
        """Resolve a ticker symbol (e.g. ``"AAPL"``) to IBKR's own numeric conid via
        ``GET /iserver/secdef/search`` -- the missing piece `get_hourly_bars`/
        `run_scanner` need before either can be driven by a plain ticker the way every
        other data source in this app is, rather than an already-known IBKR contract id
        (`backend-ibkr-data-provider`'s own `decisions` entry explicitly deferred
        researching this endpoint; this task's own `decisions` entry records the
        documented request/response shape this was implemented against).

        Matches on an exact (case-insensitive) symbol match that has a ``"STK"`` entry
        in its ``sections`` list (the search endpoint's response also mixes in
        options/warrants/futures tied to the same underlying, and can return unrelated
        symbols as fuzzy/partial matches -- neither is a usable equity conid here).

        When a bare symbol search returns more than one distinct stock conid -- confirmed
        live to be the norm, not an edge case, for heavily-tracked US tickers (IBKR lists
        AAPL/MSFT/GOOGL/etc. on several of its own international feeder-exchange programs
        under the same symbol, alongside the primary US listing -- see `_US_PRIMARY_
        EXCHANGES`'s own comment for the full live research) -- prefers the single
        candidate whose search-result `description` names a primary US listing venue
        (`_US_PRIMARY_EXCHANGES`) over degrading to `None`. Only falls back to `None` for a
        true **no-match** ticker, or a genuinely **ambiguous** one where that preference
        doesn't leave exactly one candidate (none of them is a recognized US venue, or --
        not observed live, but structurally possible -- more than one is): silently
        guessing among several still-ambiguous candidates risks resolving to the wrong
        instrument entirely, which is worse than surfacing "could not resolve
        automatically" and asking a human to supply a conid directly instead. See this
        task's `decisions` entry.

        Cached per (uppercased) ticker for `_CONID_CACHE_TTL_SECONDS` (see that constant's
        own comment) -- `backend-ibkr-primary-data-provider`'s checklist item 2, once a
        ticker-keyed `DataProvider` adapter built on top of this method
        (`app.data.ibkr_data_provider.IBKRDataProvider`) could otherwise re-resolve the
        same ticker's conid on every single request. Caches a `None` (unresolved/
        ambiguous) result too, on the same TTL -- see that constant's own comment for why.

        On an in-memory cache miss (including every miss right after a process restart,
        which clears `_conid_cache` entirely), falls back to `IBKRConidCacheORM`
        (`backend-ibkr-conid-db-cache`, only when `session_factory` was supplied to
        `__init__`) before ever making a live call -- a DB-cache hit both returns
        immediately *and* repopulates `_conid_cache` so this process's later calls for the
        same ticker hit the fast in-memory path again. Only a **successful** resolution is
        ever persisted there (a `None`/ambiguous result is not) -- see
        `IBKRConidCacheORM`'s own docstring for why, and this task's `decisions` entry. A
        DB-cache hit skips `_require_available()` entirely (no gateway call at all for an
        already-known-permanent mapping); only a genuine DB-cache miss falls through to the
        live `GET /iserver/secdef/search` path below, same as before this task.

        Double-checked locking per ticker (`_conid_cache_locks`, `backend-ibkr-primary-
        data-provider-followups`) so a concurrent cold-cache race for the *same* ticker
        can't make more than one thread issue the real `GET /iserver/secdef/search` call
        -- while still letting concurrent resolution of *different* tickers (e.g. this
        app's own per-ticker `ThreadPoolExecutor` fan-out) proceed fully in parallel. See
        `__init__`'s own comment on `_conid_cache_locks` for why this is per-ticker rather
        than one lock for the whole cache (unlike `_gateway_status_lock`). The DB read/write
        below also happens inside this same per-ticker lock -- simpler than a second,
        independent locking scheme, and the DB-write side still has its own
        `IntegrityError`/`OperationalError` handling (`_write_conid_db_cache`) for the
        cross-*instance* race this in-process lock can't prevent (two separate
        `IBKRProvider` instances, e.g. across a process restart racing a lingering old
        process, or two instances in a test, both resolving the same previously-unresolved
        ticker at once).

        Raises:
            IBKRUnavailableError: the gateway isn't `available` (see
                `get_gateway_status`), or the request itself fails. Never raised on a
                DB-cache hit (no gateway call is made in that case).
        """
        cache_key = ticker.upper()
        cached = self._conid_cache.get(cache_key)
        if cached is not None:
            cached_at, conid = cached
            if self._clock() - cached_at < _CONID_CACHE_TTL_SECONDS:
                return conid

        with self._get_conid_cache_lock(cache_key):
            # Re-check under the lock: another thread may have already resolved and
            # cached this exact ticker while this one was waiting to acquire it.
            cached = self._conid_cache.get(cache_key)
            if cached is not None:
                cached_at, conid = cached
                if self._clock() - cached_at < _CONID_CACHE_TTL_SECONDS:
                    return conid

            db_conid = self._read_conid_db_cache(cache_key)
            if db_conid is not None:
                self._conid_cache[cache_key] = (self._clock(), db_conid)
                return db_conid

            self._require_available()
            payload = self._request("GET", "/iserver/secdef/search", params={"symbol": ticker})
            conid = _resolve_stk_conid(payload, ticker)
            self._conid_cache[cache_key] = (self._clock(), conid)
            if conid is not None:
                self._write_conid_db_cache(cache_key, conid)
            return conid

    def _get_conid_cache_lock(self, cache_key: str) -> threading.Lock:
        """The per-ticker lock `resolve_conid` serializes a cold-cache race on, created
        lazily on first use and reused for the lifetime of this instance -- `_conid_cache`
        and `_conid_cache_locks` grow at the same unbounded-but-small rate (one entry per
        distinct ticker this instance has ever resolved), matching `_conid_cache`'s own
        existing no-eviction behavior (not a new concern this introduces).
        """
        with self._conid_cache_locks_lock:
            lock = self._conid_cache_locks.get(cache_key)
            if lock is None:
                lock = threading.Lock()
                self._conid_cache_locks[cache_key] = lock
            return lock

    def _read_conid_db_cache(self, cache_key: str) -> int | None:
        """`IBKRConidCacheORM` lookup for `resolve_conid`'s DB-cache fallback -- a no-op
        (`None`, same as a genuine miss) when `self._session_factory` wasn't supplied
        (`__init__`'s default), so this method is always safe to call unconditionally from
        `resolve_conid` regardless of whether the DB cache is wired up.

        Opens and closes its own short-lived `Session` per call (`self._session_factory()`)
        rather than holding one open for this long-lived singleton's lifetime -- see
        `__init__`'s own docstring on `session_factory` for why.

        A transient `OperationalError` (e.g. SQLite's default whole-file write lock
        rejecting a concurrent read with "database is locked" -- `app/db/session.py` sets
        up no WAL mode/`busy_timeout`, so this is a real, not just theoretical, failure
        mode; see PR #384's review) is treated exactly like a genuine cache miss (`None`)
        rather than propagated, the same as `IntegrityError` (defensive here -- a plain
        `SELECT` can't itself violate a constraint, but catching it alongside
        `OperationalError` costs nothing and keeps this method's error handling
        symmetric with `_write_conid_db_cache`'s). This is required, not just
        defensive-for-its-own-sake: `resolve_conid`'s own docstring documents (and
        `app.api.day_trader_signal`'s batch fan-out relies on) `resolve_conid` never
        raising anything but `IBKRUnavailableError` -- a best-effort DB-cache read must
        never be able to turn into an uncaught exception that crashes an entire batch
        request over what should just fall through to a live resolution instead.
        """
        if self._session_factory is None:
            return None
        db = self._session_factory()
        try:
            row = db.query(IBKRConidCacheORM).filter(IBKRConidCacheORM.ticker == cache_key).one_or_none()
            return row.conid if row is not None else None
        except (IntegrityError, OperationalError) as exc:
            logger.warning(
                "IBKR conid DB-cache read for %r failed (treating as a cache miss, "
                "falling through to a live resolution): %s: %s",
                cache_key,
                type(exc).__name__,
                exc,
            )
            return None
        finally:
            db.close()

    def _write_conid_db_cache(self, cache_key: str, conid: int) -> None:
        """Persist a freshly, successfully resolved `conid` to `IBKRConidCacheORM` -- a
        no-op when `self._session_factory` wasn't supplied, same as `_read_conid_db_cache`.
        Only ever called with a non-`None` `conid` (see `resolve_conid`) -- this table never
        stores an unresolved/ambiguous result (`IBKRConidCacheORM`'s own docstring).

        This is purely a best-effort write: `conid` (the caller's already-successful live
        resolution) is returned to `resolve_conid`'s caller regardless of whether anything
        in this method succeeds, so nothing here may ever raise. The pre-commit `SELECT`
        below gets the exact same `IntegrityError`/`OperationalError` handling as the
        `commit()` itself (treating a failed read the same as "no existing row, insert a
        new one" -- at worst a redundant row-already-exists `IntegrityError` on `commit()`
        just below, which that commit's own except block already discards the same way) --
        see `_read_conid_db_cache`'s docstring for why an unwrapped `SELECT` on a
        non-WAL-mode SQLite DB (`app/db/session.py`) is a real, not just theoretical,
        failure mode this method must not let escape.
        """
        if self._session_factory is None:
            return
        db = self._session_factory()
        try:
            try:
                row = db.query(IBKRConidCacheORM).filter(IBKRConidCacheORM.ticker == cache_key).one_or_none()
            except (IntegrityError, OperationalError) as exc:
                logger.warning(
                    "IBKR conid DB-cache pre-write read for %r failed (treating as 'no "
                    "existing row' and inserting fresh): %s: %s",
                    cache_key,
                    type(exc).__name__,
                    exc,
                )
                db.rollback()
                row = None
            if row is None:
                row = IBKRConidCacheORM(ticker=cache_key)
                db.add(row)
            row.conid = conid
            row.resolved_at = utcnow()
            try:
                db.commit()
            except (IntegrityError, OperationalError) as exc:
                # Same benign concurrent-first-population race `CachedDataProvider._upsert`
                # (app/data/cache.py) documents at length: two concurrent callers resolving
                # the same previously-unresolved ticker for the first time (e.g. two
                # `IBKRProvider` instances, since this in-process per-ticker lock
                # (`_get_conid_cache_lock`) already prevents this race within one instance)
                # can both attempt to insert this row; the loser discards its own write
                # rather than erroring, since `conid` (this call's own freshly resolved
                # result) is still returned to `resolve_conid`'s caller regardless of
                # whether this commit succeeds -- only a redundant write is lost, not the
                # answer itself.
                db.rollback()
                logger.warning(
                    "Concurrent IBKR conid DB-cache population for %r raced this write; "
                    "discarding this attempt in favor of the concurrently-committed row. "
                    "(%s: %s)",
                    cache_key,
                    type(exc).__name__,
                    exc,
                )
        finally:
            db.close()

    def get_account_positions(self) -> list[IBKRAccountPosition]:
        """The connected IBKR account's current equity positions
        (`backend-ibkr-portfolio-preload`'s checklist item 1) -- discovers the account id
        via `GET /iserver/accounts`, then paginates
        `GET /portfolio/{accountId}/positions/{pageId}` (`pageId` starting at 0) until a
        page comes back empty, per IBKR's own documented convention for this endpoint.
        This task's own `decisions` entry records the exact documented shape both calls
        were implemented against and why (this module's established no-live-gateway
        research pattern -- see `resolve_conid`'s own `decisions` entry for the
        precedent).

        `GET /iserver/accounts` is expected to return a JSON object with an `"accounts"`
        list of account-id strings and (usually) a `"selectedAccount"` string identifying
        which one is currently active for this session -- `selectedAccount` is preferred
        when present (the session's own notion of "the" account), falling back to the
        first entry in `accounts` otherwise. Raises `IBKRUnavailableError` if neither is
        usable (an empty/missing `accounts` list, or a response that isn't the expected
        JSON object at all) -- there is no way to proceed without an account id, and a
        silently-fabricated one would be far worse than a loud, actionable error here.

        Each page of `GET /portfolio/{accountId}/positions/{pageId}` is documented as a
        plain JSON array of position objects (not wrapped in an envelope, unlike
        `/iserver/marketdata/history`'s `{"data": [...]}` shape) -- see
        `_parse_account_positions` for the per-row field shape this was implemented
        against and which rows are kept vs. dropped. Only a `"STK"`-asset-class row with a
        resolvable ticker and a strictly positive `quantity` becomes an
        `IBKRAccountPosition` -- this app's portfolio model (`app.db.models.PositionORM`)
        has no representation for options/futures/warrants or a short/flat position, so
        those rows are silently dropped rather than surfaced with a null/nonsensical
        ticker (see this task's `decisions` entry).

        Raises:
            IBKRUnavailableError: the gateway isn't `available` (see
                `get_gateway_status`), the account id can't be discovered, or a request
                made while paginating fails.
        """
        self._require_available()
        account_id = self._discover_account_id()

        positions: list[IBKRAccountPosition] = []
        for page_id in range(_MAX_ACCOUNT_POSITIONS_PAGES):
            payload = self._request("GET", f"/portfolio/{account_id}/positions/{page_id}")
            page_positions = _parse_account_positions(payload)
            if not page_positions:
                break
            positions.extend(page_positions)
        return positions

    def _discover_account_id(self) -> str:
        """`GET /iserver/accounts` -- see `get_account_positions`'s own docstring for the
        documented response shape this was implemented against."""
        payload = self._request("GET", "/iserver/accounts")
        if not isinstance(payload, dict):
            raise IBKRUnavailableError(
                "IBKR /iserver/accounts returned an unexpected (non-object) response shape"
            )
        selected = payload.get("selectedAccount")
        if isinstance(selected, str) and selected:
            return selected
        accounts = payload.get("accounts")
        if isinstance(accounts, list) and accounts and isinstance(accounts[0], str) and accounts[0]:
            return accounts[0]
        raise IBKRUnavailableError("IBKR /iserver/accounts reported no usable account id for this session")

    def _require_available(self) -> None:
        status = self.get_gateway_status()
        if status.state != "available":
            raise IBKRUnavailableError(f"IBKR gateway not available ({status.state}): {status.detail}")

    def _request(self, method: str, path: str, **kwargs: object) -> dict | list:
        """The one method that performs a real HTTP call against the gateway -- every
        other method on this class goes through this, so tests mock this single boundary
        (per docs/architecture/Testing.md, matching `StooqProvider._fetch_csv`'s role in
        that provider) rather than the `httpx.Client` internals.

        Retries exactly once (`_REQUEST_MAX_ATTEMPTS`, `backend-ibkr-request-retry`) after
        `_REQUEST_RETRY_DELAY_SECONDS`, but only for a failure genuinely plausible as a
        transient blip rather than one retrying can't fix:

        - A network/connection-level `httpx.RequestError` (refused/reset/DNS failure etc.)
          -- retried, **except** when it's specifically a `httpx.TimeoutException` (a
          connect/read/write/pool timeout already spent this call's full `timeout` budget
          waiting -- retrying would silently double a slow-failure's already-worst-case
          latency for a caller with its own timeout expectations, most notably
          `get_analysis`'s concurrent daily/weekly/extended `ThreadPoolExecutor` fan-out and
          day-trader-mode's per-leg fan-out, see `_REQUEST_MAX_ATTEMPTS`'s own comment --
          with no evidence from this session's own observed flakiness that a slow gateway
          would recover any faster on a second attempt than a fast one would).
        - An HTTP 5xx response -- retried (server-side failure, plausibly transient).
        - An HTTP 4xx response (401/403 unauthenticated, 400 "no bridge", etc.) -- **not**
          retried: these reflect the gateway's current session/request state, which a
          300ms-later identical request won't change.
        - An unparseable (non-JSON) 200 body -- **not** retried: this session never actually
          observed this failure mode (every flip observed was status/connectivity-level, not
          a malformed success body), and retrying a response that was already a 200 is a
          materially different risk profile than retrying a connection/5xx failure -- see
          this task's `decisions` entry.

        See this task's own `decisions` entry for the full policy rationale (why a single
        retry, why this exact delay, why this exact retryable/non-retryable split).
        """
        url = f"{self._base_url}{path}"
        attempt = 1
        while True:
            try:
                response = self._client.request(method, url, **kwargs)  # type: ignore[arg-type]
            except httpx.RequestError as exc:
                if isinstance(exc, httpx.TimeoutException) or attempt >= _REQUEST_MAX_ATTEMPTS:
                    raise IBKRUnavailableError(f"IBKR gateway request to {path} failed: {exc}") from exc
                attempt += 1
                self._sleep(_REQUEST_RETRY_DELAY_SECONDS)
                continue

            if response.status_code != 200:
                if response.status_code < 500 or attempt >= _REQUEST_MAX_ATTEMPTS:
                    raise IBKRUnavailableError(f"IBKR gateway returned HTTP {response.status_code} from {path}")
                attempt += 1
                self._sleep(_REQUEST_RETRY_DELAY_SECONDS)
                continue

            try:
                return response.json()
            except ValueError as exc:
                raise IBKRUnavailableError(
                    f"IBKR gateway returned an unparseable response from {path}: {exc}"
                ) from exc


def _parse_bars(payload: object) -> list[IBKRBar]:
    """`{"data": [{"t": epoch_ms, "o":.., "h":.., "l":.., "c":.., "v":..}, ...], ...}` per
    docs/ideas.md's documented `/iserver/marketdata/history` shape. A malformed individual
    bar row is skipped rather than failing the whole page -- an isolated bad row
    shouldn't discard every other, valid bar in the same response.
    """
    if not isinstance(payload, dict):
        return []
    raw_bars = payload.get("data") or []
    bars: list[IBKRBar] = []
    for raw in raw_bars:
        if not isinstance(raw, dict):
            continue
        try:
            bars.append(
                IBKRBar(
                    timestamp=datetime.fromtimestamp(float(raw["t"]) / 1000, tz=UTC),
                    open=float(raw["o"]),
                    high=float(raw["h"]),
                    low=float(raw["l"]),
                    close=float(raw["c"]),
                    volume=float(raw["v"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return bars


def _parse_scanner_results(payload: object) -> list[ScannerResult]:
    """`{"contracts": [{"con_id":.., "symbol":.., "company_name":.., "rank":..}, ...]}` --
    a live gateway's actual field names (snake_case `con_id`/`company_name`), confirmed
    against a real running gateway; docs/ideas.md's documented shape had guessed
    camelCase (`conid`/`companyName`, unverified until now -- see this module's own
    "Testing constraint" docstring paragraph), which silently dropped every single result
    (every row's `conid` lookup came back `None`, hitting the "missing conid" skip branch
    below) rather than erroring, since a live gateway was never exercised until a user hit
    this in practice. `rank` isn't present in the confirmed live payload at all -- IBKR's
    own scan-result ordering is implicit in list order, not a per-row field -- so this
    stays `None` for every real result today; kept as a lookup (rather than removed
    outright) since `IBKRScannerResultOut.rank`'s own field description already documents
    it as "if the gateway supplied one" -- a gateway response or scan category that does
    include it degrades correctly with no further code change needed.

    Same skip-malformed-rows behavior as `_parse_bars`, except a missing/malformed
    `con_id` drops the whole row (there's no meaningful scanner result without one to key
    it by)."""
    if not isinstance(payload, dict):
        return []
    raw_contracts = payload.get("contracts") or []
    results: list[ScannerResult] = []
    for raw in raw_contracts:
        if not isinstance(raw, dict):
            continue
        conid = raw.get("con_id")
        if conid is None:
            continue
        try:
            conid_int = int(conid)
        except (TypeError, ValueError):
            continue
        results.append(
            ScannerResult(
                conid=conid_int,
                symbol=raw.get("symbol"),
                company_name=raw.get("company_name"),
                rank=_int_or_none(raw.get("rank")),
            )
        )
    return results


def _parse_account_positions(payload: object) -> list[IBKRAccountPosition]:
    """One page of `GET /portfolio/{accountId}/positions/{pageId}`, documented (this
    task's `decisions` entry) as a plain JSON array, one entry per held position, roughly
    `{"conid": 265598, "contractDesc": "AAPL", "position": 100.0, "avgCost": 130.5,
    "assetClass": "STK", ...}` -- alongside many other fields (market value, currency,
    exchange, sector, etc.) this app has no use for and doesn't model, matching
    `ScannerResult`'s own "model only what's needed" precedent.

    Ticker resolution (this task's own `decisions` entry): `contractDesc` is the field
    IBKR's own documented example response for this exact endpoint shows, and for a
    `"STK"`-asset-class row it's simply the plain ticker symbol (unlike a derivative row,
    where `contractDesc` also encodes strike/expiry) -- so `contractDesc` is used as-is,
    uppercased to match this app's own ticker-normalization convention
    (`app.api.routers.portfolio.add_position`'s `ticker.upper()`), for exactly the rows
    whose `assetClass` is `"STK"`. Every other `assetClass` (options, futures, warrants,
    cash, etc.) is dropped outright -- this app's portfolio model has no representation
    for a derivative position, and a `"STK"`-only filter mirrors `_resolve_stk_conid`'s
    own equity-only scope in this same module.

    A row is also dropped if `position` (the field name IBKR's docs use for share
    quantity, not `quantity`) is missing, non-numeric, non-finite, or not strictly
    positive (a flat/closed-out or short position) -- this app's `PositionORM.quantity`/
    `PositionIn.quantity` are always positive, so a non-positive IBKR position has no
    valid representation here (see this task's `decisions` entry for why short positions
    are out of scope). `avgCost` is kept independently nullable -- a missing/non-numeric
    `avgCost` doesn't drop the row (see `IBKRAccountPosition`'s own docstring for why),
    it just leaves `avg_cost` as `None`.

    A malformed individual row (not a dict, missing/non-numeric `conid`) is skipped
    rather than failing the whole page, same convention as `_parse_bars`/
    `_parse_scanner_results`.
    """
    if not isinstance(payload, list):
        return []
    positions: list[IBKRAccountPosition] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        if raw.get("assetClass") != "STK":
            continue
        conid = _int_or_none(raw.get("conid"))
        if conid is None:
            continue
        contract_desc = raw.get("contractDesc")
        if not isinstance(contract_desc, str) or not contract_desc.strip():
            continue
        quantity = _float_or_none(raw.get("position"))
        if quantity is None or quantity <= 0:
            continue
        positions.append(
            IBKRAccountPosition(
                conid=conid,
                ticker=contract_desc.strip().upper(),
                quantity=quantity,
                avg_cost=_float_or_none(raw.get("avgCost")),
            )
        )
    return positions


def _resolve_stk_conid(payload: object, ticker: str) -> int | None:
    """`[{"conid": "265598", "symbol": "AAPL", "description": "NASDAQ",
    "sections": [{"secType": "STK"}, ...], ...}, ...]` per `/iserver/secdef/search`'s
    documented shape (this task's `decisions` entry) -- a list of candidate contracts,
    each potentially covering several asset classes (`sections`) tied to the same
    underlying. Keeps only entries whose `symbol` matches `ticker` exactly
    (case-insensitive) and which include a `"STK"` section (skipping symbol matches that
    only exist as options/warrants/futures, and fuzzy partial-symbol matches the endpoint
    can also return).

    Returns the single resulting conid; if more than one distinct candidate remains,
    prefers the one listed on a primary US exchange (`_US_PRIMARY_EXCHANGES`, keyed off
    each candidate's own top-level `description` field) before giving up -- see that
    constant's own comment and `IBKRProvider.resolve_conid`'s docstring for the live
    research this is based on and why a still-ambiguous result degrades to `None` rather
    than raising or guessing further.

    `candidates` is keyed by conid (duplicate rows for the same conid -- one row per
    derivative-bearing section returned as separate entries, see
    `test_duplicate_rows_for_the_same_conid_are_not_ambiguous` -- are not genuine
    ambiguity), so a conid seen more than once keeps the first non-null `description` it
    was given rather than letting a later row's value silently overwrite it: a later
    duplicate with a *null* description never clobbers an already-known one, and if two
    duplicate rows for the same conid ever disagreed on a non-null `description` (not
    observed live -- every live-tested duplicate-conid ticker's rows agreed -- but not
    structurally ruled out by IBKR's documented response shape either), the first one
    encountered wins rather than this candidate's primary-exchange-match outcome
    silently depending on `/iserver/secdef/search`'s own row order. See
    `backend-ibkr-primary-data-provider-followups`'s checklist for the finding this
    closes.
    """
    if not isinstance(payload, list):
        return None
    ticker_upper = ticker.upper()
    candidates: dict[int, str | None] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        symbol = raw.get("symbol")
        if not isinstance(symbol, str) or symbol.upper() != ticker_upper:
            continue
        sections = raw.get("sections") or []
        if not isinstance(sections, list):
            continue
        if not any(isinstance(section, dict) and section.get("secType") == "STK" for section in sections):
            continue
        conid = _int_or_none(raw.get("conid"))
        if conid is None:
            continue
        description = raw.get("description")
        description = description if isinstance(description, str) else None
        if conid not in candidates or candidates[conid] is None:
            candidates[conid] = description
    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) > 1:
        primary_listings = {
            conid for conid, description in candidates.items() if description in _US_PRIMARY_EXCHANGES
        }
        if len(primary_listings) == 1:
            return next(iter(primary_listings))
    return None


def _int_or_none(value: int | float | str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    """Like `_int_or_none`, but for a field that's genuinely fractional (`position`,
    `avgCost`) rather than an id -- also rejects a non-finite result (`inf`/`nan`), which
    `float(...)` itself would otherwise happily accept from a malformed string like
    `"nan"`, since a non-finite quantity/cost has no valid meaning here."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed
