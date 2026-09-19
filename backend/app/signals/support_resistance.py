"""Horizontal support/resistance zone detection, strength scoring, and false-breakout
flagging (Elder ch. 18, "Support and Resistance" -- see docs/ideas.md's "Missing entirely:
horizontal support/resistance" entry, and this task's `decisions` entry on
docs/tasks/backend-support-resistance.json for every judgment call below).

The book describes the *concept* precisely (a horizontal congestion zone, not a single
price; strength from length/height/volume; zones flip role once broken; a false breakout --
price closes beyond the zone then closes back inside it -- is a specific, high-value reversal
signal with its own stop-placement rule) but gives no mechanical algorithm for turning a raw
daily OHLCV series into zones. Every parameter below (fractal window, cluster tolerance,
minimum touches, category thresholds, false-breakout confirmation window, the zone cap) is
this task's own judgment call, recorded in full on the task's `decisions` array -- not
something Analyse.md or the book pins down.

Scope, per this task's own description: detection + strength scoring + false-breakout
flagging + API exposure only. Zones are NOT wired into Screen 1/2/3, the Impulse gate,
confidence scoring, or `app.portfolio.risk.protective_stop` -- using a known zone to tighten
the stop-loss formula is an explicitly out-of-scope follow-up (see this task's `decisions`).
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

Role = Literal["support", "resistance"]
StrengthCategory = Literal["minor", "intermediate", "major"]
BreakoutDirection = Literal["up", "down"]

# --- detection parameters (see this task's `decisions` entry for the rationale behind each) ---

# Bars on each side of a candidate swing point a fractal window compares against -- 2 gives a
# 5-bar window (today plus 2 before/2 after), a common, simple swing-point definition that
# doesn't require a whole separate swing-point-detector module (backend-swing-point-detector
# is a distinct, not-yet-built task whose eventual detector this module intentionally doesn't
# depend on, to keep this task's own dependencies at zero -- see this task's `decisions`).
_FRACTAL_WINDOW = 2

# A swing point's CLOSE (not its high/low wick) is what gets clustered -- "the edges of where
# price repeatedly stalled, not the extreme wick" per this task's own description. Two swing
# closes merge into the same zone/cluster when within this fraction of the cluster's running
# mean price.
_CLUSTER_TOLERANCE_PCT = 0.01

# Minimum swing points required to call a price cluster a "zone" at all -- a single touch is
# just a spike, not "repeated stalling".
_MIN_TOUCHES = 2

# Elder's own length thresholds (docs/ideas.md: "length (2 weeks = minor, 2 months =
# intermediate, 2 years = major)"). Below 2 weeks, a cluster isn't reported as a zone at all
# (not even "minor") -- 2 weeks is the book's own floor for the weakest recognized category.
_MIN_ZONE_LENGTH_DAYS = 14
_INTERMEDIATE_LENGTH_DAYS = 60
_MAJOR_LENGTH_DAYS = 730

# Elder gives three anchor points for height-as-%-of-price (~1% minor, ~3% intermediate,
# >=7% major), not category boundaries -- the boundaries used here are the midpoints between
# consecutive anchors (2% between 1 and 3, 5% between 3 and 7), so each anchor value itself
# still classifies as the book intends (1% -> minor, 3% -> intermediate, 7% -> major).
_INTERMEDIATE_HEIGHT_PCT = 2.0
_MAJOR_HEIGHT_PCT = 5.0

# Trading days a breakout beyond a zone is given to prove itself false (a close back inside
# the zone) before being treated as a confirmed, role-flipping break.
_FALSE_BREAKOUT_WINDOW_DAYS = 10

# Caps the number of zones a caller has to render/reason about on a long history (a multi-year
# daily series can produce hundreds of raw swing-point clusters) -- kept by strength_score
# (then touch_count, then recency) descending, so the strongest/most-relevant zones survive
# the cap.
_MAX_ZONES_RETURNED = 15

_CATEGORY_SCORE: dict[StrengthCategory, float] = {
    "minor": 100 / 3,
    "intermediate": 200 / 3,
    "major": 100.0,
}


@dataclass(frozen=True)
class FalseBreakout:
    """A single false-breakout episode: price closed beyond the zone, then closed back
    inside it within the confirmation window (Elder ch. 18's high-value reversal setup).

    ``extreme_price`` is the failed move's own extreme (the highest high reached during an
    'up' false breakout, the lowest low during a 'down' one) -- the book's explicit
    stop-placement reference: "near the false breakout's own extreme", not further out.
    """

    direction: BreakoutDirection
    breakout_date: pd.Timestamp
    reentry_date: pd.Timestamp
    extreme_price: float


@dataclass
class Zone:
    """One horizontal support/resistance zone, plus its strength score and current
    break/false-breakout state.

    ``role`` is the zone's CURRENT role -- it starts as whichever side (support/resistance)
    its swing points were clustered from, and flips (support <-> resistance) the first time
    ``broken`` becomes True, per Elder's "a broken zone keeps existing with an inverted role"
    rule. A zone that has only ever produced false breakouts (or none at all) keeps its
    original role.
    """

    role: Role
    upper: float
    lower: float
    first_touch_date: pd.Timestamp
    last_touch_date: pd.Timestamp
    touch_count: int
    length_days: int
    length_category: StrengthCategory
    height_pct: float
    height_category: StrengthCategory
    dollar_volume: float
    strength_score: float
    broken: bool = False
    break_date: pd.Timestamp | None = None
    false_breakout: FalseBreakout | None = None


def _validate_columns(daily_ohlcv: pd.DataFrame) -> None:
    required = {"high", "low", "close", "volume"}
    missing = required - set(daily_ohlcv.columns)
    if missing:
        raise ValueError(f"daily_ohlcv is missing required column(s): {sorted(missing)}")


def _find_swing_points(
    daily_ohlcv: pd.DataFrame, window: int
) -> tuple[list[tuple[pd.Timestamp, float]], list[tuple[pd.Timestamp, float]]]:
    """Fractal-style swing highs/lows: bar ``i`` is a swing high if its ``high`` equals the
    max of the ``2*window + 1``-bar window centered on it (mirrored for swing lows via
    ``low``/min). Each returned point is ``(date, close_at_that_bar)`` -- the close, not the
    high/low itself, is what feeds clustering (see this module's docstring).

    The first/last ``window`` bars can never be a swing point (no full window to compare
    against) -- an intentional, bounded edge exclusion, not a bug: a "swing" inherently needs
    bars on both sides to confirm a local turn.
    """
    highs = daily_ohlcv["high"]
    lows = daily_ohlcv["low"]
    closes = daily_ohlcv["close"]
    n = len(daily_ohlcv)

    swing_highs: list[tuple[pd.Timestamp, float]] = []
    swing_lows: list[tuple[pd.Timestamp, float]] = []
    for i in range(window, n - window):
        high_window = highs.iloc[i - window : i + window + 1]
        low_window = lows.iloc[i - window : i + window + 1]
        if highs.iloc[i] == high_window.max():
            swing_highs.append((daily_ohlcv.index[i], float(closes.iloc[i])))
        if lows.iloc[i] == low_window.min():
            swing_lows.append((daily_ohlcv.index[i], float(closes.iloc[i])))
    return swing_highs, swing_lows


def _cluster_touches(
    touches: list[tuple[pd.Timestamp, float]],
    *,
    tolerance_pct: float,
    min_touches: int,
    min_length_days: int,
) -> list[dict]:
    """Sequential 1-D clustering of swing-point ``(date, price)`` touches into candidate
    zones: sort by price, then merge each point into the running cluster if it's within
    ``tolerance_pct`` of that cluster's current mean price, else start a new cluster.

    A cluster only becomes a candidate zone if it has at least ``min_touches`` points AND
    those touches span at least ``min_length_days`` (both are real filters -- a cluster
    failing either is dropped, not degraded). Returns dicts with ``upper``/``lower`` (the
    cluster's own price extremes -- since touches are already close prices, not wicks, this
    naturally satisfies "the edges of where price stalled, not the extreme wick"),
    ``first_touch_date``/``last_touch_date``, and ``touch_count``.
    """
    if not touches:
        return []

    ordered = sorted(touches, key=lambda t: t[1])
    clusters: list[list[tuple[pd.Timestamp, float]]] = []
    current = [ordered[0]]
    for point in ordered[1:]:
        cluster_mean = sum(p for _, p in current) / len(current)
        if cluster_mean != 0 and abs(point[1] - cluster_mean) <= tolerance_pct * cluster_mean:
            current.append(point)
        else:
            clusters.append(current)
            current = [point]
    clusters.append(current)

    candidates = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        dates = [d for d, _ in cluster]
        prices = [p for _, p in cluster]
        first_touch_date = min(dates)
        last_touch_date = max(dates)
        length_days = (last_touch_date - first_touch_date).days
        if length_days < min_length_days:
            continue
        candidates.append(
            {
                "upper": max(prices),
                "lower": min(prices),
                "first_touch_date": first_touch_date,
                "last_touch_date": last_touch_date,
                "touch_count": len(cluster),
            }
        )
    return candidates


def _length_category(length_days: int) -> StrengthCategory:
    if length_days >= _MAJOR_LENGTH_DAYS:
        return "major"
    if length_days >= _INTERMEDIATE_LENGTH_DAYS:
        return "intermediate"
    return "minor"


def _height_category(height_pct: float) -> StrengthCategory:
    if height_pct >= _MAJOR_HEIGHT_PCT:
        return "major"
    if height_pct >= _INTERMEDIATE_HEIGHT_PCT:
        return "intermediate"
    return "minor"


def _strength_score(length_category: StrengthCategory, height_category: StrengthCategory) -> float:
    """0-100 composite of length + height categories only (not dollar_volume -- Elder gives
    an explicit formula for the dollar figure but no absolute thresholds to classify it
    against, so it's exposed raw on `Zone.dollar_volume` instead of folded in here numerically
    -- see this task's `decisions` entry)."""
    return (_CATEGORY_SCORE[length_category] + _CATEGORY_SCORE[height_category]) / 2


def _dollar_volume(daily_ohlcv: pd.DataFrame, first_touch_date: pd.Timestamp, last_touch_date: pd.Timestamp) -> float:
    """Elder's own explicit formula (docs/ideas.md): days-in-zone x average daily volume x
    average price, over the zone's own touch span (``first_touch_date``..``last_touch_date``
    inclusive). "Days-in-zone" is read as trading days actually present in that span, not
    calendar days (``length_days``), since volume/price only exist on trading days."""
    window = daily_ohlcv.loc[first_touch_date:last_touch_date]
    if window.empty:
        return 0.0
    trading_days = len(window)
    avg_volume = float(window["volume"].mean())
    avg_price = float(window["close"].mean())
    return trading_days * avg_volume * avg_price


def _opposite_role(role: Role) -> Role:
    return "support" if role == "resistance" else "resistance"


def _scan_breaks_and_false_breakouts(
    candidate: dict, role: Role, daily_ohlcv: pd.DataFrame, window_days: int
) -> dict:
    """Walks the daily bars strictly after ``candidate["last_touch_date"]`` looking for a
    close beyond the zone's ``[lower, upper]`` band (a "breakout" bar, in whichever direction
    ``role`` makes a break: above ``upper`` for a resistance zone, below ``lower`` for a
    support zone).

    On a breakout bar, looks ahead up to ``window_days`` further trading days for a close
    back inside ``[lower, upper]``:

    - **Reentry found within the window (a false breakout)**: records the episode (most
      recent one wins if there are several before an eventual real break -- see this task's
      `decisions` entry for why coexistence with a later ``broken=True`` is allowed rather
      than mutually exclusive) and keeps scanning from the reentry bar onward, with the
      zone's role unchanged -- a false breakout does NOT flip the zone (Elder: the zone held,
      the breakout failed).
    - **No reentry within the window (a confirmed/true break)**: marks the zone broken as of
      the breakout date and flips its role. Scanning stops at the first confirmed break --
      this function tracks at most one role flip per zone (see this task's `decisions` entry
      for why re-flipping after that isn't attempted here).
    - A breakout with fewer than ``window_days`` bars remaining in ``daily_ohlcv`` (i.e. it
      happens near the very end of the available history) is still resolved with whatever
      partial lookahead exists -- no reentry in that partial window still confirms a break,
      since there's no future data to wait for a fuller window (see this task's `decisions`
      entry on this point-in-time limitation).

    Returns ``{"role": Role, "broken": bool, "break_date": Timestamp | None,
    "false_breakout": FalseBreakout | None}``.
    """
    upper, lower = candidate["upper"], candidate["lower"]
    subsequent = daily_ohlcv[daily_ohlcv.index > candidate["last_touch_date"]]
    closes = subsequent["close"]
    result: dict = {"role": role, "broken": False, "break_date": None, "false_breakout": None}

    n = len(subsequent)
    i = 0
    while i < n:
        close = closes.iloc[i]
        breached = (result["role"] == "resistance" and close > upper) or (
            result["role"] == "support" and close < lower
        )
        if not breached:
            i += 1
            continue

        breakout_idx = i
        breakout_date = subsequent.index[i]
        lookahead = subsequent.iloc[i + 1 : i + 1 + window_days]
        reentry = lookahead[(lookahead["close"] <= upper) & (lookahead["close"] >= lower)]

        if not reentry.empty:
            reentry_date = reentry.index[0]
            reentry_pos = subsequent.index.get_loc(reentry_date)
            if result["role"] == "resistance":
                extreme = float(subsequent["high"].iloc[breakout_idx : reentry_pos + 1].max())
                direction: BreakoutDirection = "up"
            else:
                extreme = float(subsequent["low"].iloc[breakout_idx : reentry_pos + 1].min())
                direction = "down"
            result["false_breakout"] = FalseBreakout(
                direction=direction,
                breakout_date=breakout_date,
                reentry_date=reentry_date,
                extreme_price=extreme,
            )
            i = reentry_pos + 1
            continue

        result["broken"] = True
        result["break_date"] = breakout_date
        result["role"] = _opposite_role(result["role"])
        break

    return result


def _build_zone(
    candidate: dict, role: Role, daily_ohlcv: pd.DataFrame, reference_price: float, window_days: int
) -> Zone:
    upper, lower = candidate["upper"], candidate["lower"]
    height_pct = 0.0 if reference_price == 0 else abs(upper - lower) / reference_price * 100
    length_days = (candidate["last_touch_date"] - candidate["first_touch_date"]).days
    length_category = _length_category(length_days)
    height_category = _height_category(height_pct)

    break_info = _scan_breaks_and_false_breakouts(candidate, role, daily_ohlcv, window_days)

    return Zone(
        role=break_info["role"],
        upper=upper,
        lower=lower,
        first_touch_date=candidate["first_touch_date"],
        last_touch_date=candidate["last_touch_date"],
        touch_count=candidate["touch_count"],
        length_days=length_days,
        length_category=length_category,
        height_pct=height_pct,
        height_category=height_category,
        dollar_volume=_dollar_volume(daily_ohlcv, candidate["first_touch_date"], candidate["last_touch_date"]),
        strength_score=_strength_score(length_category, height_category),
        broken=break_info["broken"],
        break_date=break_info["break_date"],
        false_breakout=break_info["false_breakout"],
    )


def detect_support_resistance_zones(
    daily_ohlcv: pd.DataFrame,
    *,
    fractal_window: int = _FRACTAL_WINDOW,
    cluster_tolerance_pct: float = _CLUSTER_TOLERANCE_PCT,
    min_touches: int = _MIN_TOUCHES,
    min_zone_length_days: int = _MIN_ZONE_LENGTH_DAYS,
    false_breakout_window_days: int = _FALSE_BREAKOUT_WINDOW_DAYS,
    max_zones: int = _MAX_ZONES_RETURNED,
) -> list[Zone]:
    """Detects horizontal support/resistance zones over the full ``daily_ohlcv`` history,
    scores each zone's strength (length/height/dollar-volume), and flags any current or past
    false-breakout episode -- Elder ch. 18, see this module's docstring for the full
    algorithm/scope notes.

    Pipeline: find fractal swing highs/lows -> cluster each side's swing-point closes into
    candidate zones (>= ``min_touches`` touches spanning >= ``min_zone_length_days``) ->
    score each candidate's length/height/dollar-volume -> scan forward from each zone's last
    touch for a confirmed break (flips role) or false breakout (does not). ``height_pct`` is
    computed against ``daily_ohlcv``'s own latest close (today's price), per this task's own
    description ("height as % of current price") -- the same reference for every zone on this
    call, not each zone's own (potentially long-past) touch-era price.

    Expects ``daily_ohlcv`` already cleaned of malformed bars (matching every other function
    in ``app.signals`` -- see ``app.signals.engine.drop_malformed_daily_bars``); this function
    does not clean it itself.

    Returns at most ``max_zones`` zones, ordered by ``strength_score`` descending (ties broken
    by ``touch_count`` then ``last_touch_date``, both descending) -- see
    ``_MAX_ZONES_RETURNED``'s module-level comment for why a cap exists at all. Returns an
    empty list for an empty ``daily_ohlcv``, or one with fewer bars than
    ``2 * fractal_window + 1`` (too short for any swing point to exist).

    Raises:
        ValueError: if ``daily_ohlcv`` is non-empty but missing a required column
            (``high``/``low``/``close``/``volume``).
    """
    if daily_ohlcv.empty:
        return []
    _validate_columns(daily_ohlcv)

    reference_price = float(daily_ohlcv["close"].iloc[-1])

    swing_highs, swing_lows = _find_swing_points(daily_ohlcv, fractal_window)
    resistance_candidates = _cluster_touches(
        swing_highs,
        tolerance_pct=cluster_tolerance_pct,
        min_touches=min_touches,
        min_length_days=min_zone_length_days,
    )
    support_candidates = _cluster_touches(
        swing_lows,
        tolerance_pct=cluster_tolerance_pct,
        min_touches=min_touches,
        min_length_days=min_zone_length_days,
    )

    zones = [
        _build_zone(candidate, "resistance", daily_ohlcv, reference_price, false_breakout_window_days)
        for candidate in resistance_candidates
    ] + [
        _build_zone(candidate, "support", daily_ohlcv, reference_price, false_breakout_window_days)
        for candidate in support_candidates
    ]

    zones.sort(key=lambda z: (z.strength_score, z.touch_count, z.last_touch_date), reverse=True)
    return zones[:max_zones]
