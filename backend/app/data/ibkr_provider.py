"""Optional IBKR Client Portal Web API provider (docs/tasks/backend-ibkr-data-provider.json,
docs/ideas.md's "Decided: add IBKR's Client Portal Web API" entry).

Unlike ``YFinanceProvider``/``StooqProvider`` (app/data/yfinance_provider.py,
app/data/stooq_provider.py), ``IBKRProvider`` deliberately does **not** implement the
``DataProvider`` protocol (app/data/base.py) -- its capabilities (hourly bars for one
IBKR contract ID, a market-breadth scanner) don't map onto that protocol's
``get_daily_ohlcv``/``get_weekly_ohlcv``/``get_extended_data`` shape at all, and forcing
a fit (e.g. resampling hourly bars into a fake "daily" series, or returning scanner
results through a method named for per-ticker OHLCV) would misrepresent what this
provider actually does. It's a distinct, secondary, fully optional capability -- see
this task's `decisions` entry for the full rationale.

**Structural constraint this whole module is designed around** (this task's own
`description`): the gateway is a persistent local process (`clientportal.gw`) that
requires a one-time interactive browser login IBKR explicitly does not support
automating, and the session must be kept alive with a periodic ``/tickle`` call. That
makes it a poor fit as this app's *primary* data source (unlike `YFinanceProvider`'s
always-on, no-login-step nature) -- it's used only for the specific extra capabilities
it uniquely unlocks, and degrades gracefully (a typed `GatewayStatus`, never an opaque
exception) whenever the gateway isn't running or isn't authenticated. See
`docs/architecture/Backend.md`'s IBKR section for the human setup walkthrough
(downloading/running the gateway, the browser login step, `FINTRADE_IBKR_ENABLED`).

**Testing constraint** (also this task's own `description`): no sandboxed/CI environment
has a live authenticated gateway to test against, so every test in
tests/unit/data/test_ibkr_provider.py mocks HTTP at the ``_request`` boundary against the
documented Web API request/response shapes -- this task's `decisions` entry records that
live-gateway behavior (the actual response shapes, the interactive login flow, and any
undocumented quirks) is unverified here and deferred to manual testing by the user
against a real running gateway.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx

# IBKR's own default: the gateway listens locally, over HTTPS with a self-signed cert
# (hence `verify=False` on the client below -- there's no real TLS trust chain to check
# against a `localhost` gateway process, and IBKR's own docs have users click through the
# browser warning for the same reason).
DEFAULT_BASE_URL = "https://localhost:5000/v1/api"

# docs/ideas.md: "max 1,000 data points per call" on /iserver/marketdata/history.
_MAX_BARS_PER_PAGE = 1000

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

# docs/ideas.md: "`params` is rate-limited to 1 request per 15 minutes (cache it)".
_SCANNER_PARAMS_TTL_SECONDS = 15 * 60.0

# docs/ideas.md: "`run` to 1 request per second".
_SCANNER_RUN_MIN_INTERVAL_SECONDS = 1.0

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
    ) -> None:
        """`client` and `clock` are injectable purely for testability (per this task's
        mocked-HTTP-only testing constraint) -- production callers should leave both at
        their defaults. `clock` uses `time.monotonic` (not wall-clock time) since it only
        ever measures elapsed intervals for the two rate limits, never an absolute
        timestamp; a test can inject a simple counter instead of a real clock to make
        rate-limit behavior deterministic without sleeping.
        """
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(verify=False, timeout=timeout)
        self._owns_client = client is None
        self._clock = clock
        self._scanner_params_cache: tuple[float, dict] | None = None
        self._last_scanner_run_at: float | None = None

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
        """
        try:
            payload = self._request("GET", "/iserver/auth/status")
        except IBKRUnavailableError as exc:
            return GatewayStatus(state="gateway_unreachable", detail=str(exc))

        if not isinstance(payload, dict) or not payload.get("authenticated"):
            detail = payload.get("message") if isinstance(payload, dict) else None
            return GatewayStatus(state="not_authenticated", detail=detail)
        return GatewayStatus(state="available")

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

        Returns `None` -- never raises -- for both a **no-match** ticker and a
        genuinely **ambiguous** one (more than one distinct stock conid for the same
        symbol, e.g. the same ticker used by unrelated companies listed on different
        exchanges): silently guessing among several candidate contracts risks resolving
        to the wrong instrument entirely, which is worse than surfacing "could not
        resolve automatically" and asking a human to supply a conid directly instead.
        See this task's `decisions` entry.

        Raises:
            IBKRUnavailableError: the gateway isn't `available` (see
                `get_gateway_status`), or the request itself fails.
        """
        self._require_available()
        payload = self._request("GET", "/iserver/secdef/search", params={"symbol": ticker})
        return _resolve_stk_conid(payload, ticker)

    def _require_available(self) -> None:
        status = self.get_gateway_status()
        if status.state != "available":
            raise IBKRUnavailableError(f"IBKR gateway not available ({status.state}): {status.detail}")

    def _request(self, method: str, path: str, **kwargs: object) -> dict | list:
        """The one method that performs a real HTTP call against the gateway -- every
        other method on this class goes through this, so tests mock this single boundary
        (per docs/architecture/Testing.md, matching `StooqProvider._fetch_csv`'s role in
        that provider) rather than the `httpx.Client` internals.
        """
        url = f"{self._base_url}{path}"
        try:
            response = self._client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.RequestError as exc:
            raise IBKRUnavailableError(f"IBKR gateway request to {path} failed: {exc}") from exc

        if response.status_code != 200:
            raise IBKRUnavailableError(f"IBKR gateway returned HTTP {response.status_code} from {path}")

        try:
            return response.json()
        except ValueError as exc:
            raise IBKRUnavailableError(f"IBKR gateway returned an unparseable response from {path}: {exc}") from exc


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
    """`{"contracts": [{"conid":.., "symbol":.., "companyName":.., "rank":..}, ...]}` per
    docs/ideas.md's documented `/iserver/scanner/run` shape. Same skip-malformed-rows
    behavior as `_parse_bars`, except a missing/malformed `conid` drops the whole row
    (there's no meaningful scanner result without one to key it by)."""
    if not isinstance(payload, dict):
        return []
    raw_contracts = payload.get("contracts") or []
    results: list[ScannerResult] = []
    for raw in raw_contracts:
        if not isinstance(raw, dict):
            continue
        conid = raw.get("conid")
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
                company_name=raw.get("companyName"),
                rank=_int_or_none(raw.get("rank")),
            )
        )
    return results


def _resolve_stk_conid(payload: object, ticker: str) -> int | None:
    """`[{"conid": "265598", "symbol": "AAPL", "sections": [{"secType": "STK"}, ...],
    ...}, ...]` per `/iserver/secdef/search`'s documented shape (this task's `decisions`
    entry) -- a list of candidate contracts, each potentially covering several asset
    classes (`sections`) tied to the same underlying. Keeps only entries whose `symbol`
    matches `ticker` exactly (case-insensitive) and which include a `"STK"` section
    (skipping symbol matches that only exist as options/warrants/futures, and fuzzy
    partial-symbol matches the endpoint can also return). Returns the single resulting
    conid, or `None` if that leaves zero or more than one distinct candidate -- see
    `IBKRProvider.resolve_conid`'s own docstring for why both degrade to the same `None`
    rather than raising or guessing.
    """
    if not isinstance(payload, list):
        return None
    ticker_upper = ticker.upper()
    candidates: set[int] = set()
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
        if conid is not None:
            candidates.add(conid)
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def _int_or_none(value: int | float | str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
