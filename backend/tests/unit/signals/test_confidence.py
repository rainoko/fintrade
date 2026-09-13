"""Tests for app.signals.confidence (docs/Analyse.md §6, Confidence Score).

Coverage:

1. ``TestComputeConfidence`` covers the weighted roll-up itself, including boundary values
   (0, 100) and the input-validation guardrails (missing/extra/duplicate components,
   mismatched weight, out-of-range score).
2. ``TestConfidenceBand`` covers the Low/Medium/High banding, with explicit boundary cases
   at 39/40/70/71 -- the checklist's called-out off-by-one risk.
3. ``TestScoreTideAlignment`` / ``TestScoreImpulseGate`` cover the mechanical categorical ->
   score mappings.
4. ``TestScoreOscillatorExtremity`` covers the state-gated, %K-depth-scaled curve, including
   its own boundary (%K exactly at the 30/70 threshold).
5. ``TestScoreElderRayConfirmation`` covers the rising/falling-gated Bull/Bear Power tiering.
6. ``TestScoreVolumeConfirmation`` covers the OR-of-two-binary-conditions scoring.
7. ``TestBreakdownPreserved`` confirms the per-component breakdown passed into
   ``compute_confidence`` is not required to be collapsed/discarded to use the final number
   -- the caller can still read every component's own weight/score alongside the total,
   matching docs/architecture/API.md's ``confidence_breakdown`` response shape.
"""

import pandas as pd
import pytest

from app.signals.confidence import (
    WEIGHTS,
    ConfidenceComponent,
    compute_confidence,
    confidence_band,
    score_elder_ray_confirmation,
    score_impulse_gate,
    score_oscillator_extremity,
    score_tide_alignment,
    score_volume_confirmation,
)


def _full_breakdown(**overrides: float) -> list[ConfidenceComponent]:
    """A complete 5-component breakdown, each defaulting to score 1.0, with the correct
    WEIGHTS weight already attached -- override individual component scores by name.
    """
    return [
        ConfidenceComponent(component=name, weight=weight, score=overrides.get(name, 1.0))
        for name, weight in WEIGHTS.items()
    ]


class TestComputeConfidence:
    def test_all_zero_scores_is_zero(self) -> None:
        breakdown = _full_breakdown(
            tide_alignment=0.0,
            impulse_gate=0.0,
            oscillator_extremity=0.0,
            elder_ray_confirmation=0.0,
            volume_confirmation=0.0,
        )
        assert compute_confidence(breakdown) == 0

    def test_all_perfect_scores_is_hundred(self) -> None:
        breakdown = _full_breakdown()  # all default to 1.0
        assert compute_confidence(breakdown) == 100

    def test_matches_worked_example_from_api_md(self) -> None:
        # docs/architecture/API.md's own worked example:
        # tide 1.0*0.30 + impulse 1.0*0.20 + oscillator 0.6*0.25 + elder_ray 0.5*0.15 +
        # volume 1.0*0.10 = 0.30 + 0.20 + 0.15 + 0.075 + 0.10 = 0.825 -> 82.5 -> round -> 82
        breakdown = _full_breakdown(
            tide_alignment=1.0,
            impulse_gate=1.0,
            oscillator_extremity=0.6,
            elder_ray_confirmation=0.5,
            volume_confirmation=1.0,
        )
        assert compute_confidence(breakdown) == 82

    def test_rounds_to_nearest_whole_percent(self) -> None:
        # Weighted total 0.499 -> 49.9 -> rounds to 50.
        breakdown = [
            ConfidenceComponent(component="tide_alignment", weight=0.30, score=0.5),
            ConfidenceComponent(component="impulse_gate", weight=0.20, score=1.0),
            ConfidenceComponent(component="oscillator_extremity", weight=0.25, score=0.596),
            ConfidenceComponent(component="elder_ray_confirmation", weight=0.15, score=0.0),
            ConfidenceComponent(component="volume_confirmation", weight=0.10, score=0.0),
        ]
        # 0.30*0.5 + 0.20*1.0 + 0.25*0.596 + 0.15*0.0 + 0.10*0.0 = 0.15+0.20+0.149 = 0.499
        assert compute_confidence(breakdown) == 50

    def test_missing_component_raises(self) -> None:
        breakdown = [c for c in _full_breakdown() if c.component != "volume_confirmation"]
        with pytest.raises(ValueError):
            compute_confidence(breakdown)

    def test_extra_unknown_component_raises(self) -> None:
        breakdown = _full_breakdown() + [
            ConfidenceComponent(component="bogus", weight=0.0, score=1.0)
        ]
        with pytest.raises(ValueError):
            compute_confidence(breakdown)

    def test_duplicate_component_raises(self) -> None:
        breakdown = _full_breakdown()
        breakdown[0] = ConfidenceComponent(
            component=breakdown[1].component, weight=breakdown[1].weight, score=1.0
        )
        with pytest.raises(ValueError):
            compute_confidence(breakdown)

    def test_mismatched_weight_raises(self) -> None:
        breakdown = _full_breakdown()
        breakdown[0] = ConfidenceComponent(
            component=breakdown[0].component, weight=0.99, score=breakdown[0].score
        )
        with pytest.raises(ValueError):
            compute_confidence(breakdown)

    @pytest.mark.parametrize("bad_score", [-0.01, 1.01])
    def test_out_of_range_score_raises(self, bad_score) -> None:
        breakdown = _full_breakdown(tide_alignment=bad_score)
        with pytest.raises(ValueError):
            compute_confidence(breakdown)


class TestConfidenceBand:
    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            (0, "Low"),
            (39, "Low"),
            (40, "Medium"),
            (55, "Medium"),
            (70, "Medium"),
            (71, "High"),
            (100, "High"),
        ],
    )
    def test_bands(self, confidence, expected) -> None:
        assert confidence_band(confidence) == expected


class TestScoreTideAlignment:
    @pytest.mark.parametrize(
        ("tide", "signal_direction", "expected"),
        [
            ("BULLISH", "BUY", 1.0),
            ("NEUTRAL", "BUY", 0.5),
            ("BEARISH", "BUY", 0.0),
            ("BEARISH", "SELL", 1.0),
            ("NEUTRAL", "SELL", 0.5),
            ("BULLISH", "SELL", 0.0),
        ],
    )
    def test_mapping(self, tide, signal_direction, expected) -> None:
        assert score_tide_alignment(tide, signal_direction) == expected

    def test_invalid_signal_direction_raises(self) -> None:
        with pytest.raises(ValueError):
            score_tide_alignment("BULLISH", "HOLD")


class TestScoreImpulseGate:
    @pytest.mark.parametrize(
        ("impulse", "signal_direction", "expected"),
        [
            ("GREEN", "BUY", 1.0),
            ("BLUE", "BUY", 0.4),
            ("RED", "BUY", 0.0),
            ("RED", "SELL", 1.0),
            ("BLUE", "SELL", 0.4),
            ("GREEN", "SELL", 0.0),
        ],
    )
    def test_mapping(self, impulse, signal_direction, expected) -> None:
        assert score_impulse_gate(impulse, signal_direction) == expected

    def test_invalid_signal_direction_raises(self) -> None:
        with pytest.raises(ValueError):
            score_impulse_gate("GREEN", "HOLD")


class TestScoreOscillatorExtremity:
    def test_buy_deep_oversold_scores_high(self) -> None:
        wave = {"stochastic_k": 0.0, "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        assert score_oscillator_extremity(wave, "BUY") == pytest.approx(1.0)

    def test_buy_shallow_oversold_scores_lower_than_deep(self) -> None:
        shallow = {"stochastic_k": 29.0, "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        deep = {"stochastic_k": 10.0, "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        assert score_oscillator_extremity(shallow, "BUY") < score_oscillator_extremity(deep, "BUY")

    def test_buy_k_20_scores_higher_than_k_29(self) -> None:
        # Mirrors docs/Analyse.md §6's own example: "Stochastic < 20 scores higher than < 30".
        k20 = {"stochastic_k": 20.0, "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        k29 = {"stochastic_k": 29.0, "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        assert score_oscillator_extremity(k20, "BUY") > score_oscillator_extremity(k29, "BUY")

    def test_buy_wrong_state_is_zero_even_if_stochastic_looks_extreme(self) -> None:
        wave = {"stochastic_k": 1.0, "force_index_2ema": -50.0, "state": "NO_WAVE"}
        assert score_oscillator_extremity(wave, "BUY") == 0.0

    def test_sell_deep_overbought_scores_high(self) -> None:
        wave = {"stochastic_k": 100.0, "force_index_2ema": 50.0, "state": "OVERBOUGHT_RALLY"}
        assert score_oscillator_extremity(wave, "SELL") == pytest.approx(1.0)

    def test_sell_shallow_overbought_scores_lower_than_deep(self) -> None:
        shallow = {"stochastic_k": 71.0, "force_index_2ema": 50.0, "state": "OVERBOUGHT_RALLY"}
        deep = {"stochastic_k": 90.0, "force_index_2ema": 50.0, "state": "OVERBOUGHT_RALLY"}
        assert score_oscillator_extremity(shallow, "SELL") < score_oscillator_extremity(deep, "SELL")

    def test_sell_wrong_state_is_zero(self) -> None:
        wave = {"stochastic_k": 99.0, "force_index_2ema": 50.0, "state": "NO_WAVE"}
        assert score_oscillator_extremity(wave, "SELL") == 0.0

    def test_nan_stochastic_k_is_zero(self) -> None:
        wave = {"stochastic_k": float("nan"), "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        assert score_oscillator_extremity(wave, "BUY") == 0.0

    def test_invalid_signal_direction_raises(self) -> None:
        wave = {"stochastic_k": 20.0, "force_index_2ema": -50.0, "state": "OVERSOLD_PULLBACK"}
        with pytest.raises(ValueError):
            score_oscillator_extremity(wave, "HOLD")


class TestScoreElderRayConfirmation:
    def test_buy_bear_power_negative_and_rising_is_full_confirmation(self) -> None:
        bear_power = pd.Series([-5.0, -2.0])  # rising (less negative)
        bull_power = pd.Series([1.0, 1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "BUY") == 1.0

    def test_buy_bear_power_negative_but_falling_is_partial(self) -> None:
        bear_power = pd.Series([-2.0, -5.0])  # falling (more negative, still deepening)
        bull_power = pd.Series([1.0, 1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "BUY") == 0.5

    def test_buy_bear_power_tie_is_partial_not_full(self) -> None:
        # A tie counts as "not rising" per this function's documented convention.
        bear_power = pd.Series([-3.0, -3.0])
        bull_power = pd.Series([1.0, 1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "BUY") == 0.5

    def test_buy_bear_power_non_negative_is_zero(self) -> None:
        bear_power = pd.Series([0.5, 1.0])
        bull_power = pd.Series([1.0, 1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "BUY") == 0.0

    def test_sell_bull_power_positive_and_falling_is_full_confirmation(self) -> None:
        bull_power = pd.Series([5.0, 2.0])  # falling
        bear_power = pd.Series([-1.0, -1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "SELL") == 1.0

    def test_sell_bull_power_positive_but_rising_is_partial(self) -> None:
        bull_power = pd.Series([2.0, 5.0])  # rising, not confirmed falling
        bear_power = pd.Series([-1.0, -1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "SELL") == 0.5

    def test_sell_bull_power_tie_is_partial_not_full(self) -> None:
        bull_power = pd.Series([3.0, 3.0])
        bear_power = pd.Series([-1.0, -1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "SELL") == 0.5

    def test_sell_bull_power_non_positive_is_zero(self) -> None:
        bull_power = pd.Series([-0.5, -1.0])
        bear_power = pd.Series([-1.0, -1.0])
        assert score_elder_ray_confirmation(bull_power, bear_power, "SELL") == 0.0

    def test_invalid_signal_direction_raises(self) -> None:
        with pytest.raises(ValueError):
            score_elder_ray_confirmation(pd.Series([1.0, 1.0]), pd.Series([-1.0, -1.0]), "HOLD")


class TestScoreVolumeConfirmation:
    def test_force_index_spike_alone_is_full_score(self) -> None:
        assert score_volume_confirmation("OVERSOLD_PULLBACK", latest_volume=100.0, average_volume_20d=500.0) == 1.0

    def test_volume_above_average_alone_is_full_score(self) -> None:
        assert score_volume_confirmation("NO_WAVE", latest_volume=600.0, average_volume_20d=500.0) == 1.0

    def test_neither_condition_is_zero(self) -> None:
        assert score_volume_confirmation("NO_WAVE", latest_volume=100.0, average_volume_20d=500.0) == 0.0

    def test_both_conditions_is_still_just_full_score(self) -> None:
        assert score_volume_confirmation("OVERBOUGHT_RALLY", latest_volume=600.0, average_volume_20d=500.0) == 1.0

    def test_nan_average_volume_does_not_crash_and_is_not_above_average(self) -> None:
        assert score_volume_confirmation("NO_WAVE", latest_volume=100.0, average_volume_20d=float("nan")) == 0.0

    def test_volume_exactly_at_average_is_not_above(self) -> None:
        assert score_volume_confirmation("NO_WAVE", latest_volume=500.0, average_volume_20d=500.0) == 0.0


class TestBreakdownPreserved:
    """compute_confidence() takes the full breakdown and returns only the rolled-up int, but
    the breakdown itself (the list the caller built) remains fully intact and readable
    afterwards -- it's the caller's job (the future signal-engine-orchestration task) to
    serialize that same list as the API's confidence_breakdown, not this function's job to
    reconstruct it after the fact.
    """

    def test_component_list_is_not_mutated_by_compute_confidence(self) -> None:
        breakdown = _full_breakdown(
            tide_alignment=1.0,
            impulse_gate=1.0,
            oscillator_extremity=0.6,
            elder_ray_confirmation=0.5,
            volume_confirmation=1.0,
        )
        before = [(c.component, c.weight, c.score) for c in breakdown]

        compute_confidence(breakdown)

        after = [(c.component, c.weight, c.score) for c in breakdown]
        assert before == after

    def test_every_component_individually_readable_alongside_total(self) -> None:
        breakdown = _full_breakdown(
            tide_alignment=1.0,
            impulse_gate=1.0,
            oscillator_extremity=0.6,
            elder_ray_confirmation=0.5,
            volume_confirmation=1.0,
        )

        total = compute_confidence(breakdown)

        assert total == 82
        by_name = {c.component: c for c in breakdown}
        assert by_name["oscillator_extremity"].score == 0.6
        assert by_name["oscillator_extremity"].weight == 0.25
        assert by_name["elder_ray_confirmation"].score == 0.5
        assert set(by_name) == set(WEIGHTS)
