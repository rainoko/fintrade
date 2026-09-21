"""Tests for app.portfolio.profit_target (docs/Analyse.md §7, Elder ch. 53 "How to Set Profit
Targets" plus ch. 58's Tradebill formula, ch. 39 p.161's weekly-vs-daily timeframe rule).

`daily_ohlcv` throughout reuses the exact 5-row fixture already hand-verified in
tests/unit/test_portfolio_risk.py::TestProtectiveStop::test_reference_values_short_series
(close=[100, 102, 101, 103, 104], low=[99, 100, 99, 101, 102] -> protective stop
97.930612..., current price 104) so `distance_to_stop` here is derived from an
independently-verified number, not a fresh hand-computation.

Channel-based target tests below similarly reuse an already-independently-verified building
block rather than re-deriving it from scratch here: `app.indicators.autoenvelope.autoenvelope`
itself is exhaustively hand-verified (via a standalone, pandas-free loop) in
tests/unit/indicators/test_autoenvelope.py, so the expected weekly channel bounds for a given
`weekly_ohlcv` fixture are computed here by calling that already-verified function directly --
hand-deriving its ~100-week rolling-average-deviation formula a second time, from scratch, over
a 120-row fixture would be impractical and wouldn't catch anything `test_autoenvelope.py`
doesn't already catch. What IS newly verified here, hand-computed from first principles, is
`suggest_profit_target`'s own composition logic on top of that channel: the entry-price + 30%
formula, that the channel comes from `weekly_ohlcv` (not `daily_ohlcv`), the
tighter-of-two-candidates selection, and the reward:risk arithmetic -- see the
backend-profit-target-weekly-channel task's `decisions` entry.
"""

import pandas as pd
import pytest

from app.indicators.autoenvelope import autoenvelope
from app.portfolio.profit_target import suggest_profit_target
from app.signals.support_resistance import Zone

_STOP_FIXTURE_DAILY_OHLCV = pd.DataFrame(
    {
        "close": [100.0, 102.0, 101.0, 103.0, 104.0],
        "low": [99.0, 100.0, 99.0, 101.0, 102.0],
    }
)
_CURRENT_PRICE = 104.0
_EXPECTED_STOP = 97.930612
_EXPECTED_DISTANCE_TO_STOP = _CURRENT_PRICE - _EXPECTED_STOP  # ~6.069388

# 120 weekly bars -- long enough to clear the Autoenvelope's ~100-week average-deviation
# warm-up window (autoenvelope's own default deviation_lookback=100), so the latest bar has a
# real (non-NaN), wide channel: a periodic +50 bump every 3rd bar on top of a mild uptrend.
# Expected bounds computed below via autoenvelope() itself (see this module's own docstring for
# why that's the reference here, not a from-scratch hand-derivation).
_WEEKLY_OHLCV_WIDE_CHANNEL = pd.DataFrame(
    {"close": [100.0 + i * 0.3 + (50.0 if i % 3 == 0 else 0.0) for i in range(120)]}
)
# Same warm-up length, milder +2 bump every 7th bar -> a real but much NARROWER channel.
_WEEKLY_OHLCV_NARROW_CHANNEL = pd.DataFrame(
    {"close": [100.0 + i * 0.3 + (2.0 if i % 7 == 0 else 0.0) for i in range(120)]}
)
# Only 26 weeks (this app's own documented minimum weekly history) -- far short of the
# Autoenvelope's ~100-week warm-up window, so the channel is NaN ("unavailable") at every bar.
_WEEKLY_OHLCV_TOO_SHORT_FOR_CHANNEL = pd.DataFrame({"close": [100.0 + i * 0.5 for i in range(26)]})


def _expected_channel_bounds(weekly_ohlcv: pd.DataFrame) -> tuple[float, float]:
    bands = autoenvelope(weekly_ohlcv["close"], ema_period=13)
    return float(bands["upper"].iloc[-1]), float(bands["lower"].iloc[-1])


_WIDE_UPPER, _WIDE_LOWER = _expected_channel_bounds(_WEEKLY_OHLCV_WIDE_CHANNEL)
_WIDE_HEIGHT = _WIDE_UPPER - _WIDE_LOWER  # ~43.17
_NARROW_UPPER, _NARROW_LOWER = _expected_channel_bounds(_WEEKLY_OHLCV_NARROW_CHANNEL)
_NARROW_HEIGHT = _NARROW_UPPER - _NARROW_LOWER  # ~4.08


def _zone(lower: float, upper: float, role: str = "resistance") -> Zone:
    ts = pd.Timestamp("2026-01-01")
    return Zone(
        role=role,  # type: ignore[arg-type]
        upper=upper,
        lower=lower,
        first_touch_date=ts,
        last_touch_date=ts,
        touch_count=2,
        length_days=14,
        length_category="minor",
        height_pct=1.0,
        height_category="minor",
        dollar_volume=0.0,
        strength_score=50.0,
    )


class TestChannelBasedTarget:
    def test_buy_near_clean_value_zone_uses_channel_target_and_passes_ratio(self) -> None:
        """No zones at all -- the channel (Tradebill) target is the only candidate. The wide
        weekly channel's height (~43.17) puts distance_to_target (~12.95) comfortably >= 2x
        distance_to_stop (~6.069388), i.e. a clean setup that passes the 2:1 sanity rule."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            weekly_ohlcv=_WEEKLY_OHLCV_WIDE_CHANNEL,
        )

        assert target is not None
        assert target.source == "channel"
        expected_distance = 0.30 * _WIDE_HEIGHT
        assert target.price == pytest.approx(_CURRENT_PRICE + expected_distance, abs=1e-6)
        assert target.distance_to_target == pytest.approx(expected_distance, abs=1e-6)
        assert target.distance_to_stop == pytest.approx(_EXPECTED_DISTANCE_TO_STOP, abs=1e-5)
        assert target.reward_risk_ratio == pytest.approx(
            expected_distance / _EXPECTED_DISTANCE_TO_STOP, abs=1e-4
        )
        assert target.reward_risk_ratio >= 2.0
        assert target.meets_minimum_reward_risk is True

    def test_channel_target_is_entry_price_plus_30pct_of_channel_height(self) -> None:
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
        )

        assert target is not None
        assert target.source == "channel"
        assert target.price == pytest.approx(_CURRENT_PRICE + 0.30 * _NARROW_HEIGHT, abs=1e-6)

    def test_channel_is_derived_from_weekly_ohlcv_not_daily_ohlcv(self) -> None:
        """The channel candidate must come from `weekly_ohlcv`, not `daily_ohlcv` -- per Elder
        ch. 39 p.161's explicit weekly-value-zone rule (this task's own fix). A `daily_ohlcv`
        long enough to itself clear a ~100-bar Autoenvelope warm-up must NOT produce a channel
        candidate when `weekly_ohlcv` is too short for its own warm-up -- proving the channel
        isn't silently falling back to (or still being sourced from) daily data."""
        long_daily_ohlcv = pd.DataFrame(
            {
                "close": [100.0 + i * 0.3 for i in range(150)],
                "low": [99.0 + i * 0.3 for i in range(150)],
            }
        )

        target = suggest_profit_target(
            long_daily_ohlcv,
            zones=[],
            weekly_ohlcv=_WEEKLY_OHLCV_TOO_SHORT_FOR_CHANNEL,
        )

        assert target is None

    def test_insufficient_weekly_history_yields_no_channel_candidate(self) -> None:
        """A too-short `weekly_ohlcv` (fewer than the ~100-week warm-up window) leaves the
        channel candidate unavailable -- the same graceful degradation the daily channel used
        to have -- so only a qualifying support/resistance zone can still produce a target."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=109.0, upper=111.0)],
            weekly_ohlcv=_WEEKLY_OHLCV_TOO_SHORT_FOR_CHANNEL,
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(109.0, abs=1e-9)


class TestSupportResistanceTighterTarget:
    def test_support_resistance_gives_tighter_target_than_channel(self) -> None:
        """A resistance zone at 110 (distance 6.0 from current price 104) is tighter than the
        wide channel's own target (~12.95 away) -- the zone should win."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=110.0, upper=112.0)],
            weekly_ohlcv=_WEEKLY_OHLCV_WIDE_CHANNEL,
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(110.0, abs=1e-9)
        assert target.distance_to_target == pytest.approx(6.0, abs=1e-9)

    def test_channel_wins_when_it_is_the_tighter_candidate(self) -> None:
        """Mirror of the above -- a zone far away (distance 30) loses to the narrow channel's
        own much closer target (~1.22 away)."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=134.0, upper=136.0)],
            weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
        )

        assert target is not None
        assert target.source == "channel"
        assert target.price == pytest.approx(_CURRENT_PRICE + 0.30 * _NARROW_HEIGHT, abs=1e-6)

    def test_zone_below_current_price_is_never_a_candidate(self) -> None:
        """A zone entirely at/below current price isn't a valid upside target -- only the
        channel candidate should be considered."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=90.0, upper=95.0), _zone(lower=104.0, upper=106.0)],
            weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
        )

        assert target is not None
        assert target.source == "channel"

    def test_a_support_labeled_zone_above_current_price_still_qualifies(self) -> None:
        """`_nearest_resistance_price` filters by each zone's own price POSITION relative to
        current price, not by its `role` label -- a `role='support'` zone that happens to sit
        above current price (role and position rarely coincide, but the code deliberately
        doesn't rely on that coincidence, per this module's own docstring and this task's
        `decisions` entry) must still be picked up as a candidate."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=109.0, upper=111.0, role="support")],
            weekly_ohlcv=pd.DataFrame(),
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(109.0, abs=1e-9)

    def test_nearest_of_multiple_qualifying_zones_is_used(self) -> None:
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=140.0, upper=142.0), _zone(lower=109.0, upper=111.0)],
            weekly_ohlcv=pd.DataFrame(),
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(109.0, abs=1e-9)


class TestRewardRiskRatioFlagging:
    def test_failing_ratio_is_computed_and_flagged_not_hidden(self) -> None:
        """distance_to_target (~1.22, the narrow channel's 30% height) / distance_to_stop
        (~6.069388) is well under 2.0 -- the ratio itself must still be a real, present number
        (not hidden/omitted), with meets_minimum_reward_risk explicitly False."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
        )

        assert target is not None
        assert target.reward_risk_ratio is not None
        assert target.reward_risk_ratio < 2.0
        assert target.meets_minimum_reward_risk is False

    def test_non_positive_distance_to_stop_gives_null_ratio_and_false_flag(self) -> None:
        """A degenerate single-row series where current price sits exactly at its own
        computed stop (distance_to_stop == 0) -- the ratio is undefined (None), and
        meets_minimum_reward_risk must still be a concrete False, not left null too."""
        daily_ohlcv = pd.DataFrame({"close": [100.0], "low": [100.0]})

        target = suggest_profit_target(
            daily_ohlcv,
            zones=[],
            weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
        )

        assert target is not None
        assert target.distance_to_stop == pytest.approx(0.0, abs=1e-9)
        assert target.reward_risk_ratio is None
        assert target.meets_minimum_reward_risk is False


class TestNoCandidateOrEmptyInput:
    def test_returns_none_when_no_channel_and_no_qualifying_zone(self) -> None:
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            weekly_ohlcv=pd.DataFrame(),
        )

        assert target is None

    def test_returns_none_when_daily_ohlcv_is_empty(self) -> None:
        target = suggest_profit_target(
            pd.DataFrame(columns=["close", "low"]),
            zones=[_zone(lower=110.0, upper=112.0)],
            weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
        )

        assert target is None

    def test_non_empty_frame_missing_close_column_raises_value_error_not_key_error(self) -> None:
        """A non-empty `daily_ohlcv` missing `close` must raise the documented `ValueError`
        (validated up front via `app.portfolio.risk.validate_daily_ohlcv_columns`), not a bare
        `KeyError` from `current_price`'s own column read -- see this task's `decisions`
        entry."""
        daily_ohlcv = pd.DataFrame({"low": [99.0, 100.0]})

        with pytest.raises(ValueError, match="close"):
            suggest_profit_target(
                daily_ohlcv,
                zones=[],
                weekly_ohlcv=_WEEKLY_OHLCV_NARROW_CHANNEL,
            )
