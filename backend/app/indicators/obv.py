import numpy as np
import pandas as pd


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume (Elder ch. 29, pp. 107-109, developed by Joseph Granville).

    A running total: add the day's full volume if today's close is higher than the prior
    close, subtract it if lower, leave the total unchanged if flat (docs/Analyse.md §4,
    docs/ideas.md). Unlike ``app.indicators.force_index.force_index`` (which weights by the
    *size* of the price change), OBV only reads the *sign* of the change -- the whole day's
    volume is credited to whichever side "won", however narrow the margin
    (``app.indicators.accumulation_distribution.accumulation_distribution`` is the more
    finely calibrated sibling that reads *where* the close landed within the day's range
    instead).

    The result is a cumulative series whose absolute level is meaningless (it depends on
    however far back ``close``/``volume`` happen to start) -- only its pattern of highs/lows
    and its divergence against price matters, same as every other oscillator in this app
    (docs/Analyse.md §4). Divergence detection against OBV is explicitly out of scope for
    this function (see the backend-indicator-obv-ad task) -- it depends on
    ``app.signals.swing_points``, the same building block
    ``app.signals.divergence`` already uses for MACD-Histogram/Stochastic/RSI.

    The first bar has no prior close to compare against, so its own direction is undefined;
    this implementation contributes 0 for that bar (the running total starts at 0, not at
    the first bar's own volume) rather than leaving it NaN, since an undefined day
    contributing NaN would poison every later cumulative total once summed (``NaN`` is
    "sticky" under ``cumsum``). See this task's `decisions` entry for why 0 was chosen over
    the alternative convention (seeding the total with the first bar's raw volume).

    Raises:
        ValueError: if ``close`` and ``volume`` are not aligned on the same index (mirrors
            ``app.indicators.force_index.force_index``'s guard against silent pandas
            label-based misalignment).
    """
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must share the same index")

    direction = np.sign(close.diff()).fillna(0.0)
    signed_volume = direction * volume
    return signed_volume.cumsum()
