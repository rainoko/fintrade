"""Package-internal shared primitive for fractal swing-point detection.

Factored out of ``app.signals.swing_points`` and ``app.signals.support_resistance`` (see
``docs/tasks/backend-swing-point-detector-followups.json``'s ``decisions`` entry) -- both
modules independently implemented "is bar i a local extreme over a window centered on it" as
a manual Python loop over per-bar ``.iloc[...]`` slices, differing only in what each does with
a confirmed extreme (``swing_points``'s plateau merging vs. ``support_resistance``'s
high/low-vs-close touch selection). This module holds just the shared, vectorized comparison;
each caller still owns its own loop bounds (edge exclusion) and NaN-handling contract.
"""

import pandas as pd


def rolling_extreme_masks(
    series: pd.Series, span: int, *, require_full_window: bool
) -> tuple[pd.Series, pd.Series]:
    """Boolean masks, aligned to ``series``'s own index, marking every position whose value
    equals the max (``is_high``) / min (``is_low``) of the ``span``-bar window centered on it.

    ``require_full_window=True`` matches ``app.signals.swing_points``'s contract: a window
    containing any NaN produces ``False`` in both masks at that position, even if the
    position's own value is a real number -- a swing point needs a FULLY populated comparison
    window, not just a non-NaN value of its own. ``require_full_window=False`` matches
    ``app.signals.support_resistance``'s original, more permissive behavior (pandas' own
    default ``skipna`` aggregation: a window with some NaN still computes max/min from
    whatever real values remain) -- preserved here rather than changed, since that module's
    zones are keyed off already-cleaned daily OHLCV and changing this behavior wasn't asked
    for or verified by either module's own review.

    Callers are still responsible for their own edge exclusion (never treating either of the
    first/last ``span // 2`` positions as a swing-point candidate, since neither has a full
    window on both sides) -- this function only reports, at each position, whether that
    position's value ties the window's own extreme; it doesn't know where the "valid interior"
    a given caller cares about starts and ends.
    """
    min_periods = span if require_full_window else 1
    rolling = series.rolling(span, center=True, min_periods=min_periods)
    return series == rolling.max(), series == rolling.min()
