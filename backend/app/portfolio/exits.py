import pandas as pd

from app.portfolio.models import Account, Position


def evaluate_exit_flags(position: Position, account: Account, daily_ohlcv: pd.DataFrame, weekly_ohlcv: pd.DataFrame) -> list[str]:
    """Existing-position exit conditions, independent of fresh-entry signal logic (docs/Analyse.md §7).

    Possible flags: 'stop_hit', 'two_percent_rule_breached', 'six_percent_rule_contributor',
    'profit_zone_impulse_red', 'tide_flipped_bearish'.
    """
    raise NotImplementedError
