"""Deterministic, no-network `DataProvider` used only by the frontend e2e test suite
(``frontend/tests/e2e/``, run via ``npm run test:e2e``), selected via
``FINTRADE_DATA_PROVIDER_MODE=fixture`` (see ``app.config.Settings.data_provider_mode`` and
``app.api.dependencies.get_data_provider``).

Never reached by the live app's default config, and never used by the backend pytest suite
either -- that suite mocks/stubs the `DataProvider` protocol directly per test (see e.g.
tests/integration/test_stocks_analysis.py's `_StubProvider`), matching
docs/architecture/Testing.md's existing "no live network calls in any test" pattern. This
class exists purely so the *separate*, real-stack e2e suite (frontend-e2e-tests task) has
somewhere offline and repeatable to point the running backend at, instead of either hitting
real yfinance/Stooq (flaky, rate-limited, requires internet, non-deterministic signal output)
or requiring e2e specs to duplicate the pytest suite's per-request mocking against a live
server process they don't control. See docs/tasks/frontend-e2e-tests.json's `decisions` entry.
"""

import random
from dataclasses import dataclass

import pandas as pd

from app.data.base import DataProvider
from app.data.exceptions import InsufficientHistoryError, TickerNotFoundError

# Mirrors YFinanceProvider/StooqProvider's own _MIN_WEEKLY_BARS (Analyse.md §8: Screen 1
# needs 26 weeks of history to seed its 26-week EMA) -- kept as a local constant (not
# imported) since none of these three provider modules otherwise depend on each other.
_MIN_WEEKLY_BARS = 26

# 420 business days (~84 weeks after a weekly resample) comfortably clears
# _MIN_WEEKLY_BARS and every daily-side indicator's own warm-up window (MACD, Stochastic,
# Force Index, Elder-Ray, Autoenvelope -- all well under 100 bars), with headroom for the
# frontend's own history-range presets (PriceChart.tsx's '1y'/'max' options) to have
# something to show at every zoom level.
_NUM_DAILY_BARS = 420


@dataclass(frozen=True)
class _SeriesSpec:
    start_price: float
    # Deterministic per-day price change driving the series' overall trend direction.
    drift_per_day: float
    # Bounded pseudo-random day-to-day wiggle amplitude (see FixtureDataProvider's docstring
    # for why this is still fully deterministic despite using `random`).
    noise_amplitude: float


# One entry per ticker the e2e suite is allowed to look up; any other ticker raises
# TickerNotFoundError (same as a real, unknown symbol would against yfinance/Stooq), so the
# suite can also exercise the 404 "unknown ticker" path deliberately (see
# frontend/tests/e2e/stock-analysis.spec.ts). Deliberately spans a strong uptrend, a mild
# uptrend, a downtrend, and a flat/choppy series -- a real spread of Triple Screen input
# shapes -- rather than one ticker, though e2e specs assert *structurally* (a BUY/SELL/HOLD
# badge and a 0-100 confidence score render at all) rather than pinning an exact signal value:
# the real Elder Triple Screen outcome depends on interacting Tide/Wave/Trigger/Impulse rules
# across the whole window (docs/Analyse.md), not just this coarse trend shape, so hand-deriving
# an exact expected signal here would either be wrong or would duplicate app.signals.engine's
# own logic just to predict its output -- that precision is the pytest suite's job (see the
# verify-elder-signal skill), not this e2e fixture's.
_FIXTURE_TICKERS: dict[str, _SeriesSpec] = {
    "AAPL": _SeriesSpec(start_price=150.0, drift_per_day=0.35, noise_amplitude=1.5),
    "MSFT": _SeriesSpec(start_price=300.0, drift_per_day=0.12, noise_amplitude=2.5),
    "TSLA": _SeriesSpec(start_price=250.0, drift_per_day=-0.30, noise_amplitude=4.0),
    "GOOGL": _SeriesSpec(start_price=120.0, drift_per_day=0.0, noise_amplitude=1.0),
}


class FixtureDataProvider(DataProvider):
    """In-memory, no-I/O `DataProvider` serving a fixed set of synthetic tickers
    (`_FIXTURE_TICKERS`).

    Every call is a pure function of `ticker`: no shared mutable state, no filesystem/network
    I/O, and no wall-clock-seeded randomness -- `random.Random` is seeded from the ticker's own
    name, so the *shape* of a given ticker's series (its day-to-day wiggle pattern) is identical
    every time this process runs, on any machine, any day. The series' calendar dates still
    anchor to "today" (`pd.Timestamp.today()`) purely so the frontend's date-labeled UI (the
    price chart's x-axis, `analysis.as_of`) looks like real, current data rather than a
    hard-coded past date -- this doesn't affect determinism of the *test assertions* below,
    which only check structural/shape properties (a signal renders, a chart has bars, indicator
    values are finite numbers), never an exact price or signal pinned to a specific calendar
    date.
    """

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        return self._series(ticker)

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        daily = self.get_daily_ohlcv(ticker)
        weekly = daily.resample("W-FRI").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        weekly = weekly.dropna(subset=["open", "high", "low", "close"])
        weekly.index.name = "date"
        if len(weekly) < _MIN_WEEKLY_BARS:  # pragma: no cover - not reachable with current constants
            # Not reachable with the current _NUM_DAILY_BARS/_FIXTURE_TICKERS values (kept as
            # a guard, not exercised behavior) -- see YFinanceProvider/StooqProvider's own
            # identical check for why this still raises rather than silently under-serving.
            raise InsufficientHistoryError(ticker, available=len(weekly), required=_MIN_WEEKLY_BARS)
        return weekly

    @staticmethod
    def _series(ticker: str) -> pd.DataFrame:
        spec = _FIXTURE_TICKERS.get(ticker.upper())
        if spec is None:
            raise TickerNotFoundError(ticker)

        rng = random.Random(f"fintrade-e2e-fixture:{ticker.upper()}")
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=_NUM_DAILY_BARS)

        closes: list[float] = []
        price = spec.start_price
        for _ in dates:
            price += spec.drift_per_day + rng.uniform(-spec.noise_amplitude, spec.noise_amplitude)
            price = max(price, 1.0)  # keep the series positive regardless of drift/noise
            closes.append(price)

        opens = [closes[0], *closes[:-1]]
        highs = [
            max(o, c) + abs(rng.uniform(0, spec.noise_amplitude)) for o, c in zip(opens, closes, strict=True)
        ]
        lows = [
            max(min(o, c) - abs(rng.uniform(0, spec.noise_amplitude)), 0.5)
            for o, c in zip(opens, closes, strict=True)
        ]
        volumes = [1_000_000.0 + rng.uniform(0, 200_000.0) for _ in dates]

        return pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
            index=pd.DatetimeIndex(dates, name="date"),
        )
