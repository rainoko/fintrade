"""End-to-end integration test for day-trader mode's generic portfolio-risk/profit-target/
exit-flag evaluation (`backend-day-trader-timeframe-mode-portfolio-risk`, checklist item 4):
global trading-mode settings persistence (`app.trading_mode`) -> mocked-IBKR intraday data
fetching (`app.data.day_trader_intraday`) -> `app.portfolio.risk.protective_stop` /
`app.portfolio.profit_target.suggest_profit_target` / `app.portfolio.exits.evaluate_exit_flags`,
run directly against the fetched intermediate/long-term legs -- the same "wired together exactly
as a future API-layer caller would, but exercised directly against the domain layer" shape
`tests/integration/test_day_trader_mode_signal_engine.py` already established for the signal
engine itself (no such API-layer wiring exists yet for the portfolio/risk layer -- see this
task's own `decisions` entry and `docs/architecture/Backend.md` §10's "Not yet landed" list).

No live network call: `IBKRProvider` is mocked at the same `get_hourly_bars` boundary the sibling
signal-engine integration test uses -- `FINTRADE_IBKR_ENABLED` stays `false` in `backend/.env`
throughout.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.data.day_trader_intraday import get_active_day_trader_intraday_bars
from app.data.ibkr_provider import IBKRBar, IBKRProvider
from app.indicators.autoenvelope import autoenvelope
from app.portfolio.exits import evaluate_exit_flags
from app.portfolio.models import Account, Equity, Position
from app.portfolio.profit_target import suggest_profit_target
from app.portfolio.risk import protective_stop
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import set_trading_mode_setting


def _bars(
    closes: list[float],
    *,
    lows: list[float] | None = None,
    start: datetime,
    step_minutes: int,
) -> list[IBKRBar]:
    lows = lows if lows is not None else [c - 1.0 for c in closes]
    return [
        IBKRBar(
            timestamp=start + timedelta(minutes=step_minutes * i),
            open=close,
            high=close + 1.0,
            low=lows[i],
            close=close,
            volume=1_000_000.0,
        )
        for i, close in enumerate(closes)
    ]


# The exact 5-bar fixture hand-verified in
# tests/unit/test_portfolio_risk.py::TestProtectiveStop::test_reference_values_short_series
# (protective_stop == 97.930612...) -- relabeled as 10-minute intraday bars (the intermediate
# leg), reused here so this integration test's own protective_stop assertion is checked against
# an independently-verified number, not a fresh hand-computation.
_INTERMEDIATE_CLOSES = [100.0, 102.0, 101.0, 103.0, 104.0]
_INTERMEDIATE_LOWS = [99.0, 100.0, 99.0, 101.0, 102.0]
_EXPECTED_STOP = 97.930612

# 120 bars of a mild uptrend with a periodic bump -- long enough to clear the Autoenvelope's
# ~100-bar average-deviation warm-up window, giving a real (non-NaN) channel at the latest bar
# -- relabeled as 60-minute intraday bars (the long_term leg).
_LONG_TERM_CLOSES = [100.0 + i * 0.3 + (50.0 if i % 3 == 0 else 0.0) for i in range(120)]

_SHORT_TERM_CLOSES = [95.5, 99.5]

_TRIPLE = TimeframeTriple(
    long_term=TimeframeInterval.parse("60m"),
    intermediate=TimeframeInterval.parse("10m"),
    short_term=TimeframeInterval.parse("2m"),
)


def _position() -> Position:
    return Position(
        id="pos_1",
        ticker="TEST",
        quantity=10.0,
        avg_cost_basis=100.0,
        entry_date=date(2026, 1, 1),
        current_price=104.0,
    )


def _account() -> Account:
    return Account(
        equity=Equity(cash=1000.0, positions_value=0.0, total=1000.0), positions=[]
    )


def _fetch_day_trader_legs(db_session: Session, mocker):
    set_trading_mode_setting(
        db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_TRIPLE
    )
    provider = mocker.create_autospec(IBKRProvider, instance=True)
    bars_by_native_size = {
        "1h": _bars(_LONG_TERM_CLOSES, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60),
        "10min": _bars(
            _INTERMEDIATE_CLOSES,
            lows=_INTERMEDIATE_LOWS,
            start=datetime(2026, 1, 5, tzinfo=UTC),
            step_minutes=10,
        ),
        "2min": _bars(_SHORT_TERM_CLOSES, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2),
    }
    provider.get_hourly_bars.side_effect = lambda conid, *, lookback_days, bar_size: (
        bars_by_native_size[bar_size]
    )
    fetched = get_active_day_trader_intraday_bars(db_session, provider=provider, conid=999)
    assert fetched is not None
    assert fetched.long_term is not None and fetched.long_term.state == "available"
    assert fetched.intermediate is not None and fetched.intermediate.state == "available"
    assert fetched.short_term is not None and fetched.short_term.state == "available"
    return fetched


class TestDayTraderModePortfolioRiskEndToEnd:
    def test_protective_stop_reads_the_intermediate_leg(
        self, db_session: Session, mocker
    ) -> None:
        """Ch. 39 p.161: stops live on the intermediate timeframe's own chart -- confirms
        `protective_stop` computed over the fetched intermediate leg (10-minute bars) matches
        the exact independently-verified swing-mode reference value, proving the same SafeZone
        math applies unchanged to a genuinely intraday-labeled frame."""
        fetched = _fetch_day_trader_legs(db_session, mocker)

        stop = protective_stop(_position(), fetched.intermediate.ohlcv)

        assert stop == pytest.approx(_EXPECTED_STOP, abs=1e-5)

    def test_profit_target_channel_reads_the_long_term_leg_not_the_intermediate_leg(
        self, db_session: Session, mocker
    ) -> None:
        """Ch. 39 p.161: profit targets use the long-term chart's own value zone -- confirms
        `suggest_profit_target`'s channel candidate, given the fetched long_term leg (60-minute
        bars) as its `weekly_ohlcv`-role argument, matches a directly-computed Autoenvelope pass
        over that SAME leg's own close series -- and genuinely differs from what the same call
        would produce if the intermediate leg were passed there instead, proving this is driven
        by which leg is actually supplied, not a hardcoded/ignored parameter."""
        fetched = _fetch_day_trader_legs(db_session, mocker)
        stop = protective_stop(_position(), fetched.intermediate.ohlcv)

        correct = suggest_profit_target(
            fetched.intermediate.ohlcv, zones=[], weekly_ohlcv=fetched.long_term.ohlcv, stop=stop
        )
        assert correct is not None
        assert correct.source == "channel"

        bands = autoenvelope(fetched.long_term.ohlcv["close"], ema_period=13)
        expected_height = float(bands["upper"].iloc[-1]) - float(bands["lower"].iloc[-1])
        current_price = float(fetched.intermediate.ohlcv["close"].iloc[-1])
        assert correct.price == pytest.approx(current_price + 0.30 * expected_height, abs=1e-5)

        # Discriminating counterpart: swapping in the INTERMEDIATE leg as the long-term-role
        # argument (simulating the exact regression this test exists to catch -- a future
        # caller wiring the wrong leg in) must produce a genuinely different outcome. The
        # intermediate leg only has 5 bars -- far short of the Autoenvelope's ~100-bar warm-up
        # window -- so swapping it in for the long-term role degrades all the way to "no channel
        # candidate at all" (`None`, no zones either) rather than merely a different price; this
        # is itself the discriminating proof that `weekly_ohlcv` is genuinely read (not ignored
        # in favor of some other already-available frame), since a truly-ignored parameter
        # couldn't distinguish "120 real bars" from "5 bars" in the first place.
        regressed = suggest_profit_target(
            fetched.intermediate.ohlcv,
            zones=[],
            weekly_ohlcv=fetched.intermediate.ohlcv,
            stop=stop,
        )
        assert regressed is None

    def test_evaluate_exit_flags_over_fetched_legs_runs_and_reads_the_long_term_leg(
        self, db_session: Session, mocker
    ) -> None:
        """Full pipeline sanity check: `evaluate_exit_flags` runs end to end over the fetched
        intermediate/long_term legs with no exception, and its `tide_flipped_bearish` flag is
        driven by the actual (real, unmocked `evaluate_tide`) long_term leg data -- confirmed
        directly against a fixture with a real, known flip, mirroring
        tests/unit/test_portfolio_exits.py::TestTideFlippedBearishIsTimeframeAgnostic."""
        fetched = _fetch_day_trader_legs(db_session, mocker)

        flags = evaluate_exit_flags(
            _position(), _account(), fetched.intermediate.ohlcv, fetched.long_term.ohlcv, 0.0
        )
        assert isinstance(flags, list)
        # The long_term fixture above is a steady mild uptrend with no flip -- must not fire.
        assert "tide_flipped_bearish" not in flags

        # Now with a long_term leg containing a genuine BULLISH -> BEARISH flip (a fresh IBKR
        # fetch under the same triple/mode, mocked separately) -- must fire.
        set_trading_mode_setting(
            db_session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=_TRIPLE
        )
        provider = mocker.create_autospec(IBKRProvider, instance=True)
        flip_closes = [100.0 * (1.05**i) for i in range(30)]
        flip_closes.append(flip_closes[-1] * 0.5)
        bars_by_native_size = {
            "1h": _bars(flip_closes, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=60),
            "10min": _bars(
                _INTERMEDIATE_CLOSES,
                lows=_INTERMEDIATE_LOWS,
                start=datetime(2026, 1, 5, tzinfo=UTC),
                step_minutes=10,
            ),
            "2min": _bars(_SHORT_TERM_CLOSES, start=datetime(2026, 1, 5, tzinfo=UTC), step_minutes=2),
        }
        provider.get_hourly_bars.side_effect = lambda conid, *, lookback_days, bar_size: (
            bars_by_native_size[bar_size]
        )
        flipped = get_active_day_trader_intraday_bars(db_session, provider=provider, conid=999)
        assert flipped is not None

        flags_after_flip = evaluate_exit_flags(
            _position(), _account(), flipped.intermediate.ohlcv, flipped.long_term.ohlcv, 0.0
        )
        assert "tide_flipped_bearish" in flags_after_flip
