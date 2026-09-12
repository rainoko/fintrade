import pandas as pd

from app.indicators.ema import ema


def force_index(close: pd.Series, volume: pd.Series, ema_period: int) -> pd.Series:
    """Force Index = Volume x price change, EMA-smoothed.

    Raw Force Index for bar t is ``volume_t * (close_t - close_{t-1})``
    (docs/Analyse.md §2); the first bar has no prior close, so its raw value
    is undefined (NaN). The raw series is then smoothed by delegating to
    ``app.indicators.ema.ema``, which applies the same recursive EMA
    definition (k = 2 / (ema_period + 1), seeded with the first non-NaN raw
    value) used everywhere else in this app, and validates ``ema_period``
    (must be a non-bool ``int`` >= 1).

    Use ema_period=2 for entry timing, ema_period=13 for trend confirmation
    (docs/Analyse.md §2/§4).

    Raises:
        TypeError: if ``ema_period`` is not an ``int`` (e.g. a ``bool`` or a
            ``float`` like ``13.5``) -- see ``app.indicators.ema.ema``.
        ValueError: if ``ema_period`` is not >= 1, or if ``close`` and
            ``volume`` are not aligned on the same index. ``volume *
            close.diff()`` aligns by pandas index *label*, not position, so
            two equal-length Series with offset or otherwise different
            indices would otherwise silently combine into a bogus,
            mis-shifted raw series instead of raising.
    """
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must share the same index")

    raw = volume * close.diff()
    return ema(raw, ema_period)
