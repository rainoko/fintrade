"""Integration tests for GET /api/stocks/{ticker}/analysis (app/api/routers/stocks.py).

Uses a stub `DataProvider` (via a `get_data_provider` dependency override, same pattern as
tests/integration/test_portfolio_get.py) so these tests never touch a live market data
provider.

`_isolated_db` below (autouse) gives every test in this module its own fresh in-memory
`TradingModeSettingORM` table (via a `get_db` override, same StaticPool in-memory-SQLite
pattern as tests/integration/test_stocks_indicator_history.py's own) -- this endpoint now reads
the active trading mode (`backend-day-trader-timeframe-mode-api`), so without this override
every call here would hit the real on-disk `fintrade.db` (app/config.py's default
`database_url`) instead of a test-only database. Every test in this module not explicitly
about day-trader mode (see `TestDayTraderMode` below) relies on the isolated DB's default
`swing` mode (no row ever written), matching this endpoint's behavior before this task.

The BUY/SELL/HOLD fixtures below are copied verbatim from
tests/unit/signals/test_engine.py's `TestAnalyseEndToEnd` (the real, unmocked
Screen/gate/indicator composition already has exhaustive hand-derived coverage there); these
tests instead focus on this route's own job -- wiring the provider fetch, `analyse()` call, and
`AnalysisResponse` mapping together, plus the 404/422/503 error mapping.
"""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_data_provider, get_ibkr_provider
from app.data.base import ExtendedData, InsiderTransaction
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.data.ibkr_provider import GatewayStatus, IBKRBar, IBKRUnavailableError
from app.db.models import Base
from app.db.session import get_db
from app.indicators.autoenvelope import autoenvelope
from app.main import app
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


@pytest.fixture(autouse=True)
def _isolated_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        app.dependency_overrides.pop(get_db, None)

# The all-null/empty ExtendedData every `_StubProvider` ticker gets unless a test explicitly
# overrides it via `extended` -- keeps every pre-existing test in this file (written before
# `get_extended_data` existed) passing unchanged, since AnalysisResponse.extended_data is a
# required field regardless of what a given test actually cares about.
_EMPTY_EXTENDED_DATA = ExtendedData(
    earnings_date=None,
    ex_dividend_date=None,
    shares_short=None,
    short_ratio=None,
    short_percent_of_float=None,
    float_shares=None,
    insider_transactions=[],
)


class _StubProvider:
    """A minimal DataProvider stand-in: returns fixed daily/weekly frames per ticker, or
    raises a fixed exception for tickers listed in the relevant `failing_*` set."""

    def __init__(
        self,
        *,
        daily: dict[str, pd.DataFrame] | None = None,
        weekly: dict[str, pd.DataFrame] | None = None,
        extended: dict[str, ExtendedData] | None = None,
        failing_daily: dict[str, Exception] | None = None,
        failing_weekly: dict[str, Exception] | None = None,
        failing_extended: dict[str, Exception] | None = None,
    ) -> None:
        self._daily = daily or {}
        self._weekly = weekly or {}
        self._extended = extended or {}
        self._failing_daily = failing_daily or {}
        self._failing_weekly = failing_weekly or {}
        self._failing_extended = failing_extended or {}

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_daily:
            raise self._failing_daily[ticker]
        return self._daily[ticker]

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_weekly:
            raise self._failing_weekly[ticker]
        return self._weekly[ticker]

    def get_extended_data(self, ticker: str) -> ExtendedData:
        if ticker in self._failing_extended:
            raise self._failing_extended[ticker]
        return self._extended.get(ticker, _EMPTY_EXTENDED_DATA)


def _make_client(provider: _StubProvider) -> TestClient:
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


def _get_analysis(provider: _StubProvider, ticker: str = "AAPL"):
    test_client = _make_client(provider)
    try:
        return test_client.get(f"/api/stocks/{ticker}/analysis")
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


def _buy_daily_ohlcv(uptrend_days: int = 20) -> pd.DataFrame:
    # `uptrend_days` days of a gentle uptrend, then a 5-day steep selloff on elevated volume
    # (an oversold pullback), then one more day rallying sharply back above the prior day's
    # high (the Trigger) -- copied from test_engine.py's
    # test_end_to_end_buy_after_pullback_and_trigger, with `uptrend_days` (default 20,
    # matching the original fixture exactly) made overridable so TestProfitTarget below can
    # extend the prefix past the Autoenvelope channel's ~100-bar warm-up window while keeping
    # the exact same BUY-triggering tail shape.
    closes = [100 + i * 0.5 for i in range(uptrend_days)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    volumes = [1_000_000] * (uptrend_days + 4) + [9_000_000, 3_000_000]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


def _buy_weekly_ohlcv() -> pd.DataFrame:
    # 40 weeks of accelerating 5%/week growth -- BULLISH tide. `weekly_closes` is built as a
    # plain array (not a pd.Series) before assembling the DataFrame with an explicit
    # DatetimeIndex below -- a Series column carries its own (default RangeIndex) index, which
    # pandas would otherwise reindex against the DataFrame's DatetimeIndex on construction,
    # silently turning every value NaN since the two indexes share no labels.
    weekly_closes = [100 * (1.05**i) for i in range(40)]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=40, freq="W", name="date"),
    )


def _buy_weekly_ohlcv_mild_growth(weeks: int) -> pd.DataFrame:
    # `weeks` weeks of steady 0.5%/week compounding growth -- unlike `_buy_weekly_ohlcv`'s own
    # faster 5%/week growth (which would compound to an unrealistically huge, hard-to-reason-
    # about channel over 100+ weeks), this stays at a modest scale while still compounding
    # (rather than a pure linear ramp) so the weekly MACD-Histogram keeps rising bar-over-bar at
    # the latest bar -- a genuine BULLISH tide, not just a rising EMA(13) -- all the way out to
    # `weeks` bars. Used by TestProfitTarget to clear the WEEKLY Autoenvelope channel's own
    # ~100-week warm-up window (see this module's own `_buy_weekly_ohlcv` for the shorter,
    # faster-growth fixture every other BUY-signal test in this file uses instead).
    weekly_closes = [100 * (1.005**i) for i in range(weeks)]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2020-01-01", periods=weeks, freq="W", name="date"),
    )


def _sell_daily_ohlcv() -> pd.DataFrame:
    # Mirror image of the BUY fixture: gentle downtrend, then a 5-day steep rebound rally on
    # elevated volume, then one more day selling off sharply back below the prior day's low.
    closes = [100 - i * 0.5 for i in range(20)]
    closes += [closes[-1] + 3 * i for i in range(1, 6)]
    closes.append(closes[-1] - 8.0)
    volumes = [1_000_000] * 24 + [9_000_000, 3_000_000]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


def _sell_weekly_ohlcv() -> pd.DataFrame:
    # Same plain-array-not-Series reasoning as _buy_weekly_ohlcv above.
    weekly_closes = [1000 * (0.9**i) for i in range(40)]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=40, freq="W", name="date"),
    )


def _hold_daily_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
        },
        index=pd.date_range("2026-01-01", periods=30, freq="D", name="date"),
    )


def _hold_weekly_ohlcv() -> pd.DataFrame:
    """28 flat weeks, then a tiny up-week and a tiny down-week -- deliberately *not*
    perfectly flat throughout. A perfectly constant weekly close would make weekly
    EMA(13) and the weekly MACD-Histogram both exactly tied bar-over-bar on the last
    step, which `app.signals.impulse._direction`'s documented tie-counts-as-falling
    convention (reused by `evaluate_tide` for Screen 1, per `backend-weekly-impulse-
    screen1`) would resolve to weekly Impulse RED / Tide BEARISH, not the NEUTRAL this
    fixture is meant to exercise. The small up-then-down wiggle instead produces a
    genuine EMA(13)-still-rising-but-histogram-ticking-down disagreement -- weekly
    Impulse BLUE / Tide NEUTRAL -- while keeping the series close-to-flat in every
    other respect Screen 2/3 care about (no real trend for Wave/Trigger to key off).
    """
    weekly_closes = [100.0] * 28 + [100.3, 100.1]
    return pd.DataFrame(
        {
            "open": weekly_closes,
            "high": [c * 1.01 for c in weekly_closes],
            "low": [c * 0.99 for c in weekly_closes],
            "close": weekly_closes,
            "volume": 1_000_000,
        },
        index=pd.date_range("2025-01-01", periods=30, freq="W", name="date"),
    )


def _divergence_daily_ohlcv() -> pd.DataFrame:
    """A real bullish RSI divergence, end to end: a sharp, monotonic 16-day selloff (100 ->
    40, RSI fully saturates at 0 -- as extreme a first low as RSI can register) followed by a
    rally, then a slower, zigzagging (down 7 / up 2, repeated) decline that reaches a new,
    LOWER closing low (17, below the first selloff's 40) without ever saturating RSI the same
    way -- the up-days along the way keep RSI's trailing gain/loss average well off zero, so
    its reading at the second low (~18.6) is markedly shallower than the first (0). Confirmed
    empirically against this app's own real app.signals.divergence.current_divergence (not
    hand-derived by hand -- RSI's 9-day rolling-average math over a 38-bar span isn't
    hand-tractable the way tests/unit/signals/test_divergence.py's own synthetic-indicator
    fixtures are) -- this is the "as closely as fixture data allows" case docs/tasks/
    backend-divergence-detection.json's own checklist anticipates for a real, non-synthetic
    indicator path; see that task's `decisions` entry. MACD-Histogram/Stochastic do NOT
    independently qualify on this same fixture (confirmed the same way), so RSI is
    unambiguously the winner here, not just the tie-break priority order.
    """
    closes = [100.0 - i * 4 for i in range(16)]  # idx 0-15: 100 -> 40 (first low, idx 15)
    for _i in range(1, 10):
        closes.append(closes[-1] + 6.0)  # idx 16-24: rally 40 -> 94
    value = closes[-1]
    for i in range(30):  # idx 25-54: zigzag decline to a new low
        value = value - 7.0 if i % 2 == 0 else value + 2.0
        closes.append(value)
    while len(closes) < 70:
        closes.append(closes[-1] + 3.0)  # idx 55-69: rally after the second low
    closes = closes[:70]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D", name="date"),
    )


class TestDivergenceField:
    """Integration coverage for `divergence`'s end-to-end wiring (detection ->
    `_divergence_to_schema` -> `AnalysisResponse.divergence`) using a real (not mocked)
    RSI computation -- see `_divergence_daily_ohlcv`'s own docstring for how this fixture was
    built and confirmed."""

    def test_bullish_rsi_divergence_is_detected_and_mapped(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _divergence_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        divergence = response.json()["divergence"]
        assert divergence is not None
        assert divergence["kind"] == "bullish"
        assert divergence["indicator"] == "rsi"
        assert divergence["first_extreme_date"] == "2026-01-16"
        assert divergence["first_extreme_price"] == 40.0
        assert divergence["first_extreme_indicator_value"] == 0.0
        assert divergence["second_extreme_date"] == "2026-02-23"
        assert divergence["second_extreme_price"] == 17.0
        assert divergence["second_extreme_indicator_value"] == pytest.approx(18.604651162790702)
        assert divergence["bars_apart"] == 38
        assert divergence["centerline_crossed"] is None
        assert divergence["beyond_reference_line"] is False
        assert divergence["aborted"] is False


class TestGetAnalysis:
    def test_buy_signal_response_shape(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["as_of"] == _buy_daily_ohlcv().index[-1].date().isoformat()
        assert body["signal"] == "BUY"
        assert 0 <= body["confidence"] <= 100
        assert body["confidence_band"] in ("Low", "Medium", "High")
        assert body["screens"]["tide"]["trend"] == "BULLISH"
        # A fresh BUY already proves showed_pullback_in_lookback was true at some point in
        # the 5-day window (one of _determine_signal's four required conditions) -- and
        # showed_rally_in_lookback is real (not null) False, since tide is directional.
        assert body["screens"]["wave"]["showed_pullback_in_lookback"] is True
        assert body["screens"]["wave"]["showed_rally_in_lookback"] is False
        assert len(body["confidence_breakdown"]) == 5
        assert set(body["indicators"]) == {
            "ema_13",
            "ema_26",
            "macd_histogram",
            "bull_power",
            "bear_power",
            "channel_upper",
            "channel_lower",
            "rsi",
            "season",
            "trend_strength",
        }
        # This fixture (26 daily bars) is far shorter than the Autoenvelope channel's ~100-bar
        # deviation-average warm-up window, so both bands are still null here -- see
        # test_channel_bands_populated_with_sufficient_history for the populated case.
        assert body["indicators"]["channel_upper"] is None
        assert body["indicators"]["channel_lower"] is None
        # rsi's warm-up (9 daily closing changes) is far shorter than the channel's, so it's
        # already populated on this same 26-bar fixture.
        assert body["indicators"]["rsi"] is not None
        assert 0 <= body["indicators"]["rsi"] <= 100
        # This fixture (26 bars) is far more than the 2-bar minimum classify_season needs,
        # so season is always a real label here -- never null.
        assert body["indicators"]["season"] in ("Spring", "Summer", "Autumn", "Winter")
        # trend_strength.atr/plus_di/minus_di warm up after 13 bars, well within this 26-bar
        # fixture; adx needs a further 13-bar window on top of that (26 total), so it's only
        # just barely defined by this fixture's very last bar.
        trend_strength = body["indicators"]["trend_strength"]
        assert set(trend_strength) == {"atr", "plus_di", "minus_di", "adx"}
        assert trend_strength["atr"] is not None and trend_strength["atr"] >= 0
        assert trend_strength["plus_di"] is not None and trend_strength["plus_di"] >= 0
        assert trend_strength["minus_di"] is not None and trend_strength["minus_di"] >= 0
        assert trend_strength["adx"] is not None and trend_strength["adx"] >= 0
        # This fixture (26 bars) is also far too short to produce any support/resistance
        # zone (min_zone_length_days=14 plus the fractal/clustering machinery needs real
        # repeated touches) -- see TestSupportResistanceZones below for the populated case.
        assert body["support_resistance_zones"] == []
        # Same reasoning as support_resistance_zones above: this fixture is far too short/
        # simple for a genuine divergence (Kerry Lovvorn's own 20-40-bar spacing filter alone
        # needs more history than this 26-bar fixture has) -- see TestDivergenceField below
        # for the populated case.
        assert body["divergence"] is None
        # profit_target needs either a channel (this fixture is far too short) or a
        # qualifying support/resistance zone above current price (also absent here, per
        # support_resistance_zones' own emptiness above) -- see TestProfitTarget below for
        # the populated case.
        assert body["profit_target"] is None

    def test_malformed_latest_daily_bar_is_excluded_not_nulled(self) -> None:
        """Regression test for the real, observed yfinance condition this task fixes: the
        most recent daily bar can come back with NaN open/high/low/close and only volume
        populated. `app.signals.engine.drop_malformed_daily_bars` excludes such a bar before
        analysis rather than letting it leak `null` into the (non-Optional)
        `Indicators`/`WaveScreen` schema fields, so `as_of` should reflect the last *real*
        bar's date, not the malformed one, and every indicator field should still be a real
        number.
        """
        clean_daily = _buy_daily_ohlcv()
        malformed_row = pd.DataFrame(
            {
                "open": [float("nan")],
                "high": [float("nan")],
                "low": [float("nan")],
                "close": [float("nan")],
                "volume": [500_000],
            },
            index=pd.DatetimeIndex(
                [clean_daily.index[-1] + pd.DateOffset(days=1)], name="date"
            ),
        )
        daily_with_malformed_latest_bar = pd.concat([clean_daily, malformed_row])
        provider = _StubProvider(
            daily={"AAPL": daily_with_malformed_latest_bar}, weekly={"AAPL": _buy_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "BUY"
        # as_of reflects the last real bar, not the malformed (later-dated) one.
        assert body["as_of"] == clean_daily.index[-1].date().isoformat()
        for field, value in body["indicators"].items():
            # channel_upper/channel_lower are the one legitimately-nullable pair here (the
            # Autoenvelope channel's ~100-bar warm-up, not related to the malformed bar this
            # test targets) -- `clean_daily` alone is far shorter than that window.
            if field in ("channel_upper", "channel_lower"):
                assert value is None
                continue
            # season is a Spring/Summer/Autumn/Winter label, not a number -- checked
            # separately (it's still real/non-null here, `clean_daily` is far longer than
            # its 2-bar minimum).
            if field == "season":
                assert value in ("Spring", "Summer", "Autumn", "Winter")
                continue
            # trend_strength is a nested object -- same 26-bar fixture as
            # test_buy_signal_response_shape, so every one of its own fields (atr/plus_di/
            # minus_di/adx) is already past its own warm-up and real (non-null) here too.
            if field == "trend_strength":
                for sub_field, sub_value in value.items():
                    assert isinstance(sub_value, (int, float)), (
                        f"indicators.trend_strength.{sub_field} was {sub_value!r}, not a number"
                    )
                continue
            assert isinstance(value, (int, float)), f"indicators.{field} was {value!r}, not a number"
        assert body["screens"]["wave"]["stochastic_k"] is not None
        assert body["screens"]["wave"]["force_index_2ema"] is not None

    def test_channel_bands_populated_with_sufficient_history(self) -> None:
        """channel_upper/channel_lower need a full 100-bar Autoenvelope deviation-average
        window (`app.indicators.autoenvelope.autoenvelope`'s default `deviation_lookback`) --
        this fixture is long enough (120 daily bars) for that window to be full at the latest
        bar, so both bands should be real numbers, with upper strictly above lower (a
        symmetric non-degenerate envelope around ema_13)."""
        daily = pd.DataFrame(
            {
                "open": [100.0 + i * 0.3 + (2.0 if i % 7 == 0 else 0.0) for i in range(120)],
                "high": [101.0 + i * 0.3 + (2.0 if i % 7 == 0 else 0.0) for i in range(120)],
                "low": [99.0 + i * 0.3 + (2.0 if i % 7 == 0 else 0.0) for i in range(120)],
                "close": [100.0 + i * 0.3 + (2.0 if i % 7 == 0 else 0.0) for i in range(120)],
                "volume": [1_000_000] * 120,
            },
            index=pd.date_range("2026-01-01", periods=120, freq="D", name="date"),
        )
        weekly = _hold_weekly_ohlcv()
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        channel_upper = body["indicators"]["channel_upper"]
        channel_lower = body["indicators"]["channel_lower"]
        assert channel_upper is not None
        assert channel_lower is not None
        assert channel_upper > channel_lower

    def test_sell_signal_response_shape(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _sell_daily_ohlcv()}, weekly={"AAPL": _sell_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "SELL"
        assert body["screens"]["tide"]["trend"] == "BEARISH"
        assert body["screens"]["wave"]["showed_rally_in_lookback"] is True
        assert body["screens"]["wave"]["showed_pullback_in_lookback"] is False
        assert len(body["confidence_breakdown"]) == 5
        # profit_target is BUY-only (this app's protective-stop formula is long-only, with
        # no symmetric SELL-side stop to pair a reward:risk ratio against -- see
        # app.portfolio.profit_target's module docstring).
        assert body["profit_target"] is None

    def test_hold_signal_has_zero_confidence_and_empty_breakdown(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "HOLD"
        assert body["confidence"] == 0
        assert body["confidence_band"] == "Low"
        assert body["confidence_breakdown"] == []
        # Tide is NEUTRAL for this fixture -- Wave was never evaluated against a
        # direction, so both lookback fields are null, not False.
        assert body["screens"]["tide"]["trend"] == "NEUTRAL"
        assert body["screens"]["wave"]["showed_pullback_in_lookback"] is None
        assert body["screens"]["wave"]["showed_rally_in_lookback"] is None
        assert body["profit_target"] is None

    def test_ticker_is_uppercased(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_analysis(provider, ticker="aapl")

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"

    def test_unknown_ticker_returns_404(self) -> None:
        provider = _StubProvider(failing_daily={"ZZZZ": TickerNotFoundError("ZZZZ")})

        response = _get_analysis(provider, ticker="ZZZZ")

        assert response.status_code == 404
        assert "ZZZZ" in response.json()["detail"]

    def test_insufficient_weekly_history_returns_422(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            failing_weekly={
                "AAPL": InsufficientHistoryError("AAPL", available=5, required=26)
            },
        )

        response = _get_analysis(provider)

        assert response.status_code == 422
        assert "AAPL" in response.json()["detail"]

    def test_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            failing_daily={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            }
        )

        response = _get_analysis(provider)

        assert response.status_code == 503

    def test_weekly_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            failing_weekly={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            },
        )

        response = _get_analysis(provider)

        assert response.status_code == 503

    def test_extended_data_provider_unavailable_returns_503(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            failing_extended={
                "AAPL": DataProviderUnavailableError("both providers failed for AAPL")
            },
        )

        response = _get_analysis(provider)

        assert response.status_code == 503


class TestExtendedData:
    """GET /api/stocks/{ticker}/analysis's `extended_data` field (earnings/dividend dates,
    short interest, insider transactions -- see the backend-market-data-extra-fields task)."""

    def test_default_stub_is_all_null_and_available(self) -> None:
        """No test above this class passes an explicit `extended=`, so every one of them
        implicitly relies on `_StubProvider`'s default (`_EMPTY_EXTENDED_DATA`) round-tripping
        through the real `AnalysisResponse` schema -- this pins that default's exact shape."""
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()}
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        assert response.json()["extended_data"] == {
            "earnings_date": None,
            "earnings_within_warning_days": False,
            "ex_dividend_date": None,
            "shares_short": None,
            "short_ratio": None,
            "short_percent_of_float": None,
            "float_shares": None,
            "insider_transactions": [],
            "unavailable_reason": None,
        }

    def test_populated_fields_and_insider_transactions_pass_through(self) -> None:
        extended = ExtendedData(
            earnings_date=date(2026, 12, 1),
            ex_dividend_date=date(2026, 11, 15),
            shares_short=12_345_678,
            short_ratio=2.3,
            short_percent_of_float=0.045,
            float_shares=1_000_000_000,
            insider_transactions=[
                InsiderTransaction(
                    insider="Cook Timothy D",
                    position="Chief Executive Officer",
                    transaction_text="Sale at price 220.00 - 225.00 per share.",
                    shares=50_000.0,
                    value=11_125_000.0,
                    start_date=date(2026, 8, 15),
                    ownership="D",
                )
            ],
        )
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": extended},
        )

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()["extended_data"]
        assert body["earnings_date"] == "2026-12-01"
        assert body["ex_dividend_date"] == "2026-11-15"
        assert body["shares_short"] == 12_345_678
        assert body["short_ratio"] == 2.3
        assert body["short_percent_of_float"] == 0.045
        assert body["float_shares"] == 1_000_000_000
        assert body["unavailable_reason"] is None
        assert body["insider_transactions"] == [
            {
                "insider": "Cook Timothy D",
                "position": "Chief Executive Officer",
                "transaction_text": "Sale at price 220.00 - 225.00 per share.",
                "shares": 50_000.0,
                "value": 11_125_000.0,
                "start_date": "2026-08-15",
                "ownership": "D",
            }
        ]

    def test_earnings_within_warning_window_is_flagged_true(self) -> None:
        soon = date.today() + timedelta(days=5)
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": ExtendedData(
                earnings_date=soon,
                ex_dividend_date=None,
                shares_short=None,
                short_ratio=None,
                short_percent_of_float=None,
                float_shares=None,
                insider_transactions=[],
            )},
        )

        response = _get_analysis(provider)

        assert response.json()["extended_data"]["earnings_within_warning_days"] is True

    def test_earnings_beyond_warning_window_is_flagged_false(self) -> None:
        far_off = date.today() + timedelta(days=90)
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": ExtendedData(
                earnings_date=far_off,
                ex_dividend_date=None,
                shares_short=None,
                short_ratio=None,
                short_percent_of_float=None,
                float_shares=None,
                insider_transactions=[],
            )},
        )

        response = _get_analysis(provider)

        assert response.json()["extended_data"]["earnings_within_warning_days"] is False

    def test_past_earnings_date_is_flagged_false(self) -> None:
        past = date.today() - timedelta(days=1)
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": ExtendedData(
                earnings_date=past,
                ex_dividend_date=None,
                shares_short=None,
                short_ratio=None,
                short_percent_of_float=None,
                float_shares=None,
                insider_transactions=[],
            )},
        )

        response = _get_analysis(provider)

        assert response.json()["extended_data"]["earnings_within_warning_days"] is False

    def test_unavailable_reason_surfaces_when_fallback_provider_active(self) -> None:
        """Reproduces `StooqProvider.get_extended_data`'s always-unavailable result reaching
        the API response unmodified through `CachedDataProvider`'s fallback path (unit-tested
        directly in tests/unit/data/test_cache.py) -- here just confirming the API layer's own
        mapping (`_extended_data_to_schema`) passes `unavailable_reason` through rather than
        dropping or reinterpreting it."""
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": ExtendedData(
                earnings_date=None,
                ex_dividend_date=None,
                shares_short=None,
                short_ratio=None,
                short_percent_of_float=None,
                float_shares=None,
                insider_transactions=[],
                unavailable_reason="fallback_provider_active",
            )},
        )

        response = _get_analysis(provider)

        assert response.json()["extended_data"]["unavailable_reason"] == "fallback_provider_active"


class TestInsiderClusters:
    """Confirms GET /api/stocks/{ticker}/analysis's `insider_clusters` field is actually wired
    to `app.signals.insider_clusters.detect_insider_clusters` over
    `extended_data.insider_transactions` -- the algorithm itself is hand-verified in
    tests/unit/signals/test_insider_clusters.py; this just checks the API-layer plumbing
    (empty by default, populated + correctly shaped when a qualifying cluster exists)."""

    def test_empty_when_no_insider_transactions(self) -> None:
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": ExtendedData(
                earnings_date=None,
                ex_dividend_date=None,
                shares_short=None,
                short_ratio=None,
                short_percent_of_float=None,
                float_shares=None,
                insider_transactions=[],
            )},
        )

        response = _get_analysis(provider)

        assert response.json()["insider_clusters"] == []

    def test_qualifying_buy_cluster_is_reported(self) -> None:
        extended = ExtendedData(
            earnings_date=None,
            ex_dividend_date=None,
            shares_short=None,
            short_ratio=None,
            short_percent_of_float=None,
            float_shares=None,
            insider_transactions=[
                InsiderTransaction(
                    insider="Alice A",
                    position="Director",
                    transaction_text="Purchase at price 10.00 per share.",
                    shares=100.0,
                    value=None,
                    start_date=date(2026, 1, 1),
                    ownership="D",
                ),
                InsiderTransaction(
                    insider="Bob B",
                    position="Director",
                    transaction_text="Purchase at price 11.00 per share.",
                    shares=200.0,
                    value=None,
                    start_date=date(2026, 1, 10),
                    ownership="D",
                ),
                InsiderTransaction(
                    insider="Carol C",
                    position="Director",
                    transaction_text="Purchase at price 12.00 per share.",
                    shares=300.0,
                    value=None,
                    start_date=date(2026, 1, 20),
                    ownership="D",
                ),
            ],
        )
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": extended},
        )

        response = _get_analysis(provider)

        assert response.json()["insider_clusters"] == [
            {
                "direction": "buy",
                "window_start_date": "2026-01-01",
                "window_end_date": "2026-01-20",
                "insiders": ["Alice A", "Bob B", "Carol C"],
                "transaction_count": 3,
                "total_shares": 600.0,
                "total_value": None,
            }
        ]

    def test_non_qualifying_transactions_produce_no_cluster(self) -> None:
        """Only 2 distinct insiders -- below the 3-insider threshold -- no cluster."""
        extended = ExtendedData(
            earnings_date=None,
            ex_dividend_date=None,
            shares_short=None,
            short_ratio=None,
            short_percent_of_float=None,
            float_shares=None,
            insider_transactions=[
                InsiderTransaction(
                    insider="Alice A",
                    position="Director",
                    transaction_text="Purchase at price 10.00 per share.",
                    shares=None,
                    value=None,
                    start_date=date(2026, 2, 1),
                    ownership="D",
                ),
                InsiderTransaction(
                    insider="Bob B",
                    position="Director",
                    transaction_text="Purchase at price 11.00 per share.",
                    shares=None,
                    value=None,
                    start_date=date(2026, 2, 10),
                    ownership="D",
                ),
            ],
        )
        provider = _StubProvider(
            daily={"AAPL": _hold_daily_ohlcv()},
            weekly={"AAPL": _hold_weekly_ohlcv()},
            extended={"AAPL": extended},
        )

        response = _get_analysis(provider)

        assert response.json()["insider_clusters"] == []


def _bar(high: float, low: float, close: float, volume: float = 1_000_000.0) -> dict:
    return {"open": close, "high": high, "low": low, "close": close, "volume": volume}


def _filler_bar(i: int) -> dict:
    # Strictly monotonic -- never ties a neighbor, so it never registers as a swing point
    # itself. Same technique as tests/unit/signals/test_support_resistance.py's fixtures.
    close = 90.0 + 0.001 * i
    return {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 500_000.0}


def _zones_daily_ohlcv(overrides: dict[int, dict], n: int = 60) -> pd.DataFrame:
    rows = [_filler_bar(i) for i in range(n)]
    for i, bar in overrides.items():
        rows[i] = bar
    return pd.DataFrame(rows, index=pd.bdate_range(start="2024-01-02", periods=n, name="date"))


class TestSupportResistanceZones:
    """Integration coverage for support_resistance_zones' end-to-end wiring (detection ->
    schema -> JSON) -- the detection algorithm itself is exhaustively unit-tested against
    hand-derived values in tests/unit/signals/test_support_resistance.py; these tests only
    need to prove GET /api/stocks/{ticker}/analysis actually calls it and serializes the
    result correctly."""

    def test_clean_zone_is_detected_and_serialized(self) -> None:
        daily = _zones_daily_ohlcv(
            {
                4: _bar(110.0, 107.0, 109.0),
                24: _bar(110.0, 107.0, 109.3),
                44: _bar(110.0, 107.0, 108.8),
            }
        )
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": _hold_weekly_ohlcv()})

        response = _get_analysis(provider)

        assert response.status_code == 200
        zones = response.json()["support_resistance_zones"]
        matches = [z for z in zones if z["role"] == "resistance" and z["lower"] == pytest.approx(108.8)]
        assert len(matches) == 1
        zone = matches[0]
        assert zone["upper"] == pytest.approx(109.3)
        assert zone["touch_count"] == 3
        assert zone["first_touch_date"] == daily.index[4].date().isoformat()
        assert zone["last_touch_date"] == daily.index[44].date().isoformat()
        assert zone["length_category"] == "minor"
        assert zone["height_category"] == "minor"
        assert zone["broken"] is False
        assert zone["break_date"] is None
        assert zone["false_breakout"] is None

    def test_role_flip_and_false_breakout_serialize_correctly(self) -> None:
        overrides = {
            4: _bar(110.0, 107.0, 109.0),
            24: _bar(110.0, 107.0, 109.3),
            44: _bar(110.0, 107.0, 108.8),
            # False breakout: closes above, then back inside, within the window.
            48: _bar(120.0, 112.0, 115.0),
            49: _bar(110.0, 108.9, 109.0),
        }
        # True breakout later on, never reentering.
        for i in range(53, 60):
            overrides[i] = _bar(130.0, 125.0, 128.0)
        daily = _zones_daily_ohlcv(overrides)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": _hold_weekly_ohlcv()})

        response = _get_analysis(provider)

        assert response.status_code == 200
        zones = response.json()["support_resistance_zones"]
        matches = [z for z in zones if z["lower"] == pytest.approx(108.8) and z["upper"] == pytest.approx(109.3)]
        assert len(matches) == 1
        zone = matches[0]
        assert zone["broken"] is True
        assert zone["role"] == "support"
        assert zone["break_date"] == daily.index[53].date().isoformat()
        false_breakout = zone["false_breakout"]
        assert false_breakout["direction"] == "up"
        assert false_breakout["breakout_date"] == daily.index[48].date().isoformat()
        assert false_breakout["reentry_date"] == daily.index[49].date().isoformat()
        assert false_breakout["extreme_price"] == pytest.approx(120.0)


class TestProfitTarget:
    """Integration coverage for profit_target's end-to-end wiring (app.portfolio.profit_target
    .suggest_profit_target -> _profit_target_to_schema -> AnalysisResponse.profit_target) --
    the target-selection algorithm itself is exhaustively unit-tested against hand-derived
    values in tests/unit/test_portfolio_profit_target.py; these tests only need to prove this
    route actually calls it (BUY-only) and serializes the result correctly.

    The channel candidate is sourced from `weekly_ohlcv`, not `daily_ohlcv` -- Elder ch. 39
    p.161's "the value zone on a weekly chart presents a good target" (see
    `app.portfolio.profit_target`'s own module docstring and the
    backend-profit-target-weekly-channel task's `decisions` entry). So
    `body["indicators"]["channel_upper"/"channel_lower"]` (the DAILY Autoenvelope pass, used
    for the price-chart overlay) is a fully independent number from what feeds
    `profit_target` here -- the expected target below is derived from a fresh
    `app.indicators.autoenvelope.autoenvelope` call over the *weekly* fixture's own close
    series instead, the same already-independently-verified oracle
    tests/unit/test_portfolio_profit_target.py uses for the identical reason."""

    def test_populated_for_a_buy_signal_with_sufficient_history_for_a_channel(self) -> None:
        # Same BUY-triggering tail as _buy_daily_ohlcv()'s default, prefixed with enough extra
        # uptrend days to clear the DAILY Autoenvelope's ~100-bar warm-up window (so
        # `indicators.channel_upper/lower` -- unrelated to `profit_target` now, see this class's
        # own docstring -- are still real numbers here too), and (per TestSupportResistanceZones'
        # own fixtures, which need deliberately-repeated touches this monotonic prefix never
        # produces) no qualifying support/resistance zone, so the channel technique is
        # unambiguously what's exercised here. `weekly` is 110 weeks of mild, steady 0.5%/week
        # growth -- enough to clear the WEEKLY Autoenvelope's own ~100-week warm-up window while
        # keeping a genuine BULLISH tide (bar-over-bar-rising EMA(13) + histogram).
        daily = _buy_daily_ohlcv(uptrend_days=100)
        weekly = _buy_weekly_ohlcv_mild_growth(weeks=110)
        provider = _StubProvider(daily={"AAPL": daily}, weekly={"AAPL": weekly})

        response = _get_analysis(provider)

        assert response.status_code == 200
        body = response.json()
        assert body["signal"] == "BUY"
        assert body["support_resistance_zones"] == []
        assert body["indicators"]["channel_upper"] is not None
        assert body["indicators"]["channel_lower"] is not None

        profit_target = body["profit_target"]
        assert profit_target is not None
        assert profit_target["source"] == "channel"
        current_price = daily["close"].iloc[-1]
        weekly_bands = autoenvelope(weekly["close"], ema_period=13)
        weekly_channel_height = float(weekly_bands["upper"].iloc[-1] - weekly_bands["lower"].iloc[-1])
        # The DAILY channel (unrelated to this target now) and the WEEKLY one used here are
        # numerically distinct -- proving `profit_target` didn't just fall back to reusing
        # `indicators.channel_upper/lower`.
        daily_channel_height = body["indicators"]["channel_upper"] - body["indicators"]["channel_lower"]
        assert weekly_channel_height != pytest.approx(daily_channel_height, rel=1e-3)
        assert profit_target["price"] == pytest.approx(
            current_price + 0.30 * weekly_channel_height, abs=1e-6
        )
        assert profit_target["distance_to_target"] == pytest.approx(profit_target["price"] - current_price, abs=1e-6)
        assert profit_target["distance_to_target"] > 0
        # This fixture's channel-derived target sits much closer to current price than its
        # protective stop does, so the ratio genuinely fails the 2:1 rule -- exercising the
        # "flag, don't silently hide" path end to end.
        assert profit_target["reward_risk_ratio"] is not None
        assert profit_target["reward_risk_ratio"] == pytest.approx(
            profit_target["distance_to_target"] / profit_target["distance_to_stop"], abs=1e-6
        )
        assert profit_target["reward_risk_ratio"] < 2.0
        assert profit_target["meets_minimum_reward_risk"] is False


def _ibkr_bars(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    *,
    start: datetime,
    step_minutes: int,
) -> list[IBKRBar]:
    # Same shape as tests/integration/test_day_trader_mode_signal_engine.py's own `_bars`.
    return [
        IBKRBar(
            timestamp=start + timedelta(minutes=step_minutes * i),
            open=close,
            high=highs[i],
            low=lows[i],
            close=close,
            volume=volumes[i],
        )
        for i, close in enumerate(closes)
    ]


def _day_trader_long_term_bars() -> list[IBKRBar]:
    # BULLISH weekly-Impulse-equivalent Tide -- same shape as test_day_trader_mode_signal_
    # engine.py's `_long_term_bars`, relabeled as 60-minute intraday bars.
    closes = [100 * (1.05**i) for i in range(40)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    volumes = [1_000_000.0] * 40
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60)


def _day_trader_intermediate_bars() -> list[IBKRBar]:
    # An oversold-pullback-then-rally sequence whose own last two bars do NOT independently
    # satisfy evaluate_trigger's crossing rule -- same shape/reasoning as test_day_trader_mode_
    # signal_engine.py's `_intermediate_bars` (see that fixture's own docstring).
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    closes.append(closes[-1] - 1.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    volumes = [1_000_000.0] * 25 + [9_000_000.0, 3_000_000.0]
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10)


def _day_trader_short_term_bars() -> list[IBKRBar]:
    # A genuine buy-stop trigger (close crosses above prior bar's high) -- same shape as
    # test_day_trader_mode_signal_engine.py's `_short_term_bars`.
    closes = [95.5, 99.5]
    highs = [96.0, 100.0]
    lows = [94.0, 98.5]
    volumes = [500_000.0, 500_000.0]
    return _ibkr_bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2)


_FULLY_INTRADAY_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("60m"),
    intermediate=TimeframeInterval.parse("10m"),
    short_term=TimeframeInterval.parse("2m"),
)


class _StubIBKRProvider:
    """Stands in for `IBKRProvider`, exposing only the methods `app.api.day_trader_signal
    .compute_day_trader_signal`/`app.data.day_trader_intraday` call -- same convention as
    tests/integration/test_ibkr_scanner.py's `_StubIBKRProvider`.

    `resolve_conid_result`/`get_hourly_bars_by_bar_size` may each be (or contain) an
    `Exception` instance to raise, covering the `IBKRUnavailableError` paths alongside the
    happy path."""

    def __init__(
        self,
        *,
        resolve_conid_result: int | None | Exception = 999,
        get_hourly_bars_by_bar_size: dict[str, list[IBKRBar] | Exception] | None = None,
        gateway_status: GatewayStatus | None = None,
    ) -> None:
        self._resolve_conid_result = resolve_conid_result
        self._get_hourly_bars_by_bar_size = get_hourly_bars_by_bar_size or {}
        self._gateway_status = gateway_status or GatewayStatus(state="available")

    def resolve_conid(self, ticker: str) -> int | None:
        if isinstance(self._resolve_conid_result, Exception):
            raise self._resolve_conid_result
        return self._resolve_conid_result

    def get_hourly_bars(self, conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
        result = self._get_hourly_bars_by_bar_size[bar_size]
        if isinstance(result, Exception):
            raise result
        return result

    def get_gateway_status(self) -> GatewayStatus:
        return self._gateway_status


def _all_legs_available_ibkr_provider() -> _StubIBKRProvider:
    return _StubIBKRProvider(
        get_hourly_bars_by_bar_size={
            "1h": _day_trader_long_term_bars(),
            "10min": _day_trader_intermediate_bars(),
            "2min": _day_trader_short_term_bars(),
        }
    )


class TestDayTraderMode:
    """`GET /api/stocks/{ticker}/analysis` while the global trading mode is `day_trader`
    (`backend-day-trader-timeframe-mode-api`) -- see `app.api.day_trader_signal
    .compute_day_trader_signal`'s own docstring for the full set of unavailable-data cases."""

    def _client(
        self, db_session: Session, provider: _StubProvider, ibkr_provider: object | None
    ) -> TestClient:
        app.dependency_overrides[get_data_provider] = lambda: provider
        app.dependency_overrides[get_ibkr_provider] = lambda: ibkr_provider
        return TestClient(app)

    def _get(
        self,
        db_session: Session,
        provider: _StubProvider,
        ibkr_provider: object | None,
        ticker: str = "AAPL",
    ):
        test_client = self._client(db_session, provider, ibkr_provider)
        try:
            return test_client.get(f"/api/stocks/{ticker}/analysis")
        finally:
            app.dependency_overrides.pop(get_data_provider, None)
            app.dependency_overrides.pop(get_ibkr_provider, None)

    def test_fully_intraday_triple_with_all_legs_available_computes_a_real_signal(
        self, _isolated_db: Session
    ) -> None:
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        # daily/weekly are still fetched for support_resistance_zones/profit_target/
        # extended_data/as_of (this task's own decision to defer that layer's day-trader
        # wiring). Deliberately HOLD-shaped (not `_buy_daily_ohlcv()`/`_buy_weekly_ohlcv()`):
        # those independently produce this exact same BUY/BULLISH/fired result under plain
        # swing `analyse()` too (confirmed via mutation testing -- forcing the day-trader
        # branch off left this test passing), so they provide no real discrimination between
        # a genuine day-trader-mode computation and a silent fallback to swing-mode data.
        # `_hold_daily_ohlcv()`/`_hold_weekly_ohlcv()` give HOLD/NEUTRAL/no-trigger under
        # swing `analyse()` (see `TestGetAnalysis.test_hold_signal_has_zero_confidence_and_
        # empty_breakdown`), so the BUY/BULLISH/fired asserted below can only come from the
        # intraday IBKR legs going through `analyse_day_trader`.
        provider = _StubProvider(daily={"AAPL": _hold_daily_ohlcv()}, weekly={"AAPL": _hold_weekly_ohlcv()})

        response = self._get(_isolated_db, provider, _all_legs_available_ibkr_provider())

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"] == {
            "mode": "day_trader",
            "day_trader_timeframe_triple": {
                "long_term": "60m",
                "intermediate": "10m",
                "short_term": "2m",
                "factor_of_five_warnings": [],
            },
        }
        # Screen 3 fires from the genuinely distinct short-term leg (2-minute bars), not the
        # HOLD-shaped daily fixture `_StubProvider` supplies -- proving this really went
        # through analyse_day_trader, not a silent fallback to the swing-mode path (which
        # would instead produce the HOLD/NEUTRAL/not-fired result this same fixture pair
        # gives under plain swing `analyse()`).
        assert body["screens"]["tide"]["trend"] == "BULLISH"
        assert body["screens"]["trigger"]["fired"] is True
        assert body["signal"] == "BUY"
        assert 0 <= body["confidence"] <= 100
        # extended_data/as_of are still derived from the ordinary daily/weekly fixture,
        # unaffected by day-trader mode (this task's own decision, see AnalysisResponse
        # .trading_mode's field description).
        assert body["as_of"] == _hold_daily_ohlcv().index[-1].date().isoformat()

    def test_swing_mode_default_is_unaffected_by_a_configured_day_trader_triple(
        self, _isolated_db: Session
    ) -> None:
        # Configuring a day-trader triple but leaving `mode` at its default ('swing') must not
        # change this endpoint's behavior at all -- the triple is only read while `mode` is
        # actually 'day_trader'.
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.SWING, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        provider = _StubProvider(daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()})

        response = self._get(_isolated_db, provider, ibkr_provider=None)

        assert response.status_code == 200
        body = response.json()
        assert body["trading_mode"]["mode"] == "swing"
        assert body["signal"] == "BUY"
        assert body["screens"]["trigger"]["reference"] == "close_above_prior_high"

    def test_non_fully_intraday_triple_returns_503(self, _isolated_db: Session) -> None:
        mixed_triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("30m"),
            short_term=TimeframeInterval.parse("5m"),
        )
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=mixed_triple
        )
        provider = _StubProvider(daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()})

        response = self._get(_isolated_db, provider, _all_legs_available_ibkr_provider())

        assert response.status_code == 503
        assert "AAPL" in response.json()["detail"]

    def test_ibkr_disabled_returns_503(self, _isolated_db: Session) -> None:
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        provider = _StubProvider(daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()})

        response = self._get(_isolated_db, provider, ibkr_provider=None)

        assert response.status_code == 503
        assert "disabled" in response.json()["detail"]

    def test_conid_not_resolved_returns_503(self, _isolated_db: Session) -> None:
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        provider = _StubProvider(daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()})

        response = self._get(
            _isolated_db, provider, _StubIBKRProvider(resolve_conid_result=None)
        )

        assert response.status_code == 503
        assert "contract id" in response.json()["detail"]

    def test_ibkr_gateway_unavailable_during_conid_resolution_returns_503(
        self, _isolated_db: Session
    ) -> None:
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        provider = _StubProvider(daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()})

        response = self._get(
            _isolated_db,
            provider,
            _StubIBKRProvider(resolve_conid_result=IBKRUnavailableError("gateway down")),
        )

        assert response.status_code == 503
        assert "gateway down" in response.json()["detail"]

    def test_one_leg_failing_returns_503(self, _isolated_db: Session) -> None:
        set_trading_mode_setting(
            _isolated_db, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )
        provider = _StubProvider(daily={"AAPL": _buy_daily_ohlcv()}, weekly={"AAPL": _buy_weekly_ohlcv()})
        failing_ibkr_provider = _StubIBKRProvider(
            get_hourly_bars_by_bar_size={
                "1h": _day_trader_long_term_bars(),
                "10min": IBKRUnavailableError("history call failed"),
                "2min": _day_trader_short_term_bars(),
            }
        )

        response = self._get(_isolated_db, provider, failing_ibkr_provider)

        assert response.status_code == 503
        assert "intermediate leg" in response.json()["detail"]
