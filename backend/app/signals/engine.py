from dataclasses import dataclass

import pandas as pd

from app.signals.confidence import ConfidenceComponent


@dataclass
class SignalResult:
    signal: str  # 'BUY' | 'SELL' | 'HOLD'
    confidence: int
    confidence_band: str
    breakdown: list[ConfidenceComponent]


def analyse(ticker: str, daily_ohlcv: pd.DataFrame, weekly_ohlcv: pd.DataFrame) -> SignalResult:
    """Orchestrates Screens 1-3 + Impulse gate + confidence scoring into one signal.

    See docs/architecture/Backend.md §5 and docs/Analyse.md §5.
    """
    raise NotImplementedError
