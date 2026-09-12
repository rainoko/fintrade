import pandas as pd


def evaluate_impulse(daily_ohlcv: pd.DataFrame) -> str:
    """'GREEN' | 'RED' | 'BLUE', from EMA(13) direction + MACD-Histogram direction together (docs/Analyse.md §3).

    Acts as a gate: GREEN blocks fresh SELL signals, RED blocks fresh BUY signals.
    """
    raise NotImplementedError
