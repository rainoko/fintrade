import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from app.data.base import DataProvider, ExtendedData, InsiderTransaction
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)

# Screen 1 needs at least 26 weeks of history to seed the 26-week EMA
# (docs/Analyse.md §8: "minimum ~200 trading days, to seed 26-week/weekly
# EMA & MACD"). Checked only on the weekly series -- see this task's
# `decisions` entry for why.
_MIN_WEEKLY_BARS = 26

# yfinance's raw column names -> the DataProvider protocol's contract
# (app/data/base.py: "Columns: open, high, low, close, volume").
_COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}

# Per-request timeout budget (seconds) for every outbound HTTP call this provider makes
# through yfinance -- see docs/tasks/backend-data-provider-timeouts.json's `decisions` entry
# for the full trade-off. `.history()` (used by `_fetch`) accepts a `timeout=` kwarg directly;
# `.calendar`/`.info`/`.insider_transactions` (used by `get_extended_data`) don't expose an
# equivalent per-call kwarg in the installed yfinance version, so `_clamp_session_timeout`
# below enforces the same cap at the underlying HTTP session instead. Matches
# `StooqProvider`'s existing `timeout=10` (stooq_provider.py's `_fetch_csv`) for a consistent
# per-request budget across both data sources.
_REQUEST_TIMEOUT_SECONDS = 10.0

_session_clamp_lock = threading.Lock()


def _clamp_session_timeout(session: object) -> None:
    """Cap every request `session` makes at `_REQUEST_TIMEOUT_SECONDS`, in place.

    yfinance's `YfData` (the object that actually issues every HTTP request) is a
    process-wide singleton holding one shared session, built with yfinance's own internal
    default (30s -- `yfinance/data.py`'s `get`/`get_raw_json`/`post`) unless overridden. But
    `Ticker.calendar`/`.info`/`.insider_transactions` (used by `get_extended_data` below) give
    callers no way to override that default per call, unlike `.history()`'s own `timeout=`
    kwarg (see `_fetch`) -- confirmed by reading the installed yfinance package's own
    `scrapers/quote.py`/`ticker.py`: those three are plain properties with no `timeout=`
    parameter of their own. Three sequential 30s-capped property fetches inside one
    `get_extended_data` call is exactly the ~90s stack this task's own incident report
    describes, so this closes that gap by capping the shared session directly instead.

    Deliberately does *not* build a brand-new from-scratch session (e.g. a bare
    `requests.Session()`) to enforce this: yfinance prefers `curl_cffi` for Yahoo-compatible
    TLS/browser fingerprinting (`yfinance._http.new_session`) specifically to reduce the risk
    of exactly the rate-limiting/blocking this task exists to mitigate, and replacing the
    session wholesale would silently drop that fingerprinting. This instead reaches into the
    session yfinance already built for itself (`Ticker._data._session`) and wraps its
    `.request` method in place, so the same curl_cffi (or plain-`requests`-fallback) session
    keeps handling everything else about the request.

    Best-effort: if yfinance's internal attribute shape ever changes, this silently no-ops
    (via `getattr`/`AttributeError`, never raised) rather than breaking every fetch --
    `.history()`'s own inline `timeout=` still applies either way, so `get_daily_ohlcv`/
    `get_weekly_ohlcv` keep their protection even if this particular clamp can't attach.

    Idempotent (checked via a marker attribute) and lock-guarded so two concurrent callers --
    e.g. `app.api.routers.stocks.get_analysis`'s concurrent daily/weekly/extended fetch, see
    this task's `decisions` entry -- can't race to double-wrap the one process-wide session.
    """
    if getattr(session, "_fintrade_timeout_clamped", False):
        return
    with _session_clamp_lock:
        if getattr(session, "_fintrade_timeout_clamped", False):
            return
        try:
            original_request = session.request  # type: ignore[attr-defined]
        except AttributeError:
            return

        def _request_with_timeout(method: object, url: object, *args: object, **kwargs: object) -> object:
            requested = kwargs.get("timeout")
            kwargs["timeout"] = (
                _REQUEST_TIMEOUT_SECONDS
                if requested is None
                else min(float(requested), _REQUEST_TIMEOUT_SECONDS)  # type: ignore[arg-type]
            )
            return original_request(method, url, *args, **kwargs)

        try:
            session.request = _request_with_timeout  # type: ignore[attr-defined]
            session._fintrade_timeout_clamped = True  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - best-effort, see docstring above
            pass


def _new_ticker(ticker: str) -> yf.Ticker:
    """`yf.Ticker(ticker)`, with `_clamp_session_timeout` applied to its underlying session.

    Both `YFinanceProvider._fetch` and `get_extended_data` construct their `yf.Ticker` through
    this helper rather than calling `yf.Ticker(...)` directly, so the clamp is applied
    consistently everywhere this provider talks to yfinance.
    """
    yf_ticker = yf.Ticker(ticker)
    session = getattr(getattr(yf_ticker, "_data", None), "_session", None)
    if session is not None:
        _clamp_session_timeout(session)
    return yf_ticker


class YFinanceProvider(DataProvider):
    """Primary market data source — free, no API key (docs/Analyse.md §9)."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV bars for `ticker`, full available history.

        Raises:
            TickerNotFoundError: yfinance returned no data at all for `ticker`.
            DataProviderUnavailableError: yfinance itself failed (rate limit,
                network error, unexpected response).
        """
        return self._fetch(ticker, interval="1d")

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Weekly OHLCV bars for `ticker`, using yfinance's native weekly
        interval (``interval="1wk"``) rather than a manual resample of daily
        bars (docs/Analyse.md §9).

        Raises:
            TickerNotFoundError: yfinance returned no data at all for `ticker`.
            InsufficientHistoryError: fewer than `_MIN_WEEKLY_BARS` weekly bars
                are available (e.g. a recent IPO).
            DataProviderUnavailableError: yfinance itself failed (rate limit,
                network error, unexpected response).
        """
        df = self._fetch(ticker, interval="1wk")
        if len(df) < _MIN_WEEKLY_BARS:
            raise InsufficientHistoryError(ticker, available=len(df), required=_MIN_WEEKLY_BARS)
        return df

    def get_extended_data(self, ticker: str) -> ExtendedData:
        """Earnings/dividend dates (`Ticker.calendar`), short interest (`Ticker.info`), and
        recent insider transactions (`Ticker.insider_transactions`) for `ticker` --
        docs/ideas.md's confirmed-live-in-yfinance fields (Elder ch. 37/53/58).

        Raises:
            DataProviderUnavailableError: yfinance itself failed (rate limit, network error,
                unexpected response) on any of the three underlying calls -- caught as one
                unit since they're all part of the same "extended data" fetch, unlike
                `get_daily_ohlcv`/`get_weekly_ohlcv` which callers fetch independently.

        Individual fields are `None`/empty when yfinance itself succeeded but simply has no
        value for this ticker (e.g. a smaller/thinly-covered company with no reported short
        interest, docs/ideas.md's own "yfinance's own data can be incomplete for smaller
        tickers" caveat) -- distinct from the provider-level failure above, which raises
        rather than returning a half-populated result.

        The three underlying property fetches (`.calendar`/`.info`/`.insider_transactions`)
        are fetched concurrently, not sequentially: none of the three depends on either of
        the others, so a slow/degraded session (each still capped at
        `_REQUEST_TIMEOUT_SECONDS` via `_clamp_session_timeout`) now costs its timeout budget
        once per call here instead of up to three times over -- the same "sequential calls
        stacking" mechanism `app.api.routers.stocks.get_analysis`'s own daily/weekly/extended
        concurrent fetch addresses one level up (backend-data-provider-timeouts), just applied
        one level down. See docs/tasks/backend-data-provider-timeouts-followups.json's
        `decisions` entry for why this doesn't need that same call site's per-leg-scoped-
        `DataProvider`/`Session` pattern: unlike `get_analysis`, nothing here owns a `Session`
        an abandoned leg could race against, so a plain fail-fast `ThreadPoolExecutor` (manual
        `shutdown(wait=False, cancel_futures=True)`, not the `with ThreadPoolExecutor(...) as
        executor:` form -- see that same call site's own comment for why the context-manager
        form's implicit `shutdown(wait=True)` would delay a fast failure by however long the
        slowest of the other two legs takes) is sufficient on its own.
        """
        try:
            yf_ticker = _new_ticker(ticker)
            executor = ThreadPoolExecutor(max_workers=3)
            try:
                calendar_future = executor.submit(lambda: yf_ticker.calendar or {})
                info_future = executor.submit(lambda: yf_ticker.info or {})
                insider_future = executor.submit(lambda: yf_ticker.insider_transactions)
                calendar = calendar_future.result()
                info = info_future.result()
                insider_df = insider_future.result()
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except YFRateLimitError as exc:
            raise DataProviderUnavailableError(f"yfinance rate-limited: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - yfinance's own errors are broad/undocumented
            raise DataProviderUnavailableError(f"yfinance request failed: {exc}") from exc

        # `Ticker.calendar`'s "Earnings Date" is a list -- Yahoo sometimes reports an
        # unconfirmed 2-day estimate window rather than a single confirmed date -- so the
        # earliest entry is used as the single date this app surfaces (see this task's
        # `decisions` entry for why the window's upper bound isn't also exposed).
        earnings_dates = calendar.get("Earnings Date") or []
        earnings_date = min(earnings_dates) if earnings_dates else None

        return ExtendedData(
            earnings_date=earnings_date,
            ex_dividend_date=calendar.get("Ex-Dividend Date"),
            shares_short=_int_or_none(info.get("sharesShort")),
            short_ratio=_float_or_none(info.get("shortRatio")),
            short_percent_of_float=_float_or_none(info.get("shortPercentOfFloat")),
            float_shares=_int_or_none(info.get("floatShares")),
            insider_transactions=_parse_insider_transactions(insider_df),
        )

    def _fetch(self, ticker: str, *, interval: str) -> pd.DataFrame:
        """Fetch and normalize one interval's worth of bars for `ticker`.

        Requests the full available history (``period="max"``): the
        `DataProvider` protocol takes no date-range argument, so trimming to
        whatever window a caller actually wants (the API's `range` query
        param, the SQLite cache) is that caller's job, not this adapter's.
        """
        try:
            raw = _new_ticker(ticker).history(
                period="max", interval=interval, timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except YFRateLimitError as exc:
            raise DataProviderUnavailableError(f"yfinance rate-limited: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - yfinance's own errors are broad/undocumented
            raise DataProviderUnavailableError(f"yfinance request failed: {exc}") from exc

        if raw.empty:
            # yfinance's default (non-raising) mode swallows unknown-ticker,
            # delisted-ticker, and "no price data for this range" cases alike
            # into a silently-returned empty DataFrame — this is the one
            # signal available to distinguish "no such ticker" without
            # depending on yfinance's internal logging/exception details.
            raise TickerNotFoundError(ticker)

        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.rename(columns=_COLUMN_MAP)[list(_COLUMN_MAP.values())].copy()
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df.index.name = "date"
        return df


def _int_or_none(value: int | float | str | None) -> int | None:
    """`Ticker.info` uses plain `None` for a genuinely missing key, but a present-but-NaN
    float for some fields yfinance still populates from an incomplete upstream record --
    both must map to `None` here rather than a Pydantic-rejecting `nan`."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return int(value)


def _float_or_none(value: int | float | str | None) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)


def _str_or_none(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _parse_insider_transactions(raw: pd.DataFrame | None) -> list[InsiderTransaction]:
    """`Ticker.insider_transactions` columns (yfinance's `Holders._parse_insider_transactions`):
    `Insider`, `Position`, `Transaction`, `Text`, `Shares`, `Value`, `Start Date`, `Ownership`.
    `None`/an empty frame (no filings reported, or yfinance's own request failure swallowed
    internally rather than raised -- see this method's own docstring) both map to `[]`, not an
    error: an empty list is this app's normal "nothing to report" representation, distinct
    from `ExtendedData.unavailable_reason`'s "not supported by this provider at all"."""
    if raw is None or raw.empty:
        return []
    transactions: list[InsiderTransaction] = []
    for _, row in raw.iterrows():
        start_date_raw = row.get("Start Date")
        transactions.append(
            InsiderTransaction(
                insider=_str_or_none(row.get("Insider")),
                position=_str_or_none(row.get("Position")),
                transaction_text=_str_or_none(row.get("Text")) or "",
                shares=_float_or_none(row.get("Shares")),
                value=_float_or_none(row.get("Value")),
                start_date=(
                    start_date_raw.date() if hasattr(start_date_raw, "date") else None
                ),
                ownership=_str_or_none(row.get("Ownership")),
            )
        )
    return transactions
