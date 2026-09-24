"""Generic long-term/intermediate/short-term timeframe model (Elder ch. 39, "Choosing
Timeframes -- the Factor of Five", pp. 155-162; docs/ideas.md's "Switchable trading mode"
entry; docs/tasks/backend-day-trader-timeframe-mode.json).

Triple Screen doesn't hard-code weekly/daily/intraday -- it's built around *whatever three
timeframes the trader picks*, each related to its neighbor by roughly a factor of five. This
module is the foundational domain model for that generic triple (checklist item 2 of the task
above); it deliberately does **not** touch `app.signals.engine`/`app.signals.triple_screen`
(Screen 1/2/3 still hard-code weekly/daily today) or any API schema/cache-table field name --
those are explicitly out of scope for this task and tracked as dependent follow-up tasks (see
`docs/tasks/backend-day-trader-timeframe-mode.json`'s `decisions` entry for the full scope-split
rationale). This module is consumed today only by `app.trading_mode` (the global settings
persistence layer, checklist item 3) -- nothing downstream reads a `TimeframeTriple` yet.

Swing/position-trader mode (this app's only mode until day-trader mode's own signal-engine
wiring lands) keeps using the existing hard-coded weekly (Tide) / daily (Wave) / daily-as-
Trigger-approximation (Screen 3, docs/Analyse.md's own documented "no intraday feed" caveat)
scheme unchanged -- `DEFAULT_SWING_TRIPLE` below exists only as this scheme's equivalent
representation in the new generic model, for documentation/parity purposes; nothing in
`app.signals.engine` reads it (yet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# A US regular trading session is ~6.5 hours = 390 minutes (docs/ideas.md's own "39 minutes
# divides the 390-minute US trading day into a clean 10 bars" note on ch. 39's day-trading
# example) -- used here as the conversion factor for comparing a "day" or "week" leg of a
# triple against a "minute" leg on one common scale (trading time, not calendar time), which
# is the only scale ch. 39's factor-of-five guideline actually makes sense on: a calendar week
# is 10080 minutes, but only ~1950 of those are trading minutes, and it's the trading-time
# ratio Elder's own weekly/daily (5x) and 25-min/5-min (5x) examples both work out to exactly.
TRADING_MINUTES_PER_DAY = 390
TRADING_DAYS_PER_WEEK = 5


class TimeframeUnit(StrEnum):
    """The three interval units this app's generic timeframe model supports.

    Deliberately not a plain "arbitrary minute count" model (the other option considered --
    see this task's `decisions` entry): a calendar-week bar is formed by resampling daily bars
    into Saturday-through-Friday bins anchored on Friday (`app.data.stooq_provider
    .StooqProvider._resample_weekly`, `app.signals.engine._weekly_through_bar_date`), which is
    qualitatively different from "10080 minutes" -- collapsing WEEK into a minute count would
    lose that calendar-anchoring semantic a future generic Tide/Screen-1 implementation still
    needs. DAY is kept distinct from WEEK for the same reason (a daily bar is one trading
    session, not literally "390 minutes" for every comparison -- see `approx_trading_minutes`
    below for where the minute-conversion is actually used, and where it's explicitly only an
    approximation).
    """

    MINUTE = "minute"
    DAY = "day"
    WEEK = "week"


_UNIT_CODE_SUFFIX: dict[TimeframeUnit, str] = {
    TimeframeUnit.MINUTE: "m",
    TimeframeUnit.DAY: "d",
    TimeframeUnit.WEEK: "w",
}
_CODE_SUFFIX_UNIT: dict[str, TimeframeUnit] = {v: k for k, v in _UNIT_CODE_SUFFIX.items()}

_CODE_PATTERN = re.compile(r"^([1-9][0-9]*)([mdw])$")


@dataclass(frozen=True)
class TimeframeInterval:
    """One leg of a `TimeframeTriple`: a count of a unit (e.g. "25 minutes", "1 week").

    `code` is the canonical, round-trippable string encoding (`"25m"`, `"1w"`, `"1d"`) used at
    the API/persistence boundary (`app.trading_mode`, `app/api/schemas.py`) instead of a
    structured object -- a single short string is simpler to persist as one SQLite column and
    to validate/display than a nested unit+count pair, and matches this codebase's existing
    "closed string-enum-like column, Python-layer validation" convention
    (`OHLCVCacheORM.interval`, `ClosedTradeORM.exit_reason` -- see docs/architecture/Backend.md
    §7's `db/models.py` docstrings) rather than inventing a new persisted shape for this one
    field.
    """

    unit: TimeframeUnit
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"TimeframeInterval count must be >= 1, got {self.count}")

    @property
    def code(self) -> str:
        return f"{self.count}{_UNIT_CODE_SUFFIX[self.unit]}"

    @classmethod
    def parse(cls, code: str) -> TimeframeInterval:
        """Parses a canonical interval code (`"25m"` / `"1d"` / `"1w"`) into a
        `TimeframeInterval`. Raises `ValueError` (not a silent `None`/default) on anything
        that doesn't match `count` (a positive integer, no leading zero) immediately followed
        by exactly one of `m`/`d`/`w` -- this is user-supplied configuration (the day-trader
        timeframe triple, checklist item 3), so a malformed value should fail loudly rather
        than silently coerce to something the caller didn't ask for."""
        match = _CODE_PATTERN.match(code.strip())
        if match is None:
            raise ValueError(
                f"Invalid timeframe interval code {code!r}; expected e.g. '25m', '1d', '1w' "
                "(a positive integer immediately followed by one of m/d/w)."
            )
        count_str, suffix = match.groups()
        return cls(unit=_CODE_SUFFIX_UNIT[suffix], count=int(count_str))

    @property
    def approx_trading_minutes(self) -> float:
        """This interval's length in trading minutes, on a common scale across units, for
        `TimeframeTriple`'s factor-of-five comparison below -- e.g. `TimeframeInterval(WEEK,
        1).approx_trading_minutes == 1950` (5 trading days x 390 minutes), matching
        `TimeframeInterval(DAY, 5).approx_trading_minutes` exactly, as it should (a trading
        week and 5 trading days are the same span). An *approximation*, not exact real-world
        clock time (holidays/half-days aren't modeled, and DAY/WEEK both assume a full regular
        session) -- adequate for this guideline-strength comparison, not claimed to be a
        precise calendar computation."""
        if self.unit is TimeframeUnit.MINUTE:
            return float(self.count)
        if self.unit is TimeframeUnit.DAY:
            return float(self.count * TRADING_MINUTES_PER_DAY)
        return float(self.count * TRADING_DAYS_PER_WEEK * TRADING_MINUTES_PER_DAY)


# Ch. 39 itself frames "roughly a factor of five" as a guideline, not a hard rule ("the ratio
# doesn't have to be exactly five" is the book's own framing) -- so `TimeframeTriple
# .factor_of_five_warnings` below returns human-readable warning strings for a ratio outside
# this band rather than this module raising/rejecting construction outright. The band itself
# (2x-10x) is this task's own judgment call, not a number from the book: wide enough to admit
# every one of ch. 39's own worked examples -- weekly/daily is exactly 5x, the 39-min/8-min
# pairing is ~4.9x, and, notably, the book's own 25-min/5-min/2-min day-trading example is
# NOT a clean 5x on both legs (25/5 = 5x, but 5/2 = only 2.5x) -- while still catching a triple
# that's clearly not following the guideline at all (e.g. two legs only ~1.1x apart, which
# defeats Screen 2's whole "wait for a counter-trend move on a faster timeframe" premise) --
# see this task's `decisions` entry.
_FACTOR_OF_FIVE_MIN_RATIO = 2.0
_FACTOR_OF_FIVE_MAX_RATIO = 10.0


@dataclass(frozen=True)
class TimeframeTriple:
    """A long-term (Tide) / intermediate (Wave) / short-term (Trigger) triple of
    `TimeframeInterval`s -- the generic replacement for this app's current hard-coded
    weekly/daily/intraday assumption (see this module's own docstring for what's actually
    wired up to read one today: nothing yet, this is the foundational model only).

    Construction enforces one **hard** rule -- `long_term` must be strictly longer than
    `intermediate`, which must be strictly longer than `short_term` (by `approx_trading_minutes`)
    -- since an inverted or degenerate ordering isn't "an unconventional but valid trader
    choice" the way an off-guideline ratio is; it breaks the Triple Screen premise outright (a
    "long-term" trend filter that's shorter than its own entry-trigger timeframe is simply
    mislabeled). This raises `ValueError` rather than degrading. The **factor-of-five spacing
    guideline** itself is deliberately not enforced here at all (see
    `factor_of_five_warnings` below) -- see this task's `decisions` entry for why these two
    get different strictness treatment.
    """

    long_term: TimeframeInterval
    intermediate: TimeframeInterval
    short_term: TimeframeInterval

    def __post_init__(self) -> None:
        long_minutes = self.long_term.approx_trading_minutes
        intermediate_minutes = self.intermediate.approx_trading_minutes
        short_minutes = self.short_term.approx_trading_minutes
        if not (long_minutes > intermediate_minutes > short_minutes):
            raise ValueError(
                "TimeframeTriple requires long_term > intermediate > short_term "
                f"(got long_term={self.long_term.code} ({long_minutes:g} min), "
                f"intermediate={self.intermediate.code} ({intermediate_minutes:g} min), "
                f"short_term={self.short_term.code} ({short_minutes:g} min))."
            )

    def factor_of_five_warnings(self) -> list[str]:
        """Non-blocking warnings (empty list = fully within the guideline band) for either
        adjacent pair's ratio falling outside `[_FACTOR_OF_FIVE_MIN_RATIO,
        _FACTOR_OF_FIVE_MAX_RATIO]`. Returned to a caller (the settings API, checklist item 3)
        to surface as an informational notice -- this never blocks saving the triple; see this
        module's own top-level comment on the chosen band and this task's `decisions` entry."""
        warnings: list[str] = []
        pairs = [
            ("long_term", self.long_term, "intermediate", self.intermediate),
            ("intermediate", self.intermediate, "short_term", self.short_term),
        ]
        for larger_name, larger, smaller_name, smaller in pairs:
            ratio = larger.approx_trading_minutes / smaller.approx_trading_minutes
            if ratio < _FACTOR_OF_FIVE_MIN_RATIO or ratio > _FACTOR_OF_FIVE_MAX_RATIO:
                warnings.append(
                    f"{larger_name} ({larger.code}) is {ratio:.1f}x {smaller_name} "
                    f"({smaller.code}) -- ch. 39's 'factor of five' guideline suggests each "
                    "timeframe be roughly 3-8x its neighbor."
                )
        return warnings


class TradingMode(StrEnum):
    """The global app-wide trading mode (docs/tasks/backend-day-trader-timeframe-mode.json's
    `decisions` entry: a single global setting, not a per-request parameter).

    `SWING` (the default, and this app's only mode until day-trader mode's own signal-engine/
    data-fetching wiring lands in a follow-up task) keeps every existing weekly/daily behavior
    exactly as-is. `DAY_TRADER` activates the user-configured `TimeframeTriple` persisted
    alongside this mode (`app.trading_mode.TradingModeSetting`) -- but, as of this task, that
    configured triple isn't read by anything yet; see this module's own docstring.
    """

    SWING = "swing"
    DAY_TRADER = "day_trader"


# The swing/position-trader triple this app has hard-coded since before this generic model
# existed -- Tide=weekly, Wave=daily, Trigger=daily (docs/Analyse.md's own documented
# approximation: "For a daily-bar app (no intraday feed required), approximate with: today's
# close crosses back above yesterday's high" -- there is no literal third, faster timeframe
# today). Constructing this via `TimeframeTriple` would raise (`intermediate` and `short_term`
# are the identical `1d` interval, violating the strict `long_term > intermediate >
# short_term` ordering above) -- correctly so, since this triple is not a valid generic
# instance of the model, only its closest existing-behavior analogue. Represented here as a
# plain tuple of codes, not a `TimeframeTriple`, for exactly that reason -- see this task's
# `decisions` entry.
DEFAULT_SWING_TRIPLE_CODES: tuple[str, str, str] = ("1w", "1d", "1d")
