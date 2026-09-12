import pandas as pd

from app.indicators.ema import ema


def macd_histogram(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.Series:
    """MACD-Histogram. Drives the Screen 1 tide slope and the Impulse gate (docs/Analyse.md §2-3).

    Standard MACD construction, built on top of ``app.indicators.ema.ema`` for
    each of the three EMAs involved (12/26/9 are just parameters to the same
    underlying EMA function, per docs/Analyse.md §4):

    - MACD line = EMA(close, fast) - EMA(close, slow)
    - Signal line = EMA(MACD line, signal)
    - Histogram = MACD line - Signal line

    The histogram's sign shows whether momentum favors the fast or slow EMA;
    its *slope* (not computed here -- see the ``screen1-tide``/``impulse-system``
    tasks) is what actually feeds the Screen 1 tide and the Impulse gate.
    Returning the raw histogram series (rather than also returning a
    rising/falling/flat classification) keeps this module a pure indicator
    function and leaves slope classification -- which needs a threshold for
    what counts as "flat", a signal-engine-level decision -- to the signal
    engine that consumes it.
    """
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line
