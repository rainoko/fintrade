"""Bullish/bearish divergence detection for MACD-Histogram, Stochastic %K, and RSI -- Elder
ch. 15/23/26/27, docs/ideas.md's own transcription of the primary text (this module's exact
algorithm source; see docs/tasks/backend-divergence-detection.json's `decisions` entry for
every judgment call below).

**What a divergence is** (docs/ideas.md): price makes a new high/low, but the indicator makes
a *shallower* extreme than its previous comparable one -- the trend is losing momentum even
though price hasn't turned yet. This module anchors on PRICE's own swing points (via
``app.signals.swing_points``, the shared prerequisite built for exactly this) and reads each
indicator's value at those same two dates, rather than independently detecting swing points on
the indicator series itself and fuzzily matching them to price's -- docs/ideas.md's own
"Implementation shape" note phrases it the same way ("compare the latest swing extreme in
price against the indicator's value at the prior comparable swing extreme"), and anchoring on
one series's swings only (not two independently-detected, approximately-aligned ones) keeps
detection deterministic and keeps this module needing only a single swing-point pass per call,
shared across all three indicators when driven from ``current_divergence``.

**MACD-Histogram** (ch. 23) has one additional hard requirement the other two don't: the
histogram must cross its own zero centerline between the two compared extremes -- "an absolute
must for a true divergence" per the book; no crossover, no divergence. A pair failing this
check isn't a weaker divergence, it isn't a divergence at all, so ``macd_centerline_crossed``
is enforced as a hard filter (like price-makes-new-extreme and the Lovvorn filters below), not
an informational flag.

**Stochastic (ch. 26) and RSI (ch. 27)** get the simpler treatment: no centerline requirement,
just a direct second-vs-first extreme comparison. They're "strongest when the first extreme is
beyond the oscillator's own overbought/oversold reference line and the second is back inside
it" -- ``is_beyond_reference_line`` computes this, but only as an informational flag
(``Divergence.beyond_reference_line``), never a hard filter, matching the book's own "strongest
when", not "only valid when", phrasing.

**Kerry Lovvorn's empirical refinement** (his own cited research): the most tradable
divergences have their two extremes 20-40 bars apart (closer to 20 better) and the second
extreme no more than half the height/depth of the first. Both are implemented as their own
named, independently-testable functions (``is_spacing_valid``, ``is_second_extreme_shallow_
enough``) rather than inlined, per this task's own checklist.

**"Hound of the Baskervilles"**: a formed divergence that price subsequently ignores (keeps
moving in the "wrong" direction instead of the reversal the divergence implied) is itself a
strong continuation signal in the opposite direction -- Elder's one explicit stop-and-reverse
case. ``Divergence.aborted`` detects this; this module only detects/exposes the aborted state,
it doesn't itself act on it (wiring a stop-and-reverse into the signal engine is explicitly out
of scope for this task -- detection + exposure only, per its own description).

**Triple divergences** (three tops/bottoms, occurring when a regular divergence "aborts" and
a third, still-shallower extreme forms) are mentioned in docs/ideas.md but not implemented here
-- out of scope for this task, which only asks for the standard two-extreme case; a real
occurrence would still show up as two separate, valid two-extreme divergences via this module
(the first pair, then the second-and-third pair) rather than going undetected.
"""

from dataclasses import dataclass
from typing import Literal, cast

import pandas as pd

from app.signals.swing_points import SwingPoint, swing_highs, swing_lows

DivergenceKind = Literal["bullish", "bearish"]
DivergenceIndicator = Literal["macd_histogram", "stochastic", "rsi"]

# Kerry Lovvorn's empirical spacing filter (docs/ideas.md): the two compared extremes should be
# 20-40 bars apart, closer to 20 being better within that range.
MIN_SWING_SPACING_BARS = 20
MAX_SWING_SPACING_BARS = 40

# Kerry Lovvorn's empirical depth filter (docs/ideas.md): the second extreme should be no more
# than half the height/depth of the first.
MAX_SECOND_EXTREME_DEPTH_RATIO = 0.5

# Swing-point window for PRICE (this module always finds swings on price, never on the
# indicator series -- see module docstring), passed straight through to
# app.signals.swing_points. Matches that module's own default (3, a 7-bar window) -- chosen
# there for indicator series specifically (which whipsaw more than price), but kept as this
# module's own default too for consistency/predictability rather than introducing a second,
# unexplained default; every call site can still override it. See this task's `decisions`
# entry.
DEFAULT_SWING_WINDOW = 3

# MACD-Histogram's own centerline (docs/Analyse.md §2-3) -- the reference "height/depth" for
# the Lovvorn depth filter is measured from, for this indicator.
_MACD_CENTERLINE = 0.0

# Stochastic %K's overbought/oversold reference lines -- pinned by docs/Analyse.md §2 ("below
# 30 = oversold, above 70 = overbought"), same constants app.signals.triple_screen defines
# (not imported from there directly to avoid a signals-internal cross-import for two float
# literals; kept in sync by convention, matching triple_screen.py's own comment).
_STOCHASTIC_OVERSOLD = 30.0
_STOCHASTIC_OVERBOUGHT = 70.0

# RSI has no overbought/oversold reference line defined anywhere else in this app (docs/
# Analyse.md §4 exposes RSI for computation + display only, wired into no signal/threshold
# logic yet) -- this module reuses the same 30/70 convention as Stochastic (Elder's own book
# also treats 30/70 as RSI's classic reference lines, ch. 27), rather than inventing a
# different pair, so both oscillators' depth/strength math reads identically. See this task's
# `decisions` entry.
_RSI_OVERSOLD = 30.0
_RSI_OVERBOUGHT = 70.0


@dataclass(frozen=True)
class DivergenceExtreme:
    """One of a ``Divergence``'s two compared points: PRICE's own swing-point date/value, plus
    the indicator's value read at that exact same date.

    ``date`` is typed ``pd.Timestamp`` (narrower than ``app.signals.swing_points.SwingPoint``'s
    own deliberately-generic ``index: object``, since every real caller in this app feeds this
    module a date-indexed price/indicator series) so it's directly comparable/sortable and
    exposes ``.date()`` for the API boundary mapping (``app.api.routers.stocks.
    _divergence_to_schema``) without a cast at every call site."""

    date: pd.Timestamp
    price: float
    indicator_value: float


@dataclass(frozen=True)
class Divergence:
    """A single detected divergence -- exposed on the API as ``AnalysisResponse.divergence``/
    each ``IndicatorHistoryPoint.divergence`` (docs/architecture/API.md).

    ``bars_apart`` is ``first``/``second``'s date spacing in bar count (not calendar days) --
    what the Lovvorn spacing filter (``is_spacing_valid``) is measured against.

    ``centerline_crossed`` is only meaningful for ``indicator == "macd_histogram"``: always
    ``True`` when present (a non-crossing pair is filtered out entirely before a ``Divergence``
    is ever built -- "no crossover, no divergence"), ``None`` for stochastic/rsi (not
    applicable, no centerline requirement for those two).

    ``beyond_reference_line`` is only meaningful for ``indicator in ("stochastic", "rsi")``:
    whether this divergence is at its textbook strongest (see module docstring). ``None`` for
    macd_histogram (that concept doesn't apply there -- its equivalent strength signal is
    simply having crossed the centerline at all, already implied by this ``Divergence``
    existing).

    ``aborted`` is the "Hound of the Baskervilles" state -- whether price has, as of the caller's
    own current-as-of point, already ignored this divergence."""

    indicator: DivergenceIndicator
    kind: DivergenceKind
    first: DivergenceExtreme
    second: DivergenceExtreme
    bars_apart: int
    centerline_crossed: bool | None
    beyond_reference_line: bool | None
    aborted: bool


def is_spacing_valid(
    bars_apart: int,
    *,
    min_bars: int = MIN_SWING_SPACING_BARS,
    max_bars: int = MAX_SWING_SPACING_BARS,
) -> bool:
    """Kerry Lovvorn's empirical spacing filter (docs/ideas.md, cited from his own research):
    the most tradable divergences have their two compared extremes 20-40 bars apart. Only the
    outer bounds are enforced here as a hard pass/fail -- the "closer to 20 is better" part of
    the book's own phrasing is a preference within the accepted range, not a second cutoff, and
    isn't turned into a continuous score here since this task's checklist scopes this to
    detection + exposure, not confidence weighting (a later task's decision, not this one's)."""
    return min_bars <= bars_apart <= max_bars


def is_second_extreme_shallow_enough(
    first_depth: float,
    second_depth: float,
    *,
    max_ratio: float = MAX_SECOND_EXTREME_DEPTH_RATIO,
) -> bool:
    """Kerry Lovvorn's empirical depth filter (docs/ideas.md): the second extreme should be no
    more than half (``max_ratio``) the height/depth of the first. ``first_depth``/
    ``second_depth`` are each an already-nonnegative distance from the relevant indicator's own
    reference line (see ``_extreme_depths``).

    A non-positive ``first_depth`` (the first extreme sat exactly on, or on the far side of,
    its own reference line, so there's no positive depth for ``second_depth`` to be a fraction
    of) never qualifies -- returns ``False`` unconditionally rather than dividing by a
    non-positive number or treating "no depth to speak of" as trivially satisfied."""
    if first_depth <= 0:
        return False
    return second_depth <= max_ratio * first_depth


def macd_centerline_crossed(
    histogram: pd.Series, first_date: object, second_date: object, kind: DivergenceKind
) -> bool:
    """Whether MACD-Histogram crossed its own zero centerline at least once strictly between
    ``first_date`` and ``second_date`` -- "an absolute must for a true divergence" per the book
    (docs/ideas.md); no crossover, no divergence.

    A bullish divergence's two extremes are troughs (histogram at/below zero), so this checks
    the histogram actually rallied *above* zero at some point in between; a bearish
    divergence's two extremes are peaks, so this checks it fell *below* zero in between. Reads
    as "did the histogram's value cross to the other side at all", not "did it cross back and
    hold" -- a single bar beyond zero is enough, matching the book's own framing of the
    crossover as a gate, not a confirmed reversal in its own right.
    """
    between = histogram[(histogram.index > first_date) & (histogram.index < second_date)]
    if between.empty:
        return False
    if kind == "bullish":
        return bool((between > 0).any())
    return bool((between < 0).any())


def is_beyond_reference_line(
    first_value: float,
    second_value: float,
    kind: DivergenceKind,
    *,
    oversold: float = _STOCHASTIC_OVERSOLD,
    overbought: float = _STOCHASTIC_OVERBOUGHT,
) -> bool:
    """Whether this divergence is at its textbook strongest for Stochastic/RSI (docs/ideas.md,
    ch. 26/27): the first extreme beyond the oscillator's own overbought/oversold reference
    line, and the second back inside it. Informational only -- unlike MACD-Histogram's
    centerline crossing, this is never a hard requirement for a divergence to count at all
    ("strongest when...", not "only valid when...", per the book's own wording)."""
    if kind == "bullish":
        return first_value < oversold <= second_value
    return first_value > overbought >= second_value


def _extreme_depths(
    indicator_name: DivergenceIndicator, kind: DivergenceKind, first_value: float, second_value: float
) -> tuple[float, float]:
    """Each extreme's distance from its indicator's own natural reference line -- what "half
    the height/depth of the first" (the Lovvorn filter) is measured against.

    MACD-Histogram's reference is its own zero centerline (explicit in the book). Stochastic/
    RSI have no signed centerline the same way (their scale is bounded 0-100, not centered on
    zero) -- this module reuses their own overbought/oversold reference line (30/70) as the
    natural stand-in, since the book invokes that exact same reference line in the very same
    breath as the depth rule for these two oscillators ("strongest when the first extreme is
    beyond the oscillator's own overbought/oversold reference line") -- see this task's
    `decisions` entry for why, rather than inventing an unrelated 0/100-bound or 50-midline
    reference the book never mentions for this purpose."""
    if indicator_name == "macd_histogram":
        reference = _MACD_CENTERLINE
    elif indicator_name == "stochastic":
        reference = _STOCHASTIC_OVERSOLD if kind == "bullish" else _STOCHASTIC_OVERBOUGHT
    else:
        reference = _RSI_OVERSOLD if kind == "bullish" else _RSI_OVERBOUGHT
    return abs(first_value - reference), abs(second_value - reference)


def _is_aborted(price: pd.Series, second: DivergenceExtreme, kind: DivergenceKind) -> bool:
    """"Hound of the Baskervilles" (docs/ideas.md): whether ``price`` has, anywhere after
    ``second.date``, already ignored this divergence -- continued in the "wrong" direction
    instead of the reversal the divergence implied.

    A bullish divergence implies an eventual move up, so "ignored" means price closed at a new
    low *below* the second (already-shallower) extreme's own low at some point after it formed;
    a bearish divergence's mirror is a new high above the second extreme's high. Elder's own
    explicit rule for this case is a stop-and-reverse trade -- this module only detects/exposes
    the aborted state itself, not that trading action (out of scope for this task, matching its
    own detection-only description)."""
    after = price[price.index > second.date]
    if after.empty:
        # Not reachable from this module's own public entry points: a swing point (`second`
        # here) always has this module's own swing-detection `window` worth of bars after it
        # within whatever `price` it was detected from -- see app.signals.swing_points's own
        # "a swing needs bars on both sides" contract -- so `after` always has at least
        # `window` rows. Guarded rather than assumed, same reasoning as `_evaluate_pair`'s own
        # two similar guards above.
        return False  # pragma: no cover
    if kind == "bullish":
        return bool((after < second.price).any())
    return bool((after > second.price).any())


def _evaluate_pair(
    first_point: SwingPoint,
    second_point: SwingPoint,
    price: pd.Series,
    indicator: pd.Series,
    *,
    indicator_name: DivergenceIndicator,
    kind: DivergenceKind,
    min_bars_apart: int,
    max_bars_apart: int,
    max_second_extreme_depth_ratio: float,
) -> Divergence | None:
    """Evaluates one consecutive same-kind swing-point pair as a candidate divergence, applying
    every filter documented above in order (cheapest/most-likely-to-reject first). Returns
    ``None`` the moment any filter fails, or the resulting ``Divergence`` if every one passes."""
    if indicator_name not in ("macd_histogram", "stochastic", "rsi"):
        raise ValueError(
            f"indicator_name must be 'macd_histogram', 'stochastic', or 'rsi', got {indicator_name!r}"
        )
    if kind not in ("bullish", "bearish"):
        raise ValueError(f"kind must be 'bullish' or 'bearish', got {kind!r}")

    if first_point.index not in indicator.index or second_point.index not in indicator.index:
        return None
    first_indicator_value = indicator.loc[first_point.index]
    second_indicator_value = indicator.loc[second_point.index]
    if pd.isna(first_indicator_value) or pd.isna(second_indicator_value):
        return None

    price_makes_new_extreme = (
        second_point.value < first_point.value
        if kind == "bullish"
        else second_point.value > first_point.value
    )
    if not price_makes_new_extreme:
        return None

    indicator_shallower = (
        second_indicator_value > first_indicator_value
        if kind == "bullish"
        else second_indicator_value < first_indicator_value
    )
    if not indicator_shallower:
        return None

    first_depth, second_depth = _extreme_depths(
        indicator_name, kind, float(first_indicator_value), float(second_indicator_value)
    )
    if not is_second_extreme_shallow_enough(
        first_depth, second_depth, max_ratio=max_second_extreme_depth_ratio
    ):
        return None

    if first_point.index not in price.index or second_point.index not in price.index:
        # Not reachable from this module's own public entry points -- every swing point handed
        # in here is always derived from (and its date always present in) this same `price`
        # series, directly (`find_divergences`) or via a prefix slice that's still guaranteed
        # to include it (`confirmed_divergence_as_of`'s "already confirmed" filter). Guarded
        # rather than assumed, in case a future caller passes a `price` that doesn't actually
        # match where `swings` came from.
        return None  # pragma: no cover
    first_position = price.index.get_loc(first_point.index)
    second_position = price.index.get_loc(second_point.index)
    if not isinstance(first_position, int) or not isinstance(second_position, int):
        # `Index.get_loc` returns a slice/boolean-array for a non-unique index instead of a
        # single int -- unreachable for this app's own always-unique daily-bar date indices,
        # but guarded rather than silently misusing a non-int in the bar-count subtraction
        # below.
        return None  # pragma: no cover
    bars_apart = second_position - first_position
    if not is_spacing_valid(bars_apart, min_bars=min_bars_apart, max_bars=max_bars_apart):
        return None

    centerline_crossed: bool | None = None
    if indicator_name == "macd_histogram":
        centerline_crossed = macd_centerline_crossed(
            indicator, first_point.index, second_point.index, kind
        )
        if not centerline_crossed:
            return None  # "no crossover, no divergence" -- not a divergence at all.

    beyond_reference_line: bool | None = None
    if indicator_name == "stochastic":
        beyond_reference_line = is_beyond_reference_line(
            float(first_indicator_value),
            float(second_indicator_value),
            kind,
            oversold=_STOCHASTIC_OVERSOLD,
            overbought=_STOCHASTIC_OVERBOUGHT,
        )
    elif indicator_name == "rsi":
        # Explicit, not relying on `is_beyond_reference_line`'s own default parameters --
        # those defaults happen to equal RSI's own constants today (both 30.0/70.0), but the
        # two pairs are deliberately kept distinct (see `_RSI_OVERSOLD`/`_RSI_OVERBOUGHT`'s own
        # comment) precisely so one can diverge from the other later without silently breaking
        # this call site (docs/tasks/backend-divergence-detection-followups.json).
        beyond_reference_line = is_beyond_reference_line(
            float(first_indicator_value),
            float(second_indicator_value),
            kind,
            oversold=_RSI_OVERSOLD,
            overbought=_RSI_OVERBOUGHT,
        )

    first_extreme = DivergenceExtreme(
        date=cast(pd.Timestamp, first_point.index),
        price=first_point.value,
        indicator_value=float(first_indicator_value),
    )
    second_extreme = DivergenceExtreme(
        date=cast(pd.Timestamp, second_point.index),
        price=second_point.value,
        indicator_value=float(second_indicator_value),
    )

    return Divergence(
        indicator=indicator_name,
        kind=kind,
        first=first_extreme,
        second=second_extreme,
        bars_apart=bars_apart,
        centerline_crossed=centerline_crossed,
        beyond_reference_line=beyond_reference_line,
        aborted=_is_aborted(price, second_extreme, kind),
    )


def divergences_from_swings(
    swings: list[SwingPoint],
    price: pd.Series,
    indicator: pd.Series,
    *,
    indicator_name: DivergenceIndicator,
    kind: DivergenceKind,
    min_bars_apart: int = MIN_SWING_SPACING_BARS,
    max_bars_apart: int = MAX_SWING_SPACING_BARS,
    max_second_extreme_depth_ratio: float = MAX_SECOND_EXTREME_DEPTH_RATIO,
) -> list[Divergence]:
    """Evaluates every chronologically-consecutive pair in ``swings`` (already restricted to
    one kind and chronologically ordered by the caller -- swing lows for a bullish scan, swing
    highs for bearish, e.g. via ``find_divergences`` or ``confirmed_divergence_as_of``'s own
    precomputed-and-filtered swing list) as a candidate divergence. Returns only the pairs that
    qualify, oldest first -- most callers only need the most recent one (``latest_divergence``/
    ``current_divergence``/``confirmed_divergence_as_of``); this is the shared low-level
    primitive every one of them is built on, and is itself the right entry point for a caller
    that wants every historical divergence (e.g. this module's own reference tests)."""
    results = []
    for first_point, second_point in zip(swings, swings[1:], strict=False):
        divergence = _evaluate_pair(
            first_point,
            second_point,
            price,
            indicator,
            indicator_name=indicator_name,
            kind=kind,
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if divergence is not None:
            results.append(divergence)
    return results


def find_divergences(
    price: pd.Series,
    indicator: pd.Series,
    *,
    indicator_name: DivergenceIndicator,
    kind: DivergenceKind,
    window: int = DEFAULT_SWING_WINDOW,
    min_bars_apart: int = MIN_SWING_SPACING_BARS,
    max_bars_apart: int = MAX_SWING_SPACING_BARS,
    max_second_extreme_depth_ratio: float = MAX_SECOND_EXTREME_DEPTH_RATIO,
) -> list[Divergence]:
    """Every qualifying ``kind`` divergence between ``price``'s own swing points (lows for
    bullish, highs for bearish -- ``app.signals.swing_points``) and ``indicator``'s value at
    those same dates, across ``price``'s full history. Oldest first.

    Runs swing-point detection fresh on the full ``price`` series every call -- fine for a
    single whole-history pass (e.g. GET /api/stocks/{ticker}/analysis, or this module's own
    reference tests), but a caller re-running this once per bar over a growing prefix (e.g.
    app.signals.engine.analyse_history) should use ``build_divergence_swing_cache`` +
    ``confirmed_divergence_as_of`` instead, to avoid an O(history_length) swing-point re-scan
    on every one of up to thousands of calls -- see that pair's own docstrings."""
    swings = swing_lows(price, window=window) if kind == "bullish" else swing_highs(price, window=window)
    return divergences_from_swings(
        swings,
        price,
        indicator,
        indicator_name=indicator_name,
        kind=kind,
        min_bars_apart=min_bars_apart,
        max_bars_apart=max_bars_apart,
        max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
    )


def latest_divergence(
    price: pd.Series,
    indicator: pd.Series,
    *,
    indicator_name: DivergenceIndicator,
    window: int = DEFAULT_SWING_WINDOW,
    min_bars_apart: int = MIN_SWING_SPACING_BARS,
    max_bars_apart: int = MAX_SWING_SPACING_BARS,
    max_second_extreme_depth_ratio: float = MAX_SECOND_EXTREME_DEPTH_RATIO,
) -> Divergence | None:
    """The single most recent qualifying divergence (bullish or bearish, whichever's ``second``
    extreme date is more recent) for one indicator against ``price``. ``None`` if neither side
    has any qualifying divergence."""
    candidates = find_divergences(
        price,
        indicator,
        indicator_name=indicator_name,
        kind="bullish",
        window=window,
        min_bars_apart=min_bars_apart,
        max_bars_apart=max_bars_apart,
        max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
    )
    candidates += find_divergences(
        price,
        indicator,
        indicator_name=indicator_name,
        kind="bearish",
        window=window,
        min_bars_apart=min_bars_apart,
        max_bars_apart=max_bars_apart,
        max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
    )
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.second.date)


# Tie-break order when more than one indicator's `latest_divergence` shares the exact same
# `second.date` (common in practice -- all three indicators are checked against the same
# price swing points, see module docstring) -- MACD-Histogram first ("his usual choice" per
# docs/ideas.md), then Stochastic, then RSI (docs/Analyse.md §4's own row order for these three
# oscillators). See this task's `decisions` entry.
_INDICATOR_PRIORITY: dict[DivergenceIndicator, int] = {
    "macd_histogram": 0,
    "stochastic": 1,
    "rsi": 2,
}


def _pick_most_recent(candidates: list[Divergence]) -> Divergence | None:
    if not candidates:
        return None
    most_recent_date = max(d.second.date for d in candidates)
    most_recent = [d for d in candidates if d.second.date == most_recent_date]
    return min(most_recent, key=lambda d: _INDICATOR_PRIORITY[d.indicator])


def current_divergence(
    price: pd.Series,
    *,
    macd_histogram: pd.Series | None = None,
    stochastic: pd.Series | None = None,
    rsi: pd.Series | None = None,
    window: int = DEFAULT_SWING_WINDOW,
    min_bars_apart: int = MIN_SWING_SPACING_BARS,
    max_bars_apart: int = MAX_SWING_SPACING_BARS,
    max_second_extreme_depth_ratio: float = MAX_SECOND_EXTREME_DEPTH_RATIO,
) -> Divergence | None:
    """The single "current divergence state" this app exposes (``AnalysisResponse.divergence``,
    docs/architecture/API.md) -- the most recent qualifying divergence across whichever of
    macd_histogram/stochastic/rsi are supplied (any subset; a ``None`` series is simply
    skipped). See ``_INDICATOR_PRIORITY`` for the tie-break rule.

    Written as three explicit (not looped-over) indicator checks -- rather than iterating a
    ``(name, series)`` tuple list -- so each ``indicator_name`` argument stays a precise string
    literal for static type-checking, instead of widening to plain ``str`` across a
    heterogeneous loop."""
    candidates: list[Divergence] = []
    if macd_histogram is not None:
        found = latest_divergence(
            price,
            macd_histogram,
            indicator_name="macd_histogram",
            window=window,
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if found is not None:
            candidates.append(found)
    if stochastic is not None:
        found = latest_divergence(
            price,
            stochastic,
            indicator_name="stochastic",
            window=window,
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if found is not None:
            candidates.append(found)
    if rsi is not None:
        found = latest_divergence(
            price,
            rsi,
            indicator_name="rsi",
            window=window,
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if found is not None:
            candidates.append(found)
    return _pick_most_recent(candidates)


@dataclass(frozen=True)
class DivergenceSwingCache:
    """Precomputed, position-indexed PRICE swing points -- built once over the full series via
    ``build_divergence_swing_cache``, then reused across every bar of a growing-window caller
    (``app.signals.engine.analyse_history``) via ``confirmed_divergence_as_of``, instead of
    every bar re-running the O(history_length) swing-point scan on its own truncated prefix (an
    O(history_length^2) total cost across a whole history otherwise -- the same concern
    ``app.signals.engine``'s other precomputed/passthrough series already address for their own
    O(history_length) computations). See this task's `decisions` entry."""

    price: pd.Series
    lows: list[SwingPoint]
    low_positions: list[int]
    highs: list[SwingPoint]
    high_positions: list[int]
    window: int


def build_divergence_swing_cache(
    price: pd.Series, *, window: int = DEFAULT_SWING_WINDOW
) -> DivergenceSwingCache:
    """Builds a ``DivergenceSwingCache`` for ``price`` (typically a ticker's full daily close
    series) -- one swing-point pass in each direction, shared by every later
    ``confirmed_divergence_as_of`` call regardless of how many indicators/bars it's asked
    about."""
    lows = swing_lows(price, window=window)
    highs = swing_highs(price, window=window)
    return DivergenceSwingCache(
        price=price,
        lows=lows,
        low_positions=[price.index.get_loc(p.index) for p in lows],
        highs=highs,
        high_positions=[price.index.get_loc(p.index) for p in highs],
        window=window,
    )


def _most_recent_confirmed(
    confirmed_lows: list[SwingPoint],
    confirmed_highs: list[SwingPoint],
    price_slice: pd.Series,
    series_slice: pd.Series,
    indicator_name: DivergenceIndicator,
    *,
    min_bars_apart: int,
    max_bars_apart: int,
    max_second_extreme_depth_ratio: float,
) -> Divergence | None:
    """The most recent qualifying divergence for one indicator, from an already-confirmed
    (no-look-ahead-filtered) swing list -- the ``confirmed_divergence_as_of``-only counterpart
    to ``latest_divergence`` (which instead runs swing-point detection itself over the full,
    untruncated ``price``)."""
    candidates: list[Divergence] = []
    bullish = divergences_from_swings(
        confirmed_lows,
        price_slice,
        series_slice,
        indicator_name=indicator_name,
        kind="bullish",
        min_bars_apart=min_bars_apart,
        max_bars_apart=max_bars_apart,
        max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
    )
    if bullish:
        candidates.append(bullish[-1])
    bearish = divergences_from_swings(
        confirmed_highs,
        price_slice,
        series_slice,
        indicator_name=indicator_name,
        kind="bearish",
        min_bars_apart=min_bars_apart,
        max_bars_apart=max_bars_apart,
        max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
    )
    if bearish:
        candidates.append(bearish[-1])
    return _pick_most_recent(candidates)


def confirmed_divergence_as_of(
    cache: DivergenceSwingCache,
    position: int,
    *,
    macd_histogram: pd.Series | None = None,
    stochastic: pd.Series | None = None,
    rsi: pd.Series | None = None,
    min_bars_apart: int = MIN_SWING_SPACING_BARS,
    max_bars_apart: int = MAX_SWING_SPACING_BARS,
    max_second_extreme_depth_ratio: float = MAX_SECOND_EXTREME_DEPTH_RATIO,
) -> Divergence | None:
    """The same "current divergence state" ``current_divergence`` computes, but restricted to
    only the swing points confirmable using data available through ``position`` (inclusive) --
    no look-ahead -- and using ``cache``'s already-computed full-history swing points instead
    of re-running swing-point detection on a truncated prefix.

    A swing point needs ``cache.window`` bars on both sides to confirm (``app.signals.
    swing_points``), so a swing at position ``p`` is confirmed as of ``position`` only once
    ``p + cache.window <= position``. ``cache.price``/``macd_histogram``/``stochastic``/``rsi``
    are each read only up to and including ``position`` (a positional slice) for the same
    no-look-ahead reason -- matching ``app.signals.engine.analyse_history``'s own per-bar
    truncation contract for every other series it passes through.

    **Known residual look-ahead leak (narrow, documented rather than fixed -- docs/tasks/
    backend-divergence-detection-followups.json):** for a swing point born from a run of 3+
    *exact-value-tied* consecutive bars, ``app.signals.swing_points``'s plateau-merge
    convention reports the point at the run's middle bar (``p``), and this function's confirm
    threshold (``p + cache.window <= position``) is measured from that reported position. But a
    genuinely causal recomputation over data truncated to ``position`` can see a *shorter*
    plateau run near the truncation boundary (the run's later bars aren't visible yet), which
    merges to an earlier middle bar than the full-series merge eventually converges to.
    Concretely: for a 5-bar tied plateau at positions 5-9, the full series merges to position 7
    (this function's own threshold then confirms it at ``position >= 10``), but a causal
    recomputation truncated to position 10 still only sees positions 5-9's neighborhood as a
    plateau lacking its true right edge and reports the merged point at position 6, not 7 --
    convergence to 7 only happens once truncated at position 11. So at ``position == 10``, this
    function reports a swing point one bar earlier than a truly causal recomputation would -- a
    real, if narrow, look-ahead leak specific to swing points born from an exact multi-bar tie.
    Left undefended rather than fixed (e.g. by tightening the threshold to key off the
    plateau run's own last raw-candidate position instead of the merged point's reported
    position) because an exact multi-bar tie in real float price/indicator data is vanishingly
    rare outside synthetic/constructed data -- the same "vanishingly rare outside synthetic
    data" reasoning this task's own `decisions` entry already applied to a related-but-distinct
    question (whether plateau merging distorts the Lovvorn spacing filter's bar-count
    measurement); that entry's "no mitigation needed" conclusion did not, however, cover this
    confirm-threshold correctness question specifically, which is why it's called out here on
    its own."""
    confirmed_lows = [
        point
        for point, swing_position in zip(cache.lows, cache.low_positions, strict=True)
        if swing_position + cache.window <= position
    ]
    confirmed_highs = [
        point
        for point, swing_position in zip(cache.highs, cache.high_positions, strict=True)
        if swing_position + cache.window <= position
    ]
    price_slice = cache.price.iloc[: position + 1]

    candidates: list[Divergence] = []
    if macd_histogram is not None:
        found = _most_recent_confirmed(
            confirmed_lows,
            confirmed_highs,
            price_slice,
            macd_histogram.iloc[: position + 1],
            "macd_histogram",
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if found is not None:
            candidates.append(found)
    if stochastic is not None:
        found = _most_recent_confirmed(
            confirmed_lows,
            confirmed_highs,
            price_slice,
            stochastic.iloc[: position + 1],
            "stochastic",
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if found is not None:
            candidates.append(found)
    if rsi is not None:
        found = _most_recent_confirmed(
            confirmed_lows,
            confirmed_highs,
            price_slice,
            rsi.iloc[: position + 1],
            "rsi",
            min_bars_apart=min_bars_apart,
            max_bars_apart=max_bars_apart,
            max_second_extreme_depth_ratio=max_second_extreme_depth_ratio,
        )
        if found is not None:
            candidates.append(found)
    return _pick_most_recent(candidates)
