"""End-to-end integration test for day-trader mode's generic signal evaluation
(`backend-day-trader-timeframe-mode-signal-engine`, checklist item 4): global trading-mode
settings persistence (`app.trading_mode`) -> mocked-IBKR intraday data fetching
(`app.data.day_trader_intraday`) -> the generic Screen 1-3 + Impulse + confidence pipeline
(`app.signals.engine.analyse_day_trader`), wired together exactly as a future
`backend-day-trader-timeframe-mode-api` route would, but exercised directly against the domain
layer rather than through an HTTP endpoint (no such endpoint exists yet -- see this task's
`decisions` entry).

No live network call: `IBKRProvider` is mocked at the same method boundary
(`get_hourly_bars`) `tests/unit/data/test_day_trader_intraday.py` already uses, matching this
codebase's established IBKR test convention -- `FINTRADE_IBKR_ENABLED` stays `false` in
`backend/.env` throughout.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.data.day_trader_intraday import get_active_day_trader_intraday_bars
from app.data.ibkr_provider import IBKRBar, IBKRProvider
from app.signals.engine import analyse, analyse_day_trader
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


def _bars(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    *,
    start: datetime,
    step_minutes: int,
) -> list[IBKRBar]:
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


def _long_term_bars() -> list[IBKRBar]:
    """40 bars of accelerating 5%-per-bar growth -- a BULLISH weekly Impulse/Tide, matching
    tests/unit/signals/test_engine.py's own `TestAnalyseEndToEnd`
    weekly-tide-fixture convention, just relabeled as 60-minute intraday bars instead of
    calendar weeks (Screen 1's math is timeframe-agnostic -- see `evaluate_tide`'s own
    "generic over the active timeframe" docstring paragraph)."""
    closes = [100 * (1.05**i) for i in range(40)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    volumes = [1_000_000.0] * 40
    return _bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60)


def _intermediate_bars() -> list[IBKRBar]:
    """A real oversold-pullback-then-sharp-rally sequence -- the same fixture shape
    tests/unit/signals/test_engine.py's `TestAnalyseEndToEnd
    .test_end_to_end_buy_after_pullback_and_trigger` uses for `daily_ohlcv`, relabeled as
    10-minute intraday bars (Screen 2/the Impulse gate's math is likewise timeframe-agnostic --
    see `evaluate_wave`'s own docstring paragraph).

    Deliberately ends with a sharp rally bar (index -2, +8.0) *followed by* one more, slightly
    receding bar (index -1, -1.0) rather than ending on the rally bar itself: this makes the
    intermediate leg's own last two bars (close -1 vs. high -2: 101.5 vs. 102.8) NOT
    independently satisfy `evaluate_trigger`'s bullish crossing rule on their own, in contrast
    to `_short_term_bars()` below, whose own last two bars genuinely do cross. Before this
    fixture had the extra receding bar, PR #312's `pr-decision` review caught that the
    intermediate leg would *also* independently fire a bullish trigger with an identical
    end-to-end result either way -- meaning the test provided zero regression protection for
    `short_term_ohlcv` actually driving Screen 3 in day-trader mode (see
    `test_short_term_leg_genuinely_drives_the_trigger_not_the_intermediate_leg` below, which
    proves the discrimination directly)."""
    closes = [100 + i * 0.5 for i in range(20)]
    closes += [closes[-1] - 3 * i for i in range(1, 6)]
    closes.append(closes[-1] + 8.0)
    closes.append(closes[-1] - 1.0)
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    volumes = [1_000_000.0] * 25 + [9_000_000.0, 3_000_000.0]
    return _bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=10)


def _short_term_bars() -> list[IBKRBar]:
    """A genuine 2-minute buy-stop trigger: the latest bar's close crosses above the prior
    bar's high -- Elder's literal Screen 3 rule (not swing mode's daily-bar approximation),
    per `evaluate_trigger`'s own docstring."""
    closes = [95.5, 99.5]
    highs = [96.0, 100.0]
    lows = [94.0, 98.5]
    volumes = [500_000.0, 500_000.0]
    return _bars(closes, highs, lows, volumes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2)


class TestDayTraderModeSignalEngineEndToEnd:
    def test_fully_intraday_triple_produces_a_real_buy_signal(
        self, db_session: Session, mocker
    ) -> None:
        # A fully-intraday triple, matching ch. 39's own day-trading examples (25-min/5-min/
        # 2-min, 39-min/8-min) -- every leg needs `app.data.day_trader_intraday` (the
        # `long_term`-fetching extension this task adds), not just short_term/intermediate.
        # Every leg's interval count is itself one of IBKR's own native `bar` values (1h/
        # 10min/2min), so no client-side resampling happens here -- this test's own focus is
        # the trading_mode -> day_trader_intraday -> engine wiring end to end, not the
        # resampling reconciliation already covered by test_day_trader_intraday.py.
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("60m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=triple
        )

        provider = mocker.create_autospec(IBKRProvider, instance=True)
        bars_by_native_size = {
            "1h": _long_term_bars(),
            "10min": _intermediate_bars(),
            "2min": _short_term_bars(),
        }

        def _get_hourly_bars(conid: int, *, lookback_days: int, bar_size: str) -> list[IBKRBar]:
            assert conid == 999  # the resolved conid is threaded straight through, unchanged
            return bars_by_native_size[bar_size]

        provider.get_hourly_bars.side_effect = _get_hourly_bars

        fetched = get_active_day_trader_intraday_bars(db_session, provider=provider, conid=999)

        assert fetched is not None
        assert fetched.long_term is not None
        assert fetched.long_term.state == "available"
        assert fetched.intermediate is not None
        assert fetched.intermediate.state == "available"
        assert fetched.short_term is not None
        assert fetched.short_term.state == "available"

        result = analyse_day_trader(
            "TEST",
            long_term_ohlcv=fetched.long_term.ohlcv,
            intermediate_ohlcv=fetched.intermediate.ohlcv,
            short_term_ohlcv=fetched.short_term.ohlcv,
        )

        assert result.screens["tide"]["trend"] == "BULLISH"
        assert result.screens["impulse"] != "RED"
        assert result.screens["wave"]["showed_pullback_in_lookback"] is True
        # The literal short-term-timeframe trigger fires -- driven by `short_term_ohlcv`
        # (2-minute bars), not `intermediate_ohlcv` (10-minute bars). See
        # `test_short_term_leg_genuinely_drives_the_trigger_not_the_intermediate_leg` below for
        # the actual discriminating proof that this fixture's intermediate leg would NOT fire
        # this same trigger on its own -- this assertion alone doesn't prove that.
        assert bool(result.screens["trigger"]["fired"]) is True
        assert result.screens["trigger"]["reference"] == "close_above_prior_high"
        assert result.signal == "BUY"
        assert 0 <= result.confidence <= 100
        assert result.confidence_band in ("Low", "Medium", "High")
        assert len(result.breakdown) == 5

    def test_short_term_leg_genuinely_drives_the_trigger_not_the_intermediate_leg(
        self, db_session: Session, mocker
    ) -> None:
        """Discriminating regression test for `backend-day-trader-timeframe-mode-signal-engine`
        PR #312's `pr-decision` review finding: the sibling
        `test_fully_intraday_triple_produces_a_real_buy_signal` test alone doesn't prove
        `short_term_ohlcv` (not `intermediate_ohlcv`) drives Screen 3 in day-trader mode,
        because (before this test was added) the fixtures' intermediate leg would *also*
        independently fire the same bullish trigger -- so wiring `short_term_ohlcv` correctly
        vs. dropping it entirely (a plausible regression: `engine.py`'s
        ``trigger_ohlcv = daily_ohlcv if short_term_ohlcv is None else short_term_ohlcv``
        silently falling back to the intermediate leg) produced byte-identical results on every
        assertion.

        This test uses the exact same fixtures as that sibling test but calls the engine two
        different ways and asserts the results genuinely differ:

        1. Correct wiring, `analyse_day_trader(..., short_term_ohlcv=short_term)` -- Screen 3
           reads the real 2-minute leg, whose own last two bars cross (close 99.5 > prior high
           96.0) -> trigger fires -> BUY.
        2. Simulated regression, plain `analyse(ticker, intermediate_ohlcv, long_term_ohlcv)`
           with no `short_term_ohlcv` at all -- Screen 3 falls back to the intermediate leg,
           whose own last two bars do NOT cross (close 101.5 <= prior high 102.8, per
           `_intermediate_bars()`'s own docstring) -> trigger does not fire -> HOLD (Tide/Wave/
           Impulse are otherwise identical between the two calls, since only the trigger input
           differs -- confirming this is a genuine causal effect of which leg drives Trigger,
           not simply the two calls not lining up).
        """
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("60m"),
            intermediate=TimeframeInterval.parse("10m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=triple
        )

        provider = mocker.create_autospec(IBKRProvider, instance=True)
        bars_by_native_size = {
            "1h": _long_term_bars(),
            "10min": _intermediate_bars(),
            "2min": _short_term_bars(),
        }
        provider.get_hourly_bars.side_effect = lambda conid, *, lookback_days, bar_size: (
            bars_by_native_size[bar_size]
        )

        fetched = get_active_day_trader_intraday_bars(db_session, provider=provider, conid=999)
        assert fetched is not None
        assert fetched.long_term is not None
        assert fetched.intermediate is not None
        assert fetched.short_term is not None

        # Sanity-check the discriminating premise directly against the fixture data itself,
        # not just the engine's output -- if either of these ever flipped, the assertions below
        # would no longer be proving what this test claims to prove.
        intermediate_ohlcv = fetched.intermediate.ohlcv
        assert intermediate_ohlcv["close"].iloc[-1] <= intermediate_ohlcv["high"].iloc[-2]
        short_term_ohlcv = fetched.short_term.ohlcv
        assert short_term_ohlcv["close"].iloc[-1] > short_term_ohlcv["high"].iloc[-2]

        correct = analyse_day_trader(
            "TEST",
            long_term_ohlcv=fetched.long_term.ohlcv,
            intermediate_ohlcv=intermediate_ohlcv,
            short_term_ohlcv=short_term_ohlcv,
        )
        regressed = analyse("TEST", intermediate_ohlcv, fetched.long_term.ohlcv)

        assert bool(correct.screens["trigger"]["fired"]) is True
        assert bool(regressed.screens["trigger"]["fired"]) is False
        assert correct.signal == "BUY"
        assert regressed.signal == "HOLD"
        # Tide/Wave/Impulse are unaffected by which leg drives Trigger -- confirms the two
        # results differ *only* because of the trigger-input wiring, not some unrelated
        # divergence between the two calls.
        assert correct.screens["tide"] == regressed.screens["tide"]
        assert correct.screens["wave"] == regressed.screens["wave"]
        assert correct.screens["impulse"] == regressed.screens["impulse"]

    def test_swing_mode_is_unaffected_by_day_trader_wiring(self, db_session: Session) -> None:
        """The default global setting is `swing`, with no configured triple -- confirms this
        test module's own setup doesn't accidentally leak day-trader state, matching every
        existing swing-mode test's implicit assumption."""
        fetched = get_active_day_trader_intraday_bars(db_session, provider=None, conid=1)

        assert fetched is None
