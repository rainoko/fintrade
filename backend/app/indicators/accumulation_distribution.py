import pandas as pd


def accumulation_distribution(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    """Accumulation/Distribution (Elder ch. 29, pp. 109-112, developed by Larry Williams).

    A running total, more finely calibrated than
    ``app.indicators.obv.obv`` since it credits volume *proportional to where the close
    landed within the day's range*, instead of crediting the whole day's volume to
    whichever side "won" (docs/Analyse.md §4, docs/ideas.md):

        A/D_t = (close_t - open_t) / (high_t - low_t) * volume_t

    cumulative running total. Conceptually close to
    ``app.indicators.elder_ray`` (both read the open/close-vs-range relationship) but A/D is
    cumulative and volume-weighted where Elder-Ray isn't -- a genuinely distinct indicator,
    not a duplicate (docs/ideas.md's own framing).

    Same "absolute level is meaningless" caveat as ``obv`` -- only the pattern of highs/lows
    and divergence against price matters. Divergence detection against A/D is explicitly out
    of scope for this function (see the backend-indicator-obv-ad task).

    A bar with zero range (``high == low``, e.g. a halted/limit-locked session) makes the
    day's own contribution undefined (0/0, since ``close - open`` is also necessarily 0 when
    the whole bar is a single price) -- mapped explicitly to 0 rather than left as NaN, for
    the same "NaN is sticky under cumsum" reason ``obv`` maps its own first-bar undefined
    direction to 0 (see this task's `decisions` entry). This differs from
    ``app.indicators.stochastic.stochastic_oscillator``'s zero-range handling (left as NaN
    via plain division), which is safe there only because %K/%D are not themselves
    cumulative.

    Raises:
        ValueError: if ``open_``, ``high``, ``low``, ``close``, and ``volume`` are not all
            aligned on the same index (mirrors ``app.indicators.force_index.force_index``'s
            guard against silent pandas label-based misalignment).
    """
    indices = (open_.index, high.index, low.index, close.index, volume.index)
    if not all(idx.equals(indices[0]) for idx in indices[1:]):
        raise ValueError("open_, high, low, close, and volume must share the same index")

    bar_range = high - low
    close_location_value = (close - open_) / bar_range
    close_location_value = close_location_value.where(bar_range != 0, other=0.0)

    raw = close_location_value * volume
    return raw.cumsum()
