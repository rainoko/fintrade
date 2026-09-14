from dataclasses import dataclass

import pandas as pd

from app.indicators.ema import ema


@dataclass(frozen=True)
class MacdComponents:
    """The full set of intermediate series behind MACD-Histogram.

    Exposed (rather than just the histogram) so a caller that also needs one
    of the intermediate EMAs -- e.g. the Screen 1 tide, which needs both the
    histogram *and* EMA(close, slow) for its 13/26-week EMA relationship
    check -- can get both from a single pass instead of recomputing
    ``ema(close, slow)`` a second time (see the ``screen1-tide`` task's
    `decisions` entry).
    """

    ema_fast: pd.Series
    ema_slow: pd.Series
    macd_line: pd.Series
    signal_line: pd.Series
    histogram: pd.Series


def macd_components(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> MacdComponents:
    """MACD-Histogram and every intermediate series it's built from (docs/Analyse.md §2-3).

    Standard MACD construction, built on top of ``app.indicators.ema.ema`` for
    each of the three EMAs involved (12/26/9 are just parameters to the same
    underlying EMA function, per docs/Analyse.md §4):

    - MACD line = EMA(close, fast) - EMA(close, slow)
    - Signal line = EMA(MACD line, signal)
    - Histogram = MACD line - Signal line
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return MacdComponents(
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        macd_line=macd_line,
        signal_line=signal_line,
        histogram=histogram,
    )


def macd_histogram(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.Series:
    """MACD-Histogram. Drives the Screen 1 tide slope and the Impulse gate (docs/Analyse.md §2-3).

    The histogram's sign shows whether momentum favors the fast or slow EMA;
    its *slope* (not computed here -- see the ``screen1-tide``/``impulse-system``
    tasks) is what actually feeds the Screen 1 tide and the Impulse gate.
    Returning just the raw histogram series (rather than also returning a
    rising/falling/flat classification) keeps this a pure indicator function
    and leaves slope classification -- which needs a threshold for what
    counts as "flat", a signal-engine-level decision -- to the signal engine
    that consumes it.

    A thin wrapper over :func:`macd_components` for callers that only need
    the histogram; use ``macd_components`` directly when an intermediate EMA
    is also needed, to avoid computing the same EMA twice.
    """
    return macd_components(close, fast=fast, slow=slow, signal=signal).histogram
