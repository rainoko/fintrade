"""Swing-high / swing-low detection over any ``pd.Series`` -- the shared prerequisite every
divergence-detection idea logged in ``docs/ideas.md`` (MACD-Histogram, Stochastic, RSI, and
eventually OBV/A-D) needs: two comparable peaks or troughs of the SAME series have to be
identified before their heights/depths can be measured against each other.

See ``docs/tasks/backend-swing-point-detector.json``'s ``decisions`` array for the full
rationale behind the algorithm and every parameter below -- this module's contract (what
counts as a swing, how ties/plateaus are handled, what the default window is and why) is
meant to be predictable enough that every later divergence-detection task can depend on it
without re-deriving it.

**Relationship to ``app.signals.support_resistance``'s own internal ``_find_swing_points``**
(checked before writing this module, per this task's own description): that function is also
fractal swing-point detection, but purpose-built for support/resistance zone clustering -- it
tests a bar's ``high``/``low`` OHLCV columns against a window of *other bars'* highs/lows, then
reports the bar's ``close`` (a different column) as the "touch" value fed into price
clustering. This module's use case is different: a divergence detector needs to find local
extrema *within a single series* -- a price series (e.g. ``close``) or an indicator series
(MACD-Histogram, Stochastic %K, RSI, OBV) -- and compare THAT SAME series's own value at two
such extrema. There is no separate high/low-vs-close split to make (an indicator series has no
"wick" of its own), so support_resistance's column-split logic doesn't fit this use case, and
extracting a shared implementation of either module's own post-processing was rejected -- see
this task's ``decisions`` entry for the full comparison. The two modules DO now share a
smaller, lower-level primitive -- ``app.signals._swing_extremes.rolling_extreme_masks``, the
vectorized "is bar i tied with its window's own max/min" comparison each module's loop
delegates to -- see ``docs/tasks/backend-swing-point-detector-followups.json``'s ``decisions``
entry for why that narrower extraction was worth it where generalizing either module's own
post-processing wasn't.

**Swing-point definition** (this module's contract): bar ``i`` is a swing HIGH if its value is
the maximum of the ``2*window + 1``-bar window centered on it (mirrored via minimum for a swing
LOW). The first/last ``window`` bars of the series can never be a swing point -- there is no
full window to compare them against, an intentional, bounded edge exclusion (a "swing"
inherently needs bars on both sides to confirm a local turn), not a bug.

**Ties / plateaus**: a flat top/bottom (several consecutive bars sharing the exact same
extreme value) would otherwise register one raw swing-point candidate per bar in the
plateau -- this function merges any run of index-consecutive, equal-value candidates of the
same kind into a SINGLE ``SwingPoint`` located at the run's middle bar (rounding toward the
later bar for an even-length run, i.e. Python's ``run_length // 2``), so a flat top always
produces exactly one swing high, never one per bar. A bar whose value equals BOTH its window's
max and min (only possible when the whole window is flat) is reported as both a swing high and
a swing low at that bar -- documented behavior, not a special case to avoid.

**NaN handling**: a candidate bar is skipped entirely (not reported as a swing point, in
either direction) if its own value OR any bar in its ``2*window + 1`` comparison window is
``NaN`` -- a partial comparison (silently dropping the ``NaN`` neighbors and comparing against
whatever real values remain) would let a bar look like a "local extreme" purely because it had
fewer real neighbors to lose to, not because it genuinely is one, which would violate this
module's own "a swing needs bars on both sides" rule. This matters for indicator series with a
warm-up period (e.g. the first N bars of an EMA-based indicator, which pandas' own `.ewm()`
leaves as ``NaN``) at the start of the input: no swing point can be detected until a bar's
entire window falls after the warm-up period ends, not just its own value.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.signals._swing_extremes import rolling_extreme_masks

SwingKind = Literal["high", "low"]

# Bars on each side of a candidate swing point the window compares against -- 3 gives a 7-bar
# window (today plus 3 before/3 after). Chosen slightly wider than
# app.signals.support_resistance's own 2-bar/5-bar fractal window: that module tests raw
# high/low price wicks, which are already the noisiest possible series; this module is
# routinely handed indicator series (Stochastic %K in particular) that whipsaw even more
# readily bar-to-bar, so a narrower window would flag a lot of short-lived wiggles as
# "swings". Still just a sensible default -- every call site (starting with the
# backend-divergence-detection task this module exists for) can override it per series. See
# this task's `decisions` entry for the full rationale and rejected alternatives.
_DEFAULT_WINDOW = 3


@dataclass(frozen=True)
class SwingPoint:
    """One local extremum of a series.

    ``index`` is the series' own index label at that bar (typically a ``pd.Timestamp`` for the
    date-indexed price/indicator series this app works with elsewhere, but this module makes
    no assumption about the index type). ``value`` is the series' own value there. ``kind`` is
    ``"high"`` or ``"low"``.
    """

    index: object
    value: float
    kind: SwingKind


def find_swing_points(series: pd.Series, *, window: int = _DEFAULT_WINDOW) -> list[SwingPoint]:
    """Detects every swing high and swing low in ``series`` using a ``2*window + 1``-bar
    fractal window (see this module's docstring for the exact definition and tie/plateau
    handling).

    Returns swing points chronologically ordered (ascending by position in ``series``),
    interleaving highs and lows in the order they actually occur -- filter by ``kind`` (or use
    :func:`swing_highs`/:func:`swing_lows`) to get just one side.

    Returns an empty list if ``series`` has fewer than ``2 * window + 1`` bars (too short for
    any swing point to exist) or is empty.

    Raises:
        ValueError: if ``window`` is less than 1.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1 (got {window})")

    n = len(series)
    if n < 2 * window + 1:
        return []

    # Vectorized centered-rolling comparison (see app.signals._swing_extremes) rather than a
    # manual per-bar loop -- `require_full_window=True` reproduces this module's NaN contract
    # exactly: `rolling(..., min_periods=span)` is NaN at a position unless every bar in its
    # window is non-NaN, so a candidate whose window touches a NaN naturally compares False
    # against both masks below, with no separate `.isna().any()` check needed.
    span = 2 * window + 1
    is_high, is_low = rolling_extreme_masks(series, span, require_full_window=True)

    raw: list[tuple[int, float, SwingKind]] = []
    for i in range(window, n - window):
        if is_high.iloc[i]:
            raw.append((i, float(series.iloc[i]), "high"))
        if is_low.iloc[i]:
            raw.append((i, float(series.iloc[i]), "low"))

    return _merge_plateau_runs(raw, series.index)


def swing_highs(series: pd.Series, *, window: int = _DEFAULT_WINDOW) -> list[SwingPoint]:
    """Convenience wrapper over :func:`find_swing_points` returning only swing highs."""
    return [p for p in find_swing_points(series, window=window) if p.kind == "high"]


def swing_lows(series: pd.Series, *, window: int = _DEFAULT_WINDOW) -> list[SwingPoint]:
    """Convenience wrapper over :func:`find_swing_points` returning only swing lows."""
    return [p for p in find_swing_points(series, window=window) if p.kind == "low"]


def _merge_plateau_runs(
    candidates: list[tuple[int, float, SwingKind]], index: pd.Index
) -> list[SwingPoint]:
    """Merges index-consecutive, equal-value candidates of the same kind into one
    ``SwingPoint`` at the run's middle bar -- see this module's docstring's "Ties / plateaus"
    section."""
    positioned: list[tuple[int, SwingPoint]] = []
    for kind in ("high", "low"):
        run: list[tuple[int, float]] = []
        for i, value, _candidate_kind in sorted(
            (c for c in candidates if c[2] == kind), key=lambda c: c[0]
        ):
            if run and i == run[-1][0] + 1 and value == run[-1][1]:
                run.append((i, value))
                continue
            if run:
                positioned.append(_run_to_point(run, kind, index))
            run = [(i, value)]
        if run:
            positioned.append(_run_to_point(run, kind, index))

    positioned.sort(key=lambda item: item[0])
    return [point for _position, point in positioned]


def _run_to_point(
    run: list[tuple[int, float]], kind: SwingKind, index: pd.Index
) -> tuple[int, SwingPoint]:
    mid_i, mid_value = run[len(run) // 2]
    return mid_i, SwingPoint(index=index[mid_i], value=mid_value, kind=kind)
