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
"""

from dataclasses import dataclass
from typing import Literal

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


def _bar_range(daily_ohlcv: pd.DataFrame, position: int) -> float:
    return float(daily_ohlcv["high"].iloc[position] - daily_ohlcv["low"].iloc[position])


def _is_tail_sized(bar_range: float, baseline_range: float, range_multiplier: float) -> bool:
    """Whether a single bar's own range qualifies as tail-sized against ``baseline_range`` --
    shared by both the candidate tail's own qualification and the "normal height" flanking-bar
    check (a flanking bar must NOT itself be tail-sized)."""
    if baseline_range <= 0:
        return False
    return bar_range >= range_multiplier * baseline_range


def _body_retraced_from_tip(
    direction: Direction,
    open_: float,
    close: float,
    high: float,
    low: float,
    bar_range: float,
    min_retracement: float,
) -> bool:
    """Whether both ``open_`` and ``close`` sit at least ``min_retracement`` of ``bar_range``
    away from the tip (``high`` for an upward tail, ``low`` for a downward one) -- "the close
    ends up back near the open, not at the extreme". See this module's docstring, point 3."""
    if bar_range <= 0:
        return False
    if direction == "up":
        open_retracement = (high - open_) / bar_range
        close_retracement = (high - close) / bar_range
    else:
        open_retracement = (open_ - low) / bar_range
        close_retracement = (close - low) / bar_range
    return open_retracement >= min_retracement and close_retracement >= min_retracement


def _confirms_direction(direction: Direction, tail_close: float, confirming_close: float) -> bool:
    """Whether the confirming (next) bar's close continues in the direction the tail's
    reversal implies -- below the tail's own close for an upward (bearish) tail, above it for
    a downward (bullish) one. See this module's docstring, point 5."""
    if direction == "up":
        return confirming_close < tail_close
    return confirming_close > tail_close


def _evaluate_candidate(
    daily_ohlcv: pd.DataFrame,
    position: int,
    *,
    lookback: int,
    range_multiplier: float,
    min_retracement: float,
) -> KangarooTail | None:
    """Evaluates bar ``position`` as a candidate Kangaroo Tail, requiring bars
    ``position - lookback`` through ``position + 1`` to all exist. Returns ``None`` the moment
    any check fails, or the confirmed ``KangarooTail`` if every one passes -- see this module's
    docstring for the full ordered algorithm."""
    window = daily_ohlcv.iloc[position - lookback : position]
    baseline_range = float((window["high"] - window["low"]).mean())

    bar_range = _bar_range(daily_ohlcv, position)
    if not _is_tail_sized(bar_range, baseline_range, range_multiplier):
        return None

    high = float(daily_ohlcv["high"].iloc[position])
    low = float(daily_ohlcv["low"].iloc[position])
    window_high_max = float(window["high"].max())
    window_low_min = float(window["low"].min())

    makes_new_high = high > window_high_max
    makes_new_low = low < window_low_min
    if not makes_new_high and not makes_new_low:
        return None
    # A bar could in principle satisfy both (a huge "outside bar", beyond the lookback
    # window's high AND low at once) -- "up" takes priority in that degenerate tie, since a
    # genuine Kangaroo Tail's body-position check below only ever passes for one direction in
    # practice (the body can't retrace toward both ends of the range at once unless
    # min_retracement is exactly 0.5 and the body sits exactly on the midpoint). Recorded as
    # its own decision in docs/tasks/backend-kangaroo-tail-pattern-followups.json (not this
    # module's originating task, backend-kangaroo-tail-pattern.json, whose own `decisions`
    # array does not actually cover this specific tie-break) -- see that followups task's
    # `decisions` entry and its dedicated outside-bar regression test
    # (test_kangaroo_tail.py::TestGatingConditions::
    # test_outside_bar_new_high_and_new_low_defaults_to_up_direction).
    direction: Direction = "up" if makes_new_high else "down"

    open_ = float(daily_ohlcv["open"].iloc[position])
    close = float(daily_ohlcv["close"].iloc[position])
    if not _body_retraced_from_tip(direction, open_, close, high, low, bar_range, min_retracement):
        return None

    before_range = _bar_range(daily_ohlcv, position - 1)
    if _is_tail_sized(before_range, baseline_range, range_multiplier):
        return None  # the "before" flanking bar isn't of normal height

    # `detect_kangaroo_tails`' own loop bound (`range(lookback, n - 1)`) already guarantees
    # `position + 1` is always a valid index here -- no separate bounds guard needed.
    after_range = _bar_range(daily_ohlcv, position + 1)
    if _is_tail_sized(after_range, baseline_range, range_multiplier):
        return None  # the "after" flanking bar isn't of normal height

    confirming_close = float(daily_ohlcv["close"].iloc[position + 1])
    if not _confirms_direction(direction, close, confirming_close):
        return None

    return KangarooTail(
        direction=direction,
        date=daily_ohlcv.index[position],
        confirmed_date=daily_ohlcv.index[position + 1],
        high=high,
        low=low,
        range_multiple=bar_range / baseline_range,
        suggested_stop=(high + low) / 2,
    )


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
    tails = []
    # A candidate at `position` needs `lookback` bars before it and 1 bar after it.
    for position in range(lookback, n - 1):
        tail = _evaluate_candidate(
            daily_ohlcv,
            position,
            lookback=lookback,
            range_multiplier=range_multiplier,
            min_retracement=min_retracement,
        )
        if tail is not None:
            tails.append(tail)
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
