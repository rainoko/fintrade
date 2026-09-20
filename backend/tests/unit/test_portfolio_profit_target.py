"""Tests for app.portfolio.profit_target (docs/Analyse.md §7, Elder ch. 53 "How to Set Profit
Targets" plus ch. 58's Tradebill formula).

`daily_ohlcv` throughout reuses the exact 5-row fixture already hand-verified in
tests/unit/test_portfolio_risk.py::TestProtectiveStop::test_reference_values_short_series
(close=[100, 102, 101, 103, 104], low=[99, 100, 99, 101, 102] -> protective stop
97.930612..., current price 104) so `distance_to_stop` here is derived from an
independently-verified number, not a fresh hand-computation.
"""

import pandas as pd
import pytest

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
        """No zones at all -- the channel (Tradebill) target is the only candidate. Channel
        height chosen so distance_to_target (13.0) is comfortably >= 2x distance_to_stop
        (~6.069388), i.e. a clean setup that passes the 2:1 sanity rule."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            channel_upper=147.333333,
            channel_lower=104.0,
        )

        assert target is not None
        assert target.source == "channel"
        assert target.price == pytest.approx(_CURRENT_PRICE + 13.0, abs=1e-4)
        assert target.distance_to_target == pytest.approx(13.0, abs=1e-4)
        assert target.distance_to_stop == pytest.approx(_EXPECTED_DISTANCE_TO_STOP, abs=1e-5)
        assert target.reward_risk_ratio == pytest.approx(13.0 / _EXPECTED_DISTANCE_TO_STOP, abs=1e-4)
        assert target.reward_risk_ratio >= 2.0
        assert target.meets_minimum_reward_risk is True

    def test_channel_target_is_entry_price_plus_30pct_of_channel_height(self) -> None:
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            channel_upper=110.0,
            channel_lower=100.0,
        )

        assert target is not None
        assert target.source == "channel"
        # height = 10.0 -> 30% = 3.0
        assert target.price == pytest.approx(_CURRENT_PRICE + 3.0, abs=1e-9)


class TestSupportResistanceTighterTarget:
    def test_support_resistance_gives_tighter_target_than_channel(self) -> None:
        """A resistance zone at 110 (distance 6.0 from current price 104) is tighter than the
        channel's own target 13.0 away -- the zone should win."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=110.0, upper=112.0)],
            channel_upper=147.333333,
            channel_lower=104.0,
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(110.0, abs=1e-9)
        assert target.distance_to_target == pytest.approx(6.0, abs=1e-9)

    def test_channel_wins_when_it_is_the_tighter_candidate(self) -> None:
        """Mirror of the above -- a zone far away (distance 30) loses to a channel target
        that's closer (distance 3)."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=134.0, upper=136.0)],
            channel_upper=110.0,
            channel_lower=100.0,
        )

        assert target is not None
        assert target.source == "channel"
        assert target.price == pytest.approx(_CURRENT_PRICE + 3.0, abs=1e-9)

    def test_zone_below_current_price_is_never_a_candidate(self) -> None:
        """A zone entirely at/below current price isn't a valid upside target -- only the
        channel candidate should be considered."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=90.0, upper=95.0), _zone(lower=104.0, upper=106.0)],
            channel_upper=110.0,
            channel_lower=100.0,
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
            channel_upper=None,
            channel_lower=None,
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(109.0, abs=1e-9)

    def test_nearest_of_multiple_qualifying_zones_is_used(self) -> None:
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[_zone(lower=140.0, upper=142.0), _zone(lower=109.0, upper=111.0)],
            channel_upper=None,
            channel_lower=None,
        )

        assert target is not None
        assert target.source == "support_resistance"
        assert target.price == pytest.approx(109.0, abs=1e-9)


class TestRewardRiskRatioFlagging:
    def test_failing_ratio_is_computed_and_flagged_not_hidden(self) -> None:
        """distance_to_target (3.0) / distance_to_stop (~6.069388) is well under 2.0 -- the
        ratio itself must still be a real, present number (not hidden/omitted), with
        meets_minimum_reward_risk explicitly False."""
        target = suggest_profit_target(
            _STOP_FIXTURE_DAILY_OHLCV,
            zones=[],
            channel_upper=110.0,
            channel_lower=100.0,
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
            channel_upper=110.0,
            channel_lower=100.0,
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
            channel_upper=None,
            channel_lower=None,
        )

        assert target is None

    def test_returns_none_when_daily_ohlcv_is_empty(self) -> None:
        target = suggest_profit_target(
            pd.DataFrame(columns=["close", "low"]),
            zones=[_zone(lower=110.0, upper=112.0)],
            channel_upper=110.0,
            channel_lower=100.0,
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
                channel_upper=110.0,
                channel_lower=100.0,
            )
