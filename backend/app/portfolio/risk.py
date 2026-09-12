import pandas as pd

from app.portfolio.models import Account, Position


def protective_stop(position: Position, daily_ohlcv: pd.DataFrame) -> float:
    """Swing low minus a volatility buffer (docs/Analyse.md §7, SafeZone concept)."""
    raise NotImplementedError


def position_risk_pct(position: Position, stop: float, account: Account) -> float:
    """Fraction of account equity at risk if `position` hits its protective stop (2% rule, docs/Analyse.md §7)."""
    raise NotImplementedError


def total_open_risk_pct(account: Account, stops: dict[str, float]) -> float:
    """Sum of position_risk_pct across all positions (6% rule, docs/Analyse.md §7)."""
    raise NotImplementedError
