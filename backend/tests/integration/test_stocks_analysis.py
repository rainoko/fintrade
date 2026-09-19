"""Integration tests for GET /api/stocks/{ticker}/analysis (app/api/routers/stocks.py).

Uses a stub `DataProvider` (via a `get_data_provider` dependency override, same pattern as
tests/integration/test_portfolio_get.py) so these tests never touch a live market data
provider. This endpoint has no DB dependency of its own, so there's no `get_db` override here.

The BUY/SELL/HOLD fixtures below are copied verbatim from
tests/unit/signals/test_engine.py's `TestAnalyseEndToEnd` (the real, unmocked
Screen/gate/indicator composition already has exhaustive hand-derived coverage there); these
tests instead focus on this route's own job -- wiring the provider fetch, `analyse()` call, and
`AnalysisResponse` mapping together, plus the 404/422/503 error mapping.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_data_provider
from app.data.exceptions import (
    DataProviderUnavailableError,
    InsufficientHistoryError,
    TickerNotFoundError,
)
from app.main import app


class _StubProvider:
    """A minimal DataProvider stand-in: returns fixed daily/weekly frames per ticker, or
    raises a fixed exception for tickers listed in the relevant `failing_*` set."""

    def __init__(
        self,
        *,
        daily: dict[str, pd.DataFrame] | None = None,
        weekly: dict[str, pd.DataFrame] | None = None,
        failing_daily: dict[str, Exception] | None = None,
        failing_weekly: dict[str, Exception] | None = None,
    ) -> None:
        self._daily = daily or {}
        self._weekly = weekly or {}
        self._failing_daily = failing_daily or {}
        self._failing_weekly = failing_weekly or {}

    def get_daily_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_daily:
            raise self._failing_daily[ticker]
        return self._daily[ticker]

    def get_weekly_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker in self._failing_weekly:
            raise self._failing_weekly[ticker]
        return self._weekly[ticker]


def _make_client(provider: _StubProvider) -> TestClient:
    app.dependency_overrides[get_data_provider] = lambda: provider
    return TestClient(app)


def _get_analysis(provider: _StubProvider, ticker: str = "AAPL"):
    test_client = _make_client(provider)
    try:
        return test_client.get(f"/api/stocks/{ticker}/analysis")
    finally:
        app.dependency_overrides.pop(get_data_provider, None)


def _buy_daily_ohlcv() -> pd.DataFrame:
    # 20 days of a gentle uptrend, then a 5-day steep selloff on elevated volume (an oversold
    # pullback), then one more day rallying sharply back above the prior day's high (the
    # Trigger) -- copied from test_engine.py's test_end_to_end_buy_after_pullback_and_trigger.
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
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
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1_000_000] * 30,
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
        # This fixture (26 bars) is also far too short to produce any support/resistance
        # zone (min_zone_length_days=14 plus the fractal/clustering machinery needs real
        # repeated touches) -- see TestSupportResistanceZones below for the populated case.
        assert body["support_resistance_zones"] == []
        # Same reasoning as support_resistance_zones above: this fixture is far too short/
        # simple for a genuine divergence (Kerry Lovvorn's own 20-40-bar spacing filter alone
        # needs more history than this 26-bar fixture has) -- see TestDivergenceField below
        # for the populated case.
        assert body["divergence"] is None

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
