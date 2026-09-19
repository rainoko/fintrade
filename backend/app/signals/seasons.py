from typing import Literal

import pandas as pd

Season = Literal["Spring", "Summer", "Autumn", "Winter"]


def classify_season(histogram: pd.Series) -> Season | None:
    """"Indicator Seasons" -- Elder ch. 32 "Time" (pp. 122-124), docs/ideas.md. A four-way
    classification of an oscillator's state from two already-cheap-to-read properties of
    ``histogram`` (``app.indicators.macd.macd_histogram``): its bar-over-bar *slope*
    (rising/falling) and its *position relative to its own zero centerline*:

    | Slope   | vs. centerline | Season | Elder's stated read                                   |
    |---------|-----------------|--------|--------------------------------------------------------|
    | Rising  | Below           | Spring | Best time to go long                                    |
    | Rising  | Above           | Summer | Crowd-recognized uptrend; take profits on longs         |
    | Falling | Above           | Autumn | Best time to go short                                   |
    | Falling | Below           | Winter | Crowd-recognized downtrend; cover shorts into weakness   |

    Purely informational -- Elder states the concept generally ("we can apply the concept of
    seasons to most indicators and timeframes"), and Spring/Autumn are explicitly called out as
    the emotionally-hardest, best-risk/reward entries precisely because the *prior* trend's
    memory is still fresh. This module is deliberately never imported by
    ``app.signals.engine._determine_signal`` or ``app.signals.confidence`` -- it's a label
    layered on top of the already-computed MACD-Histogram series, not a new signal input; see
    this task's `decisions` entry and docs/Analyse.md's Indicator Seasons section.

    ``histogram`` is taken as an already-computed series (the same one
    ``app.signals.impulse.evaluate_impulse``'s own ``histogram`` parameter and
    ``app.signals.engine.analyse``'s ``indicators.macd_histogram`` field already use) rather
    than recomputed internally, so a caller with that series in hand already (every real
    caller, via ``analyse()``) doesn't pay for a second MACD pass.

    Slope uses the same bar-over-bar "rising iff latest > previous" convention as
    ``app.signals.impulse._direction`` -- a tie (latest == previous) counts as "falling", for
    the same reason that function documents (a not-yet-advanced value hasn't demonstrated
    rising momentum), rather than inventing a third tie-breaking rule for what's structurally
    the same kind of comparison. Position-vs-centerline treats an exact zero as "below" (not
    "above") -- mirroring ``app.signals.triple_screen._is_force_index_spike``'s
    ``sign * latest <= 0`` treatment of zero as not-positive -- see this task's `decisions`
    entry.

    Returns ``None`` if ``histogram`` has fewer than 2 points, or either of its last two
    values is NaN: there's no bar-over-bar slope to classify yet. This mirrors the same
    degrade-to-null convention ``Indicators.rsi``/``channel_upper``/``channel_lower``
    (docs/architecture/API.md) already use for "not enough history yet", just triggered by a
    much shorter (2-bar) requirement than either of those rolling-window warm-ups.
    """
    if len(histogram) < 2:
        return None

    latest, previous = histogram.iloc[-1], histogram.iloc[-2]
    if pd.isna(latest) or pd.isna(previous):
        return None

    rising = latest > previous
    above_centerline = latest > 0

    if rising and not above_centerline:
        return "Spring"
    if rising and above_centerline:
        return "Summer"
    if not rising and above_centerline:
        return "Autumn"
    return "Winter"
