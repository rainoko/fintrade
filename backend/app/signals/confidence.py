from dataclasses import dataclass

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
    """Weighted composite score, 0-100 (docs/Analyse.md §6). Not a statistical probability."""
    raise NotImplementedError


def confidence_band(confidence: int) -> str:
    """'Low' (<40) | 'Medium' (40-70) | 'High' (>70) (docs/Analyse.md §6)."""
    raise NotImplementedError
