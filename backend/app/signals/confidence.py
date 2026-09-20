from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.signals.triple_screen import STOCHASTIC_OVERBOUGHT, STOCHASTIC_OVERSOLD

# Weights per docs/Analyse.md §6 — must sum to 1.0.
WEIGHTS: dict[str, float] = {
    "tide_alignment": 0.30,
    "impulse_gate": 0.20,
    "oscillator_extremity": 0.25,
    "elder_ray_confirmation": 0.15,
    "volume_confirmation": 0.10,
}


@dataclass
class ConfidenceComponent:
    component: str
    weight: float
    score: float  # 0.0-1.0


def compute_confidence(components: list[ConfidenceComponent]) -> int:
    """Weighted composite score, 0-100 (docs/Analyse.md §6). Not a statistical probability.

    ``components`` must contain exactly the five components named in ``WEIGHTS`` (no more,
    no fewer, no duplicates), each carrying the matching weight from ``WEIGHTS`` and a score
    in [0.0, 1.0] -- this function only performs the ``Σ(component_score × weight)`` roll-up
    documented in docs/Analyse.md §6, it does not itself decide which components exist or
    what they're worth; see this task's `decisions` entry on docs/tasks/confidence-scoring.json
    for why mismatches raise ``ValueError`` here rather than silently summing whatever's given
    (a caller that drops or double-weights a component is a bug worth catching immediately,
    not a confidence score that's quietly wrong).

    Rounds to the nearest whole percent using Python's built-in ``round()`` (banker's
    rounding, i.e. exact .5 ties round to the nearest *even* integer) -- docs/Analyse.md §6
    says only "round to nearest whole percent" and gives no tie-breaking rule, so the
    language's own default was kept rather than introducing a custom round-half-up; see the
    same decisions entry.
    """
    seen = [c.component for c in components]
    if len(seen) != len(set(seen)) or set(seen) != set(WEIGHTS):
        raise ValueError(
            f"components must contain exactly {sorted(WEIGHTS)}, got {sorted(seen)}"
        )
    for component in components:
        expected_weight = WEIGHTS[component.component]
        if component.weight != expected_weight:
            raise ValueError(
                f"{component.component}: weight {component.weight} does not match "
                f"WEIGHTS[{component.component}] = {expected_weight}"
            )
        if not 0.0 <= component.score <= 1.0:
            raise ValueError(f"{component.component}: score {component.score} out of [0.0, 1.0]")

    total = sum(component.weight * component.score for component in components)
    return round(total * 100)


def confidence_band(confidence: int) -> Literal["Low", "Medium", "High"]:
    """'Low' (<40) | 'Medium' (40-70) | 'High' (>70) (docs/Analyse.md §6).

    Both band edges (40 and 70) are inclusive to "Medium" per the doc's own "40–70% =
    Medium" phrasing -- so confidence 40 and confidence 70 both classify as Medium, not
    Low/High respectively (see this task's `decisions` entry on the off-by-one boundary
    interpretation this text otherwise leaves ambiguous).
    """
    if confidence < 40:
        return "Low"
    if confidence <= 70:
        return "Medium"
    return "High"


def score_tide_alignment(tide: str, signal_direction: str) -> float:
    """Screen 1 (Tide) component score (docs/Analyse.md §6, weight 30%).

    ``evaluate_tide`` (app.signals.triple_screen) only ever returns BULLISH / BEARISH /
    NEUTRAL -- the doc's "100% if Tide agrees with the signal direction; 50% if Neutral
    (weekly Impulse Blue); 0% if Tide contradicts" already collapses onto that same
    three-way output, since a weekly EMA(13)/MACD-Histogram direction disagreement (or too
    little weekly history) is exactly what makes ``evaluate_tide`` return NEUTRAL in the
    first place. So this is a direct, mechanical mapping: tide agreeing with
    ``signal_direction`` scores 1.0, NEUTRAL scores 0.5, and tide contradicting
    ``signal_direction`` scores 0.0.
    """
    if signal_direction not in ("BUY", "SELL"):
        raise ValueError(f"signal_direction must be 'BUY' or 'SELL', got {signal_direction!r}")

    agrees = "BULLISH" if signal_direction == "BUY" else "BEARISH"
    contradicts = "BEARISH" if signal_direction == "BUY" else "BULLISH"
    if tide == agrees:
        return 1.0
    if tide == contradicts:
        return 0.0
    return 0.5


def score_impulse_gate(impulse: str, signal_direction: str) -> float:
    """Impulse System component score (docs/Analyse.md §6, weight 20%).

    Direct mapping from ``evaluate_impulse``'s GREEN/RED/BLUE output: the color matching
    ``signal_direction`` (Green for Buy, Red for Sell) scores 1.0, Blue scores 0.4, and the
    opposite color scores 0.0 -- matching the doc's table exactly. Note the opposite-color
    case should already be unreachable in practice (signal-engine-orchestration's Impulse
    gate blocks a fresh Buy under Red / Sell under Green before a signal is even emitted,
    per docs/Analyse.md §3) but this function still scores it rather than raising, since
    ``compute_confidence`` may legitimately be called standalone (e.g. in tests) without
    that upstream gate having run.
    """
    if signal_direction not in ("BUY", "SELL"):
        raise ValueError(f"signal_direction must be 'BUY' or 'SELL', got {signal_direction!r}")

    matching_color = "GREEN" if signal_direction == "BUY" else "RED"
    opposite_color = "RED" if signal_direction == "BUY" else "GREEN"
    if impulse == matching_color:
        return 1.0
    if impulse == opposite_color:
        return 0.0
    return 0.4


def score_oscillator_extremity(wave: dict, signal_direction: str) -> float:
    """Screen 2 (Wave) oscillator-extremity component score (docs/Analyse.md §6, weight 25%).

    ``wave`` is the dict shape returned by ``evaluate_wave``/documented in
    docs/architecture/API.md's ``screens.wave``: ``{"stochastic_k": float,
    "force_index_2ema": float, "state": str}``.

    docs/Analyse.md §6 says this component is "scaled by how deep into oversold/overbought
    territory Stochastic + Force Index are (e.g., Stochastic < 20 scores higher than < 30)"
    but gives no formula -- see this task's `decisions` entry on docs/tasks/confidence-scoring.json
    for the chosen curve and for why it's driven by Stochastic %K depth alone rather than
    also blending in Force Index magnitude directly:

    - If ``wave["state"]`` doesn't match the setup ``signal_direction`` needs
      (``OVERSOLD_PULLBACK`` for BUY, ``OVERBOUGHT_RALLY`` for SELL), the score is 0.0 --
      ``evaluate_wave`` already requires *both* a qualifying Stochastic reading *and* a
      Force Index spike (docs/Analyse.md §2) to reach either of those states, so the state
      field alone already encodes "Force Index confirms too", and a mismatched/NO_WAVE
      state means no oscillator setup is present for this signal at all, regardless of how
      extreme %K happens to look in isolation.
    - Otherwise, the score scales linearly with how far %K sits beyond its 30/70 threshold:
      ``(30 - k) / 30`` for an oversold BUY setup, ``(k - 70) / 30`` for an overbought SELL
      setup, clamped to [0.0, 1.0] -- so %K == 20 (comfortably < 30) scores higher than
      %K == 29 (barely < 30), matching the doc's own "< 20 scores higher than < 30" example.

    Force Index's *magnitude* (as opposed to its already-gated spike/no-spike role via
    ``state``) isn't blended into the continuous scale: unlike the Stochastic 0-100 range,
    Force Index has no ticker-independent reference scale here to normalize a raw magnitude
    against (``_is_force_index_spike`` in triple_screen.py normalizes against a *rolling
    standard deviation of the full historical series*, which this function -- given only the
    latest scalar snapshot per the documented ``screens.wave`` shape -- doesn't have access
    to). Re-deriving that normalization here would need the same historical series and would
    duplicate triple_screen.py's own spike logic rather than reusing it.
    """
    if signal_direction not in ("BUY", "SELL"):
        raise ValueError(f"signal_direction must be 'BUY' or 'SELL', got {signal_direction!r}")

    stochastic_k = wave["stochastic_k"]
    if pd.isna(stochastic_k):
        return 0.0

    if signal_direction == "BUY":
        if wave["state"] != "OVERSOLD_PULLBACK":
            return 0.0
        depth = (STOCHASTIC_OVERSOLD - stochastic_k) / STOCHASTIC_OVERSOLD
    else:
        if wave["state"] != "OVERBOUGHT_RALLY":
            return 0.0
        depth = (stochastic_k - STOCHASTIC_OVERBOUGHT) / (100.0 - STOCHASTIC_OVERBOUGHT)

    return max(0.0, min(1.0, depth))


def score_elder_ray_confirmation(bull_power: pd.Series, bear_power: pd.Series, signal_direction: str) -> float:
    """Elder-Ray confirmation component score (docs/Analyse.md §6, weight 15%).

    docs/Analyse.md §2 states the confirmation cue in trend terms, not just sign: "in an
    uptrend, look for Bear Power to be negative but rising (weak dip) as a buy cue; in a
    downtrend, Bull Power positive but falling as a sell cue" -- the *trajectory* (rising vs.
    falling), not merely the current sign, is what §2 calls a confirmed "exhaustion-then-
    reversal pattern". A same-day sign test alone (e.g. "bull_power > 0 and bear_power < 0")
    can't distinguish that pattern from an ordinary trending day where the daily range simply
    straddles the EMA(13), which is common and not itself a confirmation signal -- see this
    task's `decisions` entry on docs/tasks/confidence-scoring.json for why this function
    therefore takes ``bull_power``/``bear_power`` as ``pd.Series`` (at least the last two
    bars) rather than scalars, and reuses the same last-two-points "rising"/"falling"
    direction convention as ``app.signals.impulse._direction`` (a tie counts as "falling",
    i.e. not yet demonstrated to be recovering) for consistency with that existing precedent.

    Scoring (mirroring the 100/50/0 tiering docs/Analyse.md §6 already uses for tide
    alignment):

    - BUY: Bear Power negative *and* rising (the dip is there and easing) → 1.0. Bear Power
      negative but not rising (still deepening -- exhaustion not yet confirmed reversing) →
      0.5. Bear Power non-negative (no dip below the EMA at all -- pattern absent) → 0.0.
    - SELL (mirror, on Bull Power): positive and falling → 1.0; positive but not falling →
      0.5; non-positive → 0.0.
    """
    if signal_direction not in ("BUY", "SELL"):
        raise ValueError(f"signal_direction must be 'BUY' or 'SELL', got {signal_direction!r}")

    if signal_direction == "BUY":
        if len(bear_power) < 2:
            raise ValueError(f"bear_power must have at least 2 points, got {len(bear_power)}")
        latest, previous = bear_power.iloc[-1], bear_power.iloc[-2]
        if pd.isna(latest) or pd.isna(previous):
            return 0.0
        if latest >= 0:
            return 0.0
        return 1.0 if latest > previous else 0.5
    else:
        if len(bull_power) < 2:
            raise ValueError(f"bull_power must have at least 2 points, got {len(bull_power)}")
        latest, previous = bull_power.iloc[-1], bull_power.iloc[-2]
        if pd.isna(latest) or pd.isna(previous):
            return 0.0
        if latest <= 0:
            return 0.0
        return 1.0 if latest < previous else 0.5


def score_volume_confirmation(wave_state: str, latest_volume: float, average_volume_20d: float) -> float:
    """Volume confirmation component score (docs/Analyse.md §6, weight 10%).

    docs/Analyse.md §6: "100% if Force Index spike / trigger bar volume is above 20-day
    average" -- an OR of two binary conditions, with no partial-credit tier documented
    (unlike tide alignment or the Impulse gate), so this is scored as a plain 1.0/0.0 rather
    than inventing an intermediate value; see this task's `decisions` entry on
    docs/tasks/confidence-scoring.json.

    ``wave_state`` stands in for "Force Index spike": ``evaluate_wave`` only reaches
    ``OVERSOLD_PULLBACK``/``OVERBOUGHT_RALLY`` when its own Force Index spike check
    (``_is_force_index_spike`` in triple_screen.py) passed, so reusing that state here avoids
    re-deriving the same spike threshold a second time with a different, possibly
    inconsistent definition.
    """
    force_index_spiked = wave_state in ("OVERSOLD_PULLBACK", "OVERBOUGHT_RALLY")
    volume_above_average = not pd.isna(average_volume_20d) and latest_volume > average_volume_20d
    return 1.0 if (force_index_spiked or volume_above_average) else 0.0
