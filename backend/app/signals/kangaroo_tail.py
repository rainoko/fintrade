"""Kangaroo Tail ("fingers") reversal-pattern detection -- Elder ch. 20, pp. 65-67 (see
docs/ideas.md's own transcription and docs/tasks/backend-kangaroo-tail-pattern.json's
`decisions` entry for every judgment call below; this module and task are completely
independent of everything else already in ``app.signals`` -- no candlestick-pattern detection
existed anywhere in this codebase before it).

**What a Kangaroo Tail is** (docs/ideas.md): a single daily bar whose range is roughly 2-3x
the recent average bar range, protruding from a tight recent range, where the close ends up
back near the open (not at the extreme) -- flanked by two bars of normal height. An
upward-pointing tail (new high, closes back down) is a bearish reversal signal; a
downward-pointing tail (new low, closes back up) is a bullish reversal signal.

**This is purely an OHLC pattern** -- no new indicator/EMA/oscillator is involved, just a
bar-range-vs-recent-average-range comparison plus a confirming next bar, exactly as
docs/ideas.md's own "Implementation shape" framing describes it.

**Algorithm** (every threshold below is this task's own judgment call -- the book gives the
qualitative shape precisely but no mechanical numbers, same situation
``app.signals.support_resistance`` was in for its own zone-detection algorithm):

1. **Baseline "average bar range"**: the mean ``high - low`` over the ``lookback`` (default
   10, ~2 trading weeks) daily bars immediately preceding the candidate tail bar. A small
   baseline value is itself what "protruding from a tight recent range" means here -- no
   separate volatility-tightness check is needed beyond the range-multiplier comparison below.
2. **Tail qualification**: the candidate bar's own ``high - low`` must be at least
   ``range_multiplier`` (default 2.5, the midpoint of the book's own "roughly 2-3x") times
   that baseline, AND its ``high``/``low`` must be a genuine new extreme beyond the *whole*
   lookback window (not just larger than average) -- "protruding from a tight recent range",
   read literally as *sticking out past* that range, not merely wider than its own bars.
3. **Body position ("close ends up back near the open, not at the extreme")**: both the open
   and the close must sit in the half of the bar's own range *farthest* from the tip (the new
   high for an upward tail, the new low for a downward one) -- i.e. each retraces at least
   ``min_retracement`` (default 0.5, the midpoint of the range) back from the tip.
4. **Flanked by two bars of normal height**: the bar immediately before AND the bar
   immediately after the candidate must each fail the tail-qualification range-multiplier test
   themselves (i.e. neither is itself a tail-sized outlier).
5. **Confirming next bar**: the very same next bar (the second flanking bar in (4)) must also
   *close* in the direction the reversal implies -- below the tail's own close for an upward
   (bearish) tail, above it for a downward (bullish) one. This is a hard gate, not an
   informational flag -- a `KangarooTail` is only ever returned once genuinely confirmed (see
   this task's `decisions` entry for why, mirroring
   ``app.signals.divergence``'s MACD-Histogram centerline-crossing precedent: "no
   confirmation, no signal").

**Suggested stop** ("halfway through the tail, not at its tip -- too wide -- or its base --
too tight"): the tail bar's own range midpoint, ``(high + low) / 2``. The tip is the bar's own
extreme (``high`` for an upward tail, ``low`` for a downward one); the base is the opposite end
of the same range, which -- given the body-position requirement in (3) above already
constrains both open and close to sit in that opposite half -- is a faithful, literal "halfway
through the tail" reference without inventing a separate open/close-based formula. See this
task's `decisions` entry.

**No look-ahead, no global re-ranking**: unlike ``app.signals.support_resistance``'s zone list
(capped to the strongest 15, a decision that depends on comparing *every* detected zone against
each other) or ``app.signals.divergence``'s swing-point confirmation (which needs a window of
*future* bars beyond a swing point before it's trustworthy), a single candidate bar's
qualification here depends only on bars up to and including its own confirming next bar --
nothing beyond that ever changes whether it qualifies. This means ``detect_kangaroo_tails`` can
be run once over the *full* available history and its results simply filtered by confirming-bar
position for a caller (``app.signals.engine.analyse_history``) that needs a genuinely
no-look-ahead "as of this bar" answer per bar -- no swing-point-style confirmation cache is
needed, just a plain sorted list.

**Vectorized implementation** (docs/tasks/backend-portfolio-load-performance-followups-followups.json's
`decisions` entry has the full before/after measurement): `detect_kangaroo_tails` used to loop
once per bar (`_evaluate_candidate`), re-slicing a `lookback`-row window and re-running
`.mean()`/`.max()`/`.min()`/several scalar `.iloc[...]` lookups on every one of the ~11,528 bars
scanned for a realistic full-history daily series -- measured at ~1.6-1.8s for one ~11,539-row
ticker (AAPL-scale history), the dominant CPU-bound cost of a realistic swing-mode portfolio
load (`backend-portfolio-load-performance-followups`'s own investigation). It's now a single
vectorized pass: `pandas.Series.rolling(lookback).mean()/.max()/.min()` (each `.shift(1)`ed so
the window at position `i` covers exactly bars `i-lookback` through `i-1`, matching the old
per-bar slice `daily_ohlcv.iloc[position - lookback : position]` bar-for-bar) computes every
candidate's baseline range/window extremes across the whole series at once;
`pandas.Series.shift(1)`/`.shift(-1)` read the flanking bars' own ranges and the confirming
bar's close the same way. Every per-bar boolean check (tail-sized, new-extreme,
body-retraced-from-tip, flanks-normal, confirms-direction) becomes one elementwise numpy
comparison over the full array, `&`-combined into a single final boolean mask -- only the
positions where every check passes (typically a small handful, not thousands) are then turned
into `KangarooTail` objects, so the O(n) cost is now pandas' own compiled rolling/shift
implementation rather than n Python-level function calls. This produced a measured ~1.66s ->
~0.0017s (~955x) speedup on the same synthetic ~11,539-row random-walk fixture (0 tails present),
and ~1.68s -> ~0.0022s (~765x) on a second, purpose-built ~11,539-row fixture with 460 candidate
patterns injected every ~25 bars (10 of which pass every gate) -- exercising the actual
tail-detection/rejection branches at scale, not just the "nothing qualifies" case. Both fixtures'
old-vs-new output matched EXACTLY (every field of every `KangarooTail`, not just the count) when
independently cross-checked against the pre-vectorization implementation -- see this task's own
`decisions` entry for the full methodology. See this module's own test suite
(`tests/unit/signals/test_kangaroo_tail.py`) for the hand-computed reference values this rewrite
is verified against -- the pre-existing reference-value tests (written against the old per-bar
implementation, using a flat, hand-computable filler baseline) are reused verbatim here, proving
the rewrite reproduces the book-derived algorithm's exact behavior, not just "agrees with the old
code on one large random fixture" (see this task's own `decisions` entry for why that distinction
mattered enough to block shipping the original prototype)."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Direction = Literal["up", "down"]

# Trading days of prior bars the "recent average bar range" baseline is computed over --
# roughly 2 trading weeks. Also doubles as the window a candidate's high/low must protrude
# beyond ("a tight recent range"). See this task's `decisions` entry.
DEFAULT_LOOKBACK = 10

# The book says "roughly 2-3x" the recent average bar range -- 2.5 is the midpoint of that
# range, used both for the tail's own qualification and (reused, not a second invented number)
# for what counts as "normal height" on the two flanking bars. See this task's `decisions`.
DEFAULT_RANGE_MULTIPLIER = 2.5

# Both the tail bar's open AND close must retrace at least this fraction of the bar's own
# range back from the tip (the new high/low) -- i.e. sit in the far half, away from the
# extreme -- for "the close ends up back near the open, not at the extreme". See this task's
# `decisions`.
DEFAULT_MIN_RETRACEMENT = 0.5

_REQUIRED_COLUMNS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class KangarooTail:
    """One confirmed Kangaroo Tail reversal pattern.

    ``direction`` is the tail's own physical shape: ``"up"`` (a new high, closing back down --
    Elder's bearish reversal reading) or ``"down"`` (a new low, closing back up -- bullish).

    ``date`` is the tail bar's own date; ``confirmed_date`` is the very next bar's date -- the
    one whose own close/range made this a genuine, confirmed pattern rather than just a
    candidate shape (see this module's docstring, point 5). Both are exposed (rather than only
    ``date``) since a consumer walking history bar-by-bar (``app.signals.engine.analyse_history``)
    can only know about this pattern once ``confirmed_date``'s own bar has arrived -- exactly
    the same "point A happened, but not knowable as of any bar earlier than point B" shape
    ``app.signals.divergence.Divergence`` already has for its own two dated extremes.

    ``high``/``low`` are the tail bar's own values; ``range_multiple`` is how many times the
    recent average bar range this bar's own range was (always >= the qualifying
    ``range_multiplier`` threshold). ``suggested_stop`` is the tail's own range midpoint
    (``(high + low) / 2``) -- see this module's docstring for why that's "halfway through the
    tail"."""

    direction: Direction
    date: pd.Timestamp
    confirmed_date: pd.Timestamp
    high: float
    low: float
    range_multiple: float
    suggested_stop: float


def _validate_columns(daily_ohlcv: pd.DataFrame) -> None:
    missing = _REQUIRED_COLUMNS - set(daily_ohlcv.columns)
    if missing:
        raise ValueError(f"daily_ohlcv is missing required column(s): {sorted(missing)}")


def detect_kangaroo_tails(
    daily_ohlcv: pd.DataFrame,
    *,
    lookback: int = DEFAULT_LOOKBACK,
    range_multiplier: float = DEFAULT_RANGE_MULTIPLIER,
    min_retracement: float = DEFAULT_MIN_RETRACEMENT,
) -> list[KangarooTail]:
    """Scans the full ``daily_ohlcv`` history for confirmed Kangaroo Tail patterns (Elder
    ch. 20, see this module's docstring for the full algorithm). Returns only genuinely
    confirmed tails -- a candidate whose shape matches but whose confirming next bar doesn't
    pass every check in this module's docstring's point 4-5 is not returned at all, not
    returned with a `confirmed=False` flag (see this task's `decisions` entry for why).

    Returns tails chronologically ordered by ``date`` ascending (equivalently by
    ``confirmed_date``, since detection is a simple forward scan with no cross-candidate
    ranking). Expects ``daily_ohlcv`` already cleaned of malformed bars (matching every other
    function in ``app.signals`` -- see ``app.signals.engine.drop_malformed_daily_bars``); this
    function does not clean it itself.

    **Vectorized** (see this module's docstring's "Vectorized implementation" section for the
    full before/after story): every candidate position's checks are computed as a single
    elementwise numpy comparison over the whole series at once, rather than a per-bar Python
    loop -- functionally equivalent to evaluating each bar independently (this function's own
    docstring, points 1-5), just computed in bulk.

    Raises:
        ValueError: if ``daily_ohlcv`` is non-empty but missing a required column
            (``open``/``high``/``low``/``close``), or if ``lookback`` is less than 1.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1 (got {lookback})")
    if daily_ohlcv.empty:
        return []
    _validate_columns(daily_ohlcv)

    n = len(daily_ohlcv)
    # A candidate needs `lookback` bars before it and 1 bar after it -- too short a series has
    # no valid candidate position at all (mirrors the old loop's `range(lookback, n - 1)` being
    # empty whenever `n - 1 <= lookback`).
    if n < lookback + 2:
        return []

    high = daily_ohlcv["high"].to_numpy(dtype=float)
    low = daily_ohlcv["low"].to_numpy(dtype=float)
    open_ = daily_ohlcv["open"].to_numpy(dtype=float)
    close = daily_ohlcv["close"].to_numpy(dtype=float)
    bar_range = high - low

    # Baseline "average bar range" (point 1): the mean bar range over the `lookback` bars
    # immediately preceding each position -- a rolling mean over a window ENDING at the
    # previous bar, i.e. `.shift(1)` after `.rolling(lookback)` so the window at position `i`
    # covers exactly bars `i-lookback` through `i-1` (bar-for-bar identical to the old
    # `daily_ohlcv.iloc[position - lookback : position]` slice). Positions with fewer than
    # `lookback` prior bars get NaN here, which every comparison below treats as "does not
    # qualify" -- exactly mirroring the old loop never considering those positions at all.
    bar_range_series = pd.Series(bar_range)
    baseline_range = bar_range_series.rolling(lookback).mean().shift(1).to_numpy()
    window_high_max = pd.Series(high).rolling(lookback).max().shift(1).to_numpy()
    window_low_min = pd.Series(low).rolling(lookback).min().shift(1).to_numpy()
    before_range = bar_range_series.shift(1).to_numpy()
    after_range = bar_range_series.shift(-1).to_numpy()
    confirming_close = pd.Series(close).shift(-1).to_numpy()

    with np.errstate(invalid="ignore", divide="ignore"):
        baseline_positive = baseline_range > 0

        # Point 2: tail qualification -- own range >= range_multiplier * baseline, AND a
        # genuine new extreme beyond the whole lookback window (not just wider than average).
        is_tail_sized = baseline_positive & (bar_range >= range_multiplier * baseline_range)
        makes_new_high = high > window_high_max
        makes_new_low = low < window_low_min
        qualifies_extreme = makes_new_high | makes_new_low

        # "up" takes priority on the degenerate outside-bar tie (both a new high AND a new low
        # at once) -- see this module's docstring, point 2, and
        # docs/tasks/backend-kangaroo-tail-pattern-followups.json's `decisions` entry for the
        # original scalar tie-break this reproduces exactly (`"up" if makes_new_high else
        # "down"`, only ever reached once `qualifies_extreme` holds).
        direction_is_up = makes_new_high

        # Point 3: body position -- both open and close must retrace at least
        # `min_retracement` of the bar's own range back from the tip. Computed for both
        # directions unconditionally (cheap elementwise numpy math) then selected via
        # `np.where`; a zero `bar_range` would otherwise divide to +-inf, so it's masked out
        # explicitly (`bar_range > 0`) rather than relying on an inf/NaN comparison happening
        # to come out False -- the old scalar `_body_retraced_from_tip` had the identical
        # `bar_range <= 0: return False` guard for the same reason.
        up_open_retracement = (high - open_) / bar_range
        up_close_retracement = (high - close) / bar_range
        down_open_retracement = (open_ - low) / bar_range
        down_close_retracement = (close - low) / bar_range
        body_ok_up = (up_open_retracement >= min_retracement) & (up_close_retracement >= min_retracement)
        body_ok_down = (down_open_retracement >= min_retracement) & (down_close_retracement >= min_retracement)
        body_ok = np.where(direction_is_up, body_ok_up, body_ok_down) & (bar_range > 0)

        # Point 4: flanked by two bars of normal height -- neither the immediately-before nor
        # immediately-after bar may itself be tail-sized, against the SAME baseline computed
        # for the candidate position (matching the old code passing the candidate's own
        # `baseline_range` into both flanking checks, not a baseline recomputed for the
        # flanking bar's own position).
        before_tail_sized = baseline_positive & (before_range >= range_multiplier * baseline_range)
        after_tail_sized = baseline_positive & (after_range >= range_multiplier * baseline_range)
        flanks_normal = ~before_tail_sized & ~after_tail_sized

        # Point 5: confirming next bar -- its close must continue in the reversal's direction.
        # `confirming_close` is NaN for the very last position (no bar after it exists), and a
        # NaN comparison is always False in numpy, so the last position is naturally excluded
        # here without a separate bounds check (the old loop's `range(lookback, n - 1))` upper
        # bound achieved the same exclusion structurally instead).
        confirms_up = confirming_close < close
        confirms_down = confirming_close > close
        confirms_ok = np.where(direction_is_up, confirms_up, confirms_down)

        qualifies = is_tail_sized & qualifies_extreme & body_ok & flanks_normal & confirms_ok
        # Only ever read (below) at a `qualifies` position, where `baseline_positive` is
        # already guaranteed True (via `is_tail_sized`) -- computed under the same
        # divide-by-zero/NaN suppression as everything else above for the same reason.
        range_multiple = bar_range / baseline_range

    suggested_stop = (high + low) / 2
    index = daily_ohlcv.index

    tails = []
    for position in np.flatnonzero(qualifies):
        direction: Direction = "up" if direction_is_up[position] else "down"
        tails.append(
            KangarooTail(
                direction=direction,
                date=index[position],
                confirmed_date=index[position + 1],
                high=float(high[position]),
                low=float(low[position]),
                range_multiple=float(range_multiple[position]),
                suggested_stop=float(suggested_stop[position]),
            )
        )
    return tails


def latest_kangaroo_tail(
    daily_ohlcv: pd.DataFrame,
    *,
    lookback: int = DEFAULT_LOOKBACK,
    range_multiplier: float = DEFAULT_RANGE_MULTIPLIER,
    min_retracement: float = DEFAULT_MIN_RETRACEMENT,
) -> KangarooTail | None:
    """The single most recently confirmed Kangaroo Tail across ``daily_ohlcv``'s full history
    (``None`` if none), matching the "current state" convention
    ``app.signals.divergence.current_divergence`` already established for this app's other
    detect-and-expose-the-most-recent-one signals."""
    tails = detect_kangaroo_tails(
        daily_ohlcv,
        lookback=lookback,
        range_multiplier=range_multiplier,
        min_retracement=min_retracement,
    )
    return tails[-1] if tails else None


@dataclass(frozen=True)
class KangarooTailCache:
    """Precomputed, position-indexed Kangaroo Tails -- built once over the full daily series
    via ``build_kangaroo_tail_cache``, then reused across every bar of a growing-window caller
    (``app.signals.engine.analyse_history``) via ``kangaroo_tail_confirmed_as_of``, mirroring
    ``app.signals.divergence.DivergenceSwingCache``'s own precompute-once-reuse-per-bar shape
    -- though, per this module's docstring's "No look-ahead, no global re-ranking" section,
    this cache needs no re-filtering logic beyond storing each tail's own confirming bar's
    positional index for a direct integer comparison per bar."""

    tails: list[KangarooTail]
    confirmed_positions: list[int]


def build_kangaroo_tail_cache(
    daily_ohlcv: pd.DataFrame,
    *,
    lookback: int = DEFAULT_LOOKBACK,
    range_multiplier: float = DEFAULT_RANGE_MULTIPLIER,
    min_retracement: float = DEFAULT_MIN_RETRACEMENT,
) -> KangarooTailCache:
    """Builds a ``KangarooTailCache`` for ``daily_ohlcv`` (typically a ticker's full daily
    OHLCV series) -- one whole-history Kangaroo Tail scan, shared by every later
    ``kangaroo_tail_confirmed_as_of`` call regardless of how many bars it's asked about."""
    tails = detect_kangaroo_tails(
        daily_ohlcv,
        lookback=lookback,
        range_multiplier=range_multiplier,
        min_retracement=min_retracement,
    )
    # `Index.get_loc` returns a slice/boolean-array for a non-unique index instead of a single
    # int -- unreachable for this app's own always-unique daily-bar date indices (matching
    # app.signals.divergence's identical `isinstance` guard for the same get_loc pattern,
    # divergence.py's `_evaluate_pair`), but guarded rather than silently letting a non-int
    # position flow into `kangaroo_tail_confirmed_as_of`'s `confirmed_position > position`
    # comparison, which would raise a TypeError there instead of degrading gracefully here
    # (docs/tasks/backend-kangaroo-tail-pattern-followups.json). `tails`/`confirmed_positions`
    # are filtered together so they stay index-parallel for `kangaroo_tail_confirmed_as_of`'s
    # own `zip(..., strict=True)`.
    filtered_tails: list[KangarooTail] = []
    confirmed_positions: list[int] = []
    for tail in tails:
        position = daily_ohlcv.index.get_loc(tail.confirmed_date)
        if not isinstance(position, int):
            continue  # pragma: no cover
        filtered_tails.append(tail)
        confirmed_positions.append(position)
    return KangarooTailCache(tails=filtered_tails, confirmed_positions=confirmed_positions)


def kangaroo_tail_confirmed_as_of(cache: KangarooTailCache, position: int) -> KangarooTail | None:
    """The most recently confirmed ``KangarooTail`` in ``cache`` whose own confirming bar is at
    or before positional index ``position`` -- the per-bar "as of this bar, no look-ahead"
    counterpart to ``latest_kangaroo_tail``, for
    ``app.signals.engine.analyse_history``'s growing-prefix walk.

    ``cache.tails`` is already ordered by ``confirmed_date``/``confirmed_positions`` ascending
    (``detect_kangaroo_tails``' own return contract, a simple forward scan with no
    cross-candidate ranking -- see this module's docstring's "No look-ahead, no global
    re-ranking" section), so the most recent one confirmable as of ``position`` is simply the
    last one in iteration order whose ``confirmed_position <= position``."""
    result: KangarooTail | None = None
    for tail, confirmed_position in zip(cache.tails, cache.confirmed_positions, strict=True):
        if confirmed_position > position:
            break
        result = tail
    return result
