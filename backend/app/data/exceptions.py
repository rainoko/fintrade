"""Typed exceptions raised by market data provider adapters (app/data/*_provider.py).

The API layer maps these to HTTP responses per CLAUDE.md's API documentation
standard (every documented error case declared in a route's ``responses={}``):

- ``TickerNotFoundError``          -> 404
- ``InsufficientHistoryError``     -> 422
- ``DataProviderUnavailableError`` -> 503

See the `decisions` entry on docs/tasks/data-provider-stooq.json for why this
module exists here rather than only in the (at the time, not-yet-merged)
data-provider-yfinance task — the two should be identical, and whichever PR
merges second should simply drop its own copy in favor of the other's.
"""


class DataProviderError(Exception):
    """Base class for every error a `DataProvider` implementation can raise.

    Lets calling code (the API layer, the cache, other providers) catch
    "any provider failure" with one `except DataProviderError` when it
    doesn't need to distinguish the specific cause.
    """


class TickerNotFoundError(DataProviderError):
    """Raised when the provider has no data at all for `ticker`.

    Covers both an actually-unknown/mistyped symbol and a delisted one —
    yfinance's default (non-raising) mode doesn't reliably distinguish the
    two, it just returns an empty result either way, so neither does this
    exception. Maps to HTTP 404 in the API layer.
    """

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        super().__init__(f"Unknown ticker: {ticker!r}")


class InsufficientHistoryError(DataProviderError):
    """Raised when a (real, found) ticker has fewer bars than required.

    E.g. a recent IPO with less than the 26 weeks of history Screen 1 needs
    to seed its 26-week EMA (docs/Analyse.md §8). Maps to HTTP 422 in the
    API layer.
    """

    def __init__(self, ticker: str, *, available: int, required: int) -> None:
        self.ticker = ticker
        self.available = available
        self.required = required
        super().__init__(
            f"{ticker}: insufficient history ({available} bars available, {required} required)"
        )


class DataProviderUnavailableError(DataProviderError):
    """Raised when the upstream provider itself is unreachable or refusing requests
    (rate-limited, network failure, unexpected response shape) — as opposed to a
    per-ticker problem. Maps to HTTP 503 in the API layer.
    """
