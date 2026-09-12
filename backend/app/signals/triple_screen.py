import pandas as pd


def evaluate_tide(weekly_ohlcv: pd.DataFrame) -> str:
    """Screen 1: 'BULLISH' | 'BEARISH' | 'NEUTRAL'.

    From weekly MACD-Histogram slope + 13/26-week EMA relationship (docs/Analyse.md §2).
    """
    raise NotImplementedError


def evaluate_wave(daily_ohlcv: pd.DataFrame, tide: str) -> dict:
    """Screen 2: oscillator state evaluated against the tide direction (docs/Analyse.md §2)."""
    raise NotImplementedError


def evaluate_trigger(daily_ohlcv: pd.DataFrame, tide: str) -> bool:
    """Screen 3: has price resumed direction (close crossed prior day's high/low) (docs/Analyse.md §2)."""
    raise NotImplementedError
