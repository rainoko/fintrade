import pandas as pd

from app.indicators._validation import validate_period


def rsi(close: pd.Series, period: int = 9) -> pd.Series:
    """Relative Strength Index (Elder ch. 27). Closing-price-only oscillator, unlike
    ``app.indicators.stochastic.stochastic_oscillator`` (which reads high/low/close) --
    Elder's own selling point for RSI over Stochastic is exactly this: fewer inputs make it
    "less noisy," with signals that tend to emerge earlier (docs/Analyse.md §4, docs/ideas.md).

    ``RSI = 100 - 100 / (1 + RS)``, where ``RS`` is the average of net up-closes over the
    trailing ``period`` days divided by the average of net down-closes over the same window
    (the exact wording docs/ideas.md quotes from the book). Each day's signed close-to-close
    change (``close.diff()``) is split into an "up" series (the change when positive, 0
    otherwise) and a "down" series (the magnitude of the change when negative, 0 otherwise);
    ``RS`` is the ratio of their trailing rolling *simple* (arithmetic) means.

    A plain ``.rolling(window=period).mean()`` is used for both series -- not Wilder's
    smoothed moving average (an EMA-like running average with smoothing constant
    ``1/period``), which is what the original 1978 Wilder formula and most mainstream RSI
    implementations actually use in practice. The book's own formula, and docs/ideas.md's
    transcription of it, read as a plain average with no mention of exponential smoothing;
    a simple rolling mean also matches how this app's own Stochastic Oscillator is computed
    (SMA-based throughout, no ``.ewm(...)``) and is what makes a hand-computed reference-value
    test tractable without needing an EMA seed-value convention. See this task's `decisions`
    entry (docs/tasks/backend-indicator-rsi.json).

    Edge cases, evaluated only from ``period`` bars onward (see warm-up below):

    - No down-closes in the window (``avg_loss == 0``, but ``avg_gain > 0``): ``RS`` is
      undefined (division by zero), conventionally read as maximal strength -- RSI = 100.
      Reached here via plain float division (``avg_gain / 0.0 == inf``, no explicit branch
      needed): ``100 - 100 / (1 + inf) == 100.0`` exactly.
    - No gains AND no down-closes in the window (a perfectly flat trailing run,
      ``avg_gain == avg_loss == 0``): ``RS`` is a 0/0 division (NaN), explicitly mapped to
      RSI = 50 (neutral -- no evidence of either strength or weakness), not 0 or 100, since
      neither of those would correctly represent "no price movement at all."

    The first bar's ``close.diff()`` is itself NaN (no prior close to compare against), which
    propagates through this bar's own rolling window the same way
    ``stochastic_oscillator``'s first ``k_period - 1`` bars are NaN -- so RSI is NaN for the
    first ``period`` bars (needs ``period`` daily changes, i.e. ``period + 1`` closes).

    Raises:
        TypeError: if ``period`` is not an ``int`` (e.g. a ``bool`` or a ``float`` like
            ``9.5``).
        ValueError: if ``period`` is not >= 1.
    """
    validate_period("period", period)

    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.rolling(window=period).mean()
    avg_loss = losses.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    result = 100 - 100 / (1 + rs)

    flat = (avg_gain == 0) & (avg_loss == 0)
    result = result.where(~flat, other=50.0)

    return result
