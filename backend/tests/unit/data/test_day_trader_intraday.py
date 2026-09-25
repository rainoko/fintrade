"""Tests for app.data.day_trader_intraday (docs/tasks/
backend-day-trader-timeframe-mode-ibkr-intraday.json).

Per docs/architecture/Testing.md ("no live network calls in tests") and this codebase's
existing IBKR test convention (tests/unit/data/test_ibkr_provider.py), every test here mocks
`IBKRProvider` at the method boundary (`get_hourly_bars`/`get_gateway_status`) rather than
`_request`/HTTP itself -- this module's own contract is with `IBKRProvider`'s public methods,
not the wire format underneath them (that's `test_ibkr_provider.py`'s job).
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data.day_trader_intraday import (
    DayTraderIntradayBars,
    get_active_day_trader_intraday_bars,
    get_active_day_trader_intraday_history_bars,
    get_intraday_bars_for_triple,
    get_intraday_history_bars_for_triple,
)
from app.data.ibkr_provider import GatewayStatus, IBKRBar, IBKRProvider, IBKRUnavailableError
from app.db.models import Base
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


def _bar(minute_offset: int, price: float) -> IBKRBar:
    return IBKRBar(
        timestamp=datetime(2026, 1, 5, 14, 30, tzinfo=UTC) + timedelta(minutes=minute_offset),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + 0.5,
        volume=1000.0,
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db: Session = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestGetIntradayBarsForTripleUnitScoping:
    def test_minute_unit_short_term_leg_is_fetched(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0), _bar(2, 101.0)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1w"),
            intermediate=TimeframeInterval.parse("1d"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=12345, lookback_days=5)

        assert isinstance(result, DayTraderIntradayBars)
        assert result.long_term is None  # "1w" -- not MINUTE, doesn't need IBKR
        assert result.intermediate is None  # "1d" -- not MINUTE, doesn't need IBKR
        assert result.short_term is not None
        assert result.short_term.state == "available"
        assert result.short_term.ibkr_bar_size == "2min"
        assert list(result.short_term.ohlcv["close"]) == [100.5, 101.5]

    def test_two_of_three_minute_unit_legs_are_fetched(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1w"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1, lookback_days=5)

        assert result.long_term is None  # "1w" -- not MINUTE, doesn't need IBKR
        assert result.short_term is not None
        assert result.intermediate is not None
        assert result.short_term.state == "available"
        assert result.intermediate.state == "available"
        # `get_hourly_bars.call_count`'s increment is a non-atomic read-modify-write that can
        # lose updates under real concurrent invocation from separate OS threads (the three
        # legs are fetched concurrently -- see `_fetch_legs_concurrently`); `call_args_list`
        # (a plain list append) stays exact under the same concurrency, so assert on its
        # length instead (docs/tasks/backend-day-trader-timeframe-mode-ibkr-intraday-followups-followups.json).
        assert len(provider.get_hourly_bars.call_args_list) == 2

    def test_all_three_legs_fetched_for_a_fully_intraday_triple(self, mocker) -> None:
        """ch. 39's own day-trading examples (25-min/5-min/2-min, 39-min/8-min) are fully
        intraday on all three legs, not just short_term/intermediate -- `long_term` needs
        fetching too in that case, not just when it happens to be DAY/WEEK-unit (see this
        module's own docstring on the `long_term`-fetching extension)."""
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1, lookback_days=5)

        assert result.long_term is not None
        assert result.short_term is not None
        assert result.intermediate is not None
        assert result.long_term.state == "available"
        assert result.long_term.ibkr_bar_size == "5min"
        assert result.short_term.state == "available"
        assert result.intermediate.state == "available"
        # See the same call_count -> call_args_list rationale in
        # test_two_of_three_minute_unit_legs_are_fetched above.
        assert len(provider.get_hourly_bars.call_args_list) == 3

    def test_no_leg_needs_ibkr_when_none_is_minute_unit(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("2w"),
            intermediate=TimeframeInterval.parse("3d"),
            short_term=TimeframeInterval.parse("1d"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.long_term is None
        assert result.short_term is None
        assert result.intermediate is None
        provider.get_hourly_bars.assert_not_called()


class TestSelectIbkrBarSizeAndResampling:
    def test_exact_match_needs_no_resampling(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0), _bar(5, 105.0), _bar(10, 110.0)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("5m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.ibkr_bar_size == "5min"
        assert len(result.short_term.ohlcv) == 3

    def test_non_composable_interval_resamples_from_finest_evenly_dividing_bar_size(self, mocker) -> None:
        """25m isn't one of IBKR's own valid `bar` values -- 5min (the largest supported
        interval that evenly divides 25) should be fetched and resampled 5:1."""
        provider = mocker.create_autospec(IBKRProvider, instance=True)

        # Five consecutive 5-minute bars, timestamps chosen to land in exactly one 25-minute
        # bin under pandas' own default resample origin (midnight) -- 15:00 UTC is 900
        # minutes past midnight, a clean multiple of 25, so [15:00, 15:25) is a whole bin.
        def bar_at(minute_offset: int, price: float) -> IBKRBar:
            return IBKRBar(
                timestamp=datetime(2026, 1, 5, 15, 0, tzinfo=UTC) + timedelta(minutes=minute_offset),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5,
                volume=1000.0,
            )

        provider.get_hourly_bars.return_value = [bar_at(i * 5, 100.0 + i) for i in range(5)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("100m"),
            short_term=TimeframeInterval.parse("25m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        # The three legs are now fetched concurrently (checklist item 1 of
        # backend-day-trader-timeframe-mode-ibkr-intraday-followups), so `call_args_list`'s
        # own order across legs is no longer guaranteed -- check membership, not position.
        bar_sizes_requested = {call.kwargs["bar_size"] for call in provider.get_hourly_bars.call_args_list}
        assert "5min" in bar_sizes_requested
        assert result.short_term.ibkr_bar_size == "5min"
        assert len(result.short_term.ohlcv) == 1
        row = result.short_term.ohlcv.iloc[0]
        assert row["open"] == 100.0  # first bar's open
        assert row["close"] == 104.5  # last bar's close
        assert row["high"] == 105.0  # max high across all 5 bars
        assert row["low"] == 99.0  # min low across all 5 bars
        assert row["volume"] == 5000.0  # summed

    def test_prime_minute_count_falls_back_to_one_minute_bars(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(i, 100.0) for i in range(7)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("30m"),
            short_term=TimeframeInterval.parse("7m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.ibkr_bar_size == "1min"

    def test_hour_scale_interval_selects_the_matching_hourly_bar_size(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1w"),
            intermediate=TimeframeInterval.parse("480m"),
            short_term=TimeframeInterval.parse("240m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.ibkr_bar_size == "4h"
        assert result.intermediate.ibkr_bar_size == "8h"

    def test_empty_bars_returns_empty_frame_without_error(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = []
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.state == "available"
        assert result.short_term.ohlcv.empty

    def test_empty_bars_with_non_composable_interval_does_not_crash_on_resample(self, mocker) -> None:
        """Regression test (PR #311 review): a `"25m"` leg isn't one of IBKR's own native
        `bar` values, so `_fetch_leg` always resamples its raw bars (`chosen_minutes=5 !=
        interval.count=25`) even when IBKR returns zero bars for the window. Before this fix,
        `_bars_to_frame([])` returned a `pd.DataFrame` with a default `RangeIndex`, and
        `_resample_to_target` calling `.resample(...)` on that index raised a raw
        `TypeError: Only valid with DatetimeIndex, ...` instead of degrading gracefully --
        exactly the "never a raw exception surfaced to a caller" contract this module
        documents (checklist item 3)."""
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = []
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("100m"),
            short_term=TimeframeInterval.parse("25m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.state == "available"
        assert result.short_term.ibkr_bar_size == "5min"
        assert result.short_term.ohlcv.empty
        assert isinstance(result.short_term.ohlcv.index, pd.DatetimeIndex)


class TestGracefulDegradation:
    def test_provider_none_is_disabled_for_every_minute_unit_leg(self) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=None, conid=1)

        assert result.long_term.state == "disabled"
        assert result.long_term.ohlcv is None
        assert result.short_term.state == "disabled"
        assert result.short_term.ohlcv is None
        assert result.intermediate.state == "disabled"
        assert result.intermediate.ohlcv is None

    def test_gateway_unreachable_is_surfaced_not_raised(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.side_effect = IBKRUnavailableError("connection refused")
        provider.get_gateway_status.return_value = GatewayStatus(state="gateway_unreachable", detail="down")
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.state == "gateway_unreachable"
        assert result.short_term.detail == "down"
        assert result.short_term.ohlcv is None

    def test_not_authenticated_is_surfaced_not_raised(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.side_effect = IBKRUnavailableError("please log in")
        provider.get_gateway_status.return_value = GatewayStatus(state="not_authenticated", detail="please log in")
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.state == "not_authenticated"

    def test_transient_failure_against_an_available_gateway_is_unavailable_not_raised(self, mocker) -> None:
        """The gateway/session itself is fine (a fresh status check says `available`), but
        this specific history call failed -- this module's equivalent of
        app.api.routers.ibkr._resolve_ibkr_call_unavailable's HTTPException(503) case."""
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.side_effect = IBKRUnavailableError("HTTP 500 from /iserver/marketdata/history")
        provider.get_gateway_status.return_value = GatewayStatus(state="available")
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_bars_for_triple(triple, provider=provider, conid=1)

        assert result.short_term.state == "unavailable"
        assert "HTTP 500" in result.short_term.detail
        assert result.short_term.ohlcv is None


class TestGetIntradayHistoryBarsForTriple:
    """Tests for `get_intraday_history_bars_for_triple`
    (`backend-day-trader-timeframe-mode-history`) -- the walk-forward-*history* fetch, distinct
    from `get_intraday_bars_for_triple`'s own live-signal-snapshot fetch."""

    def test_default_lookback_is_the_much_larger_history_default_not_the_live_snapshot_default(
        self, mocker
    ) -> None:
        """Regression-discriminating: if this function silently delegated straight to
        `get_intraday_bars_for_triple` (or otherwise lost its own larger default), every leg
        would be requested with 30 days (the live-snapshot default) instead of 90 (or that
        leg's own smaller achievable-history clamp, for `"2min"` here -- see
        `TestMaxLookbackDaysForBarSize` for the exact bound arithmetic)."""
        from app.data.ibkr_provider import max_lookback_days_for_bar_size

        provider = mocker.create_autospec(IBKRProvider, instance=True)
        requested_lookback_days: dict[str, int] = {}

        def _get_hourly_bars(conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
            requested_lookback_days[bar_size] = lookback_days
            return [_bar(0, 100.0)]

        provider.get_hourly_bars.side_effect = _get_hourly_bars
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("60m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        result = get_intraday_history_bars_for_triple(triple, provider=provider, conid=1)

        assert result.long_term is not None
        assert result.long_term.state == "available"
        # "1h"/"10min" both have an achievable-history bound comfortably above 90 days (833.3
        # and 138.9 respectively), so neither is clamped -- the default 90 passes straight
        # through. "2min"'s own bound (27.8 days) is *below* 90, so it -- and only it -- is
        # clamped down; this is also proof this function's default really is 90, not 30 (the
        # live-snapshot default), since a 30-day request would never have exceeded "2min"'s own
        # 27.8-day bound and this clamp wouldn't have been observable at all.
        assert requested_lookback_days == {
            "1h": 90,
            "10min": 90,
            "2min": int(max_lookback_days_for_bar_size("2min")),
        }
        assert requested_lookback_days["2min"] < 90

    def test_clamps_lookback_days_per_leg_to_what_that_legs_granularity_can_ever_return(
        self, mocker
    ) -> None:
        """A caller requesting far more history than a fine-grained leg's own bar size could
        ever honor (per `IBKRProvider.max_lookback_days_for_bar_size`) must have that leg's own
        effective request clamped down -- proving this by actually inspecting the `lookback_days`
        `get_hourly_bars` was called with, not just that the call succeeded (a happy-path-only
        assertion here wouldn't catch the clamp being silently dropped)."""
        from app.data.ibkr_provider import max_lookback_days_for_bar_size

        provider = mocker.create_autospec(IBKRProvider, instance=True)
        requested_lookback_days: dict[str, int] = {}

        def _get_hourly_bars(conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
            requested_lookback_days[bar_size] = lookback_days
            return [_bar(0, 100.0)]

        provider.get_hourly_bars.side_effect = _get_hourly_bars
        # "7m" isn't evenly divisible by any IBKR-native bar size except 1min (a prime minute
        # count) -- `_select_ibkr_bar_size` falls back to `"1min"`, this app's finest, most
        # tightly-capped granularity.
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1d"),
            intermediate=TimeframeInterval.parse("30m"),
            short_term=TimeframeInterval.parse("7m"),
        )
        huge_request = 10_000

        result = get_intraday_history_bars_for_triple(
            triple, provider=provider, conid=1, lookback_days=huge_request
        )

        assert result.short_term is not None
        assert result.short_term.state == "available"
        expected_short_term_clamp = int(max_lookback_days_for_bar_size("1min"))
        expected_intermediate_clamp = int(max_lookback_days_for_bar_size("30min"))
        assert requested_lookback_days["1min"] == expected_short_term_clamp
        assert requested_lookback_days["30min"] == expected_intermediate_clamp
        # Both are clamped (neither leg's own achievable window reaches 10,000 days), but to
        # genuinely different values -- confirms the clamp is computed per-leg from that leg's
        # own chosen `bar_size`, not a single global cap applied uniformly regardless of
        # granularity (which would have clamped both to the same number).
        assert expected_short_term_clamp < expected_intermediate_clamp < huge_request

    def test_no_clamping_when_the_requested_lookback_is_comfortably_under_the_max(
        self, mocker
    ) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0)]
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("60m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )

        get_intraday_history_bars_for_triple(triple, provider=provider, conid=1, lookback_days=14)

        for call in provider.get_hourly_bars.call_args_list:
            assert call.kwargs["lookback_days"] == 14

    def test_day_and_week_unit_legs_still_need_no_ibkr_call(self, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("2w"),
            intermediate=TimeframeInterval.parse("3d"),
            short_term=TimeframeInterval.parse("1d"),
        )

        result = get_intraday_history_bars_for_triple(triple, provider=provider, conid=1)

        assert result.long_term is None
        assert result.intermediate is None
        assert result.short_term is None
        provider.get_hourly_bars.assert_not_called()


class TestGetActiveDayTraderIntradayHistoryBars:
    def test_none_when_mode_is_swing(self, session: Session, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)

        result = get_active_day_trader_intraday_history_bars(session, provider=provider, conid=1)

        assert result is None
        provider.get_hourly_bars.assert_not_called()

    def test_fetches_the_persisted_triple_with_the_history_default(
        self, session: Session, mocker
    ) -> None:
        from app.data.ibkr_provider import max_lookback_days_for_bar_size

        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        set_trading_mode_setting(session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=triple)
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0)]

        result = get_active_day_trader_intraday_history_bars(session, provider=provider, conid=999)

        assert result is not None
        assert result.long_term.state == "available"
        assert result.short_term.state == "available"
        assert result.intermediate.state == "available"
        # "25m"/"5m" both resolve to native "5min" bars (69.4-day bound); "2m" resolves to
        # native "2min" bars (27.8-day bound) -- both below the 90-day default, so every leg
        # here is clamped, each to its own bar size's own bound.
        expected_5min_clamp = int(max_lookback_days_for_bar_size("5min"))
        expected_2min_clamp = int(max_lookback_days_for_bar_size("2min"))
        for call in provider.get_hourly_bars.call_args_list:
            assert call.args[0] == 999
            if call.kwargs["bar_size"] == "5min":
                assert call.kwargs["lookback_days"] == expected_5min_clamp
            else:
                assert call.kwargs["bar_size"] == "2min"
                assert call.kwargs["lookback_days"] == expected_2min_clamp


class TestGetActiveDayTraderIntradayBars:
    def test_none_when_mode_is_swing(self, session: Session, mocker) -> None:
        provider = mocker.create_autospec(IBKRProvider, instance=True)

        result = get_active_day_trader_intraday_bars(session, provider=provider, conid=1)

        assert result is None
        provider.get_hourly_bars.assert_not_called()

    def test_none_when_day_trader_mode_has_no_configured_triple(self, session: Session, mocker) -> None:
        # Force mode=day_trader with no triple by writing the ORM row directly -- the
        # settings API itself never allows this combination (PUT rejects it), but
        # get_trading_mode_setting must still degrade sanely if it's ever encountered
        # (e.g. a hand-edited row, or a future migration path).
        from app.db.models import TradingModeSettingORM
        from app.time_utils import utcnow

        session.add(TradingModeSettingORM(id=1, mode="day_trader", updated_at=utcnow()))
        session.commit()
        provider = mocker.create_autospec(IBKRProvider, instance=True)

        result = get_active_day_trader_intraday_bars(session, provider=provider, conid=1)

        assert result is None
        provider.get_hourly_bars.assert_not_called()

    def test_fetches_the_persisted_triple_when_day_trader_mode_is_active(self, session: Session, mocker) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        set_trading_mode_setting(session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=triple)
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        provider.get_hourly_bars.return_value = [_bar(0, 100.0)]

        result = get_active_day_trader_intraday_bars(session, provider=provider, conid=999)

        assert result is not None
        assert result.long_term.state == "available"
        assert result.short_term.state == "available"
        assert result.intermediate.state == "available"
        for call in provider.get_hourly_bars.call_args_list:
            assert call.args[0] == 999
