import io
import urllib.request

import pandas as pd

from app.data.base import DataProvider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)

_BASE_URL = "https://stooq.com/q/d/l/"

# Screen 1 needs at least 26 weeks of history to seed the 26-week EMA
# (docs/Analyse.md §8). Matches YFinanceProvider's threshold/placement (see
# this task's `decisions` entry) -- checked only on the weekly series.
_MIN_WEEKLY_BARS = 26

# Stooq's raw CSV column names -> the DataProvider protocol's contract
# (app/data/base.py: "Columns: open, high, low, close, volume").
_COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}

# Stooq's CSV endpoint returns the literal body "No data" (no CSV header at
# all) for an unknown/delisted symbol, rather than an HTTP error status.
_NO_DATA_BODY = "No data"


class StooqProvider(DataProvider):
    """Fallback market data source, used when the yfinance provider fails or rate-limits (docs/Analyse.md §9)."""

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV bars for `ticker`, full available history from Stooq's
        plain CSV endpoint (``stooq.com/q/d/l/?s=TICKER&i=d``).

        Raises:
            TickerNotFoundError: Stooq returned no data for `ticker`.
            DataProviderUnavailableError: the Stooq request itself failed
                (network error, unexpected response).
        """
        return self._fetch_daily(ticker)

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        """Weekly OHLCV bars for `ticker`, resampled from daily bars.

        Stooq's CSV endpoint has no native weekly interval usable here (see
        this task's `decisions` entry), so weekly bars are derived by
        resampling the daily series into Friday-ending weeks
        (open=first, high=max, low=min, close=last, volume=sum).

        Raises:
            TickerNotFoundError: Stooq returned no data for `ticker`.
            InsufficientHistoryError: fewer than `_MIN_WEEKLY_BARS` weekly
                bars result from the resample (e.g. a recent IPO).
            DataProviderUnavailableError: the Stooq request itself failed
                (network error, unexpected response).
        """
        daily = self._fetch_daily(ticker)
        weekly = self._resample_weekly(daily)
        if len(weekly) < _MIN_WEEKLY_BARS:
            raise InsufficientHistoryError(ticker, available=len(weekly), required=_MIN_WEEKLY_BARS)
        return weekly

    def _fetch_daily(self, ticker: str) -> pd.DataFrame:
        url = f"{_BASE_URL}?s={self._to_stooq_symbol(ticker)}&i=d"
        try:
            text = self._fetch_csv(url)
        except Exception as exc:  # noqa: BLE001 - any transport failure is a provider-availability problem
            raise DataProviderUnavailableError(f"Stooq request failed: {exc}") from exc

        if text.strip() == _NO_DATA_BODY:
            raise TickerNotFoundError(ticker)

        try:
            raw = pd.read_csv(io.StringIO(text))
        except Exception as exc:  # noqa: BLE001 - malformed body is a provider-availability problem, not a 404
            raise DataProviderUnavailableError(f"Stooq returned an unparseable response: {exc}") from exc

        if raw.empty:
            # Belt-and-braces alongside the "No data" body check above: an
            # unexpected header-only response should still read as "no such
            # ticker" rather than silently returning zero rows.
            raise TickerNotFoundError(ticker)

        return self._normalize(raw)

    def _fetch_csv(self, url: str) -> str:
        """Perform the actual HTTP GET against Stooq. Isolated in its own method
        so tests can mock this one boundary rather than urllib internals.
        """
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed https host, not user input
            return response.read().decode("utf-8")

    @staticmethod
    def _to_stooq_symbol(ticker: str) -> str:
        """Stooq requires a market suffix (e.g. ``aapl.us``) on its symbols; a
        bare ticker like ``AAPL`` is assumed to be a US equity, matching the
        default market YFinanceProvider is used for in this project.

        A ``.`` in the input ticker isn't necessarily an existing market
        suffix -- Stooq (and yfinance) use a hyphen, not a dot, for
        class-share tickers (``BRK.B`` -> ``brk-b``), so a dotted class-share
        ticker must still get the ``.us`` suffix appended after its dot is
        converted to a hyphen. A trailing ``.us`` is stripped first (rather
        than short-circuited on with an early return) so a combined,
        already-suffixed class-share input like ``BRK.B.US`` still gets its
        remaining dot hyphenated before ``.us`` is reappended, producing
        ``brk-b.us`` rather than passing the whole thing through as the
        invalid ``brk.b.us``.

        ``.us`` is the only market suffix this method recognizes, since this
        provider only ever targets US equities (docs/Analyse.md §9) --
        yfinance (this project's primary provider) is used for that same
        default market, and Stooq is only ever consulted as its fallback
        (docs/architecture/Backend.md §2). An already-suffixed non-US ticker
        such as ``SAP.DE`` is therefore *not* recognized as pre-qualified and
        still gets its dot hyphenated and ``.us`` appended (``sap-de.us``),
        which is not a symbol Stooq recognizes -- a deliberate, documented
        gap rather than a bug, since there's no reliable way to distinguish a
        genuine non-US market suffix from a single-letter class-share dot
        (e.g. ``BRK.B``) without a country-code allowlist this app has no
        other use for (see this task's `decisions` entry, and
        data-provider-stooq-followups's own decisions entry for the same
        tradeoff on the class-share-vs-suffix ambiguity). Callers must only
        pass this provider US-equity tickers.
        """
        symbol = ticker.strip().lower()
        if symbol.endswith(".us"):
            symbol = symbol[: -len(".us")]
        return f"{symbol.replace('.', '-')}.us"

    @staticmethod
    def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.rename(columns=_COLUMN_MAP)
        df["date"] = pd.to_datetime(df["Date"])
        df = df.set_index("date")[list(_COLUMN_MAP.values())].sort_index()
        return df

    @staticmethod
    def _resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
        weekly = daily.resample("W-FRI").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        weekly = weekly.dropna(subset=["open", "high", "low", "close"])
        weekly.index.name = "date"
        return weekly
