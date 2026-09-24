"""Unit tests for app/api/day_trader_signal.py (backend-day-trader-timeframe-mode-api).

`IBKRProvider` is mocked at the same `get_hourly_bars`/`resolve_conid` method boundary
tests/unit/data/test_day_trader_intraday.py and
tests/integration/test_day_trader_mode_signal_engine.py already use -- no live network call.
"""

from datetime import UTC, datetime, timedelta

from app.api.day_trader_signal import (
    compute_day_trader_signal,
    trading_mode_setting_to_schema,
)
from app.api.schemas import TradingModeOut
from app.data.day_trader_intraday import DayTraderIntradayBars, IntradayLegResult
from app.data.ibkr_provider import GatewayStatus, IBKRBar, IBKRProvider, IBKRUnavailableError
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import TradingModeSetting


def _bars(
    closes: list[float], *, start: datetime, step_minutes: int
) -> list[IBKRBar]:
    return [
        IBKRBar(
            timestamp=start + timedelta(minutes=step_minutes * i),
            open=close,
            high=close + 0.5,
            low=close - 0.5,
            close=close,
            volume=1_000_000.0,
        )
        for i, close in enumerate(closes)
    ]


_FULLY_INTRADAY_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("60m"),
    intermediate=TimeframeInterval.parse("10m"),
    short_term=TimeframeInterval.parse("2m"),
)

_MIXED_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("1d"),
    intermediate=TimeframeInterval.parse("30m"),
    short_term=TimeframeInterval.parse("5m"),
)


class TestComputeDayTraderSignalNotFullyIntraday:
    def test_a_triple_with_a_non_minute_leg_is_unavailable_without_any_ibkr_call(
        self, mocker
    ) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)

        outcome = compute_day_trader_signal("AAPL", _MIXED_TRIPLE, provider=provider)

        assert outcome.signal_result is None
        assert outcome.unavailable_reason is not None
        assert "MINUTE" in outcome.unavailable_reason
        provider.resolve_conid.assert_not_called()
        provider.get_hourly_bars.assert_not_called()


class TestComputeDayTraderSignalIBKRDisabled:
    def test_provider_none_is_unavailable(self) -> None:
        outcome = compute_day_trader_signal("AAPL", _FULLY_INTRADAY_TRIPLE, provider=None)

        assert outcome.signal_result is None
        assert outcome.unavailable_reason is not None
        assert "disabled" in outcome.unavailable_reason


class TestComputeDayTraderSignalConidResolution:
    def test_conid_not_resolved_is_unavailable(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.resolve_conid.return_value = None

        outcome = compute_day_trader_signal("ZZZZ", _FULLY_INTRADAY_TRIPLE, provider=provider)

        assert outcome.signal_result is None
        assert "ZZZZ" in outcome.unavailable_reason
        provider.get_hourly_bars.assert_not_called()

    def test_gateway_unavailable_during_resolution_is_unavailable(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.resolve_conid.side_effect = IBKRUnavailableError("gateway down")

        outcome = compute_day_trader_signal("AAPL", _FULLY_INTRADAY_TRIPLE, provider=provider)

        assert outcome.signal_result is None
        assert "gateway down" in outcome.unavailable_reason


class TestComputeDayTraderSignalLegFetch:
    def _fully_available_provider(self, mocker):
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.resolve_conid.return_value = 999
        bars_by_bar_size = {
            "1h": _bars([100 * (1.05**i) for i in range(40)], start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60),
            "10min": _bars(
                [100 + i * 0.5 for i in range(20)]
                + [100 + 19 * 0.5 - 3 * i for i in range(1, 6)]
                + [100 + 19 * 0.5 - 15 + 8.0, 100 + 19 * 0.5 - 15 + 7.0],
                start=datetime(2026, 1, 5, tzinfo=UTC),
                step_minutes=10,
            ),
            "2min": [
                IBKRBar(
                    timestamp=datetime(2026, 1, 5, tzinfo=UTC), open=95.5, high=96.0, low=94.0, close=95.5, volume=500_000.0
                ),
                IBKRBar(
                    timestamp=datetime(2026, 1, 5, 0, 2, tzinfo=UTC), open=99.5, high=100.0, low=98.5, close=99.5, volume=500_000.0
                ),
            ],
        }
        provider.get_hourly_bars.side_effect = lambda conid, *, lookback_days, bar_size: bars_by_bar_size[bar_size]
        return provider

    def test_all_legs_available_computes_a_real_signal(self, mocker) -> None:
        provider = self._fully_available_provider(mocker)

        outcome = compute_day_trader_signal("AAPL", _FULLY_INTRADAY_TRIPLE, provider=provider)

        assert outcome.unavailable_reason is None
        assert outcome.signal_result is not None
        assert outcome.signal_result.screens["tide"]["trend"] == "BULLISH"
        assert bool(outcome.signal_result.screens["trigger"]["fired"]) is True
        assert outcome.signal_result.signal == "BUY"

    def test_one_leg_unavailable_is_unavailable_with_a_detail_naming_the_leg(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.resolve_conid.return_value = 999
        provider.get_gateway_status.return_value = GatewayStatus(state="available")

        def _get_hourly_bars(conid, *, lookback_days, bar_size):
            if bar_size == "10min":
                raise IBKRUnavailableError("history call failed")
            return [IBKRBar(timestamp=datetime(2026, 1, 5, tzinfo=UTC), open=1, high=1, low=1, close=1, volume=1)]

        provider.get_hourly_bars.side_effect = _get_hourly_bars

        outcome = compute_day_trader_signal("AAPL", _FULLY_INTRADAY_TRIPLE, provider=provider)

        assert outcome.signal_result is None
        assert "intermediate leg" in outcome.unavailable_reason
        assert "history call failed" in outcome.unavailable_reason

    def test_leg_reported_available_with_no_ohlcv_is_treated_as_unavailable(self, mocker) -> None:
        # Defensive branch: `IntradayLegResult`'s own contract guarantees `ohlcv` is populated
        # iff `state == "available"`, so this shouldn't happen from a real
        # `get_intraday_bars_for_triple` call -- but `compute_day_trader_signal` re-checks
        # `leg.ohlcv is None` explicitly rather than trusting that contract blindly.
        fake_bars = DayTraderIntradayBars(
            long_term=IntradayLegResult(
                leg="long_term",
                interval=_FULLY_INTRADAY_TRIPLE.long_term,
                ibkr_bar_size="1h",
                state="available",
                detail=None,
                ohlcv=None,
            ),
            intermediate=None,
            short_term=None,
        )
        mocker.patch(
            "app.api.day_trader_signal.get_intraday_bars_for_triple", return_value=fake_bars
        )
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.resolve_conid.return_value = 999

        outcome = compute_day_trader_signal("AAPL", _FULLY_INTRADAY_TRIPLE, provider=provider)

        assert outcome.signal_result is None
        assert "long_term leg unavailable" in outcome.unavailable_reason


class TestTradingModeSettingToSchema:
    def test_swing_mode_with_no_triple_ever_configured(self) -> None:
        setting = TradingModeSetting(mode=TradingMode.SWING, day_trader_timeframe_triple=None)

        out = trading_mode_setting_to_schema(setting)

        assert out == TradingModeOut(mode="swing", day_trader_timeframe_triple=None)

    def test_day_trader_mode_with_a_configured_triple_echoes_it_and_its_warnings(self) -> None:
        setting = TradingModeSetting(
            mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_FULLY_INTRADAY_TRIPLE
        )

        out = trading_mode_setting_to_schema(setting)

        assert out.mode == "day_trader"
        assert out.day_trader_timeframe_triple is not None
        assert out.day_trader_timeframe_triple.long_term == "60m"
        assert out.day_trader_timeframe_triple.intermediate == "10m"
        assert out.day_trader_timeframe_triple.short_term == "2m"
        assert out.day_trader_timeframe_triple.factor_of_five_warnings == []
