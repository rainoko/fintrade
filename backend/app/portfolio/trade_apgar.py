"""Elder ch. 58's "Trade Apgar" -- a pre-trade go/no-go score (docs/ideas.md's ch. 58 entry,
itself quoting ch. 58 directly), the pre-trade counterpart to ch. 55's after-the-fact "Is This
an A-Trade?" grading (`app.portfolio.grading`).

Elder is explicit that a Trade Apgar's five questions are strategy-specific ("the scoring
method you're about to see is designed for one system... All other systems will require a
different test"), so this module implements a single **fixed** 5-question set matching only
Elder's own worked example strategy -- not a per-strategy-configurable question builder. See
the `backend-trade-apgar` task's `decisions` entry for why a fixed set (a much smaller, still
useful first version) was chosen over a genuinely configurable one (the "real" long-term
shape, but out of scope here).

Elder's own example strategy's five questions, each scored 0/1/2 (docs/ideas.md):

1. Weekly Impulse -- Red=0, Green=1, Blue=2.
2. Daily Impulse -- same scale.
3. Daily price vs. value -- above value=0, in value zone=1, below value=2.
4. False breakout status -- none=0, already happened=1, on the verge=2.
5. "Perfection" -- neither timeframe looks ideal=0, one does=1, both do=2.

Go/no-go rule: total score >= 7 **and** no single question scored 0 (both conditions
required -- a trade scoring, say, 8 total with one 0 must still fail, per the book's own
explicit "no single 0" carve-out; docs/ideas.md's own restatement of ch. 58).

Three of the five questions are auto-populated from data `app.signals.engine.analyse()`
already computes for any ticker (weekly/daily Impulse color, and the daily price-vs-value
zone from EMA(13)/EMA(26) -- ch. 41's own "value zone", *not* the Autoenvelope/channel band
`channel_upper`/`channel_lower` expose, despite this task's own description text loosely
conflating the two -- see the `decisions` entry for the correction). False-breakout status and
"perfection" stay fully manual inputs for this first version -- see the `decisions` entry for
why no suggested starting value is derived from `kangaroo_tail`/`support_resistance` either,
even though the task's own checklist flagged that as an option.
"""

from dataclasses import dataclass
from typing import Literal

ImpulseColor = Literal["GREEN", "RED", "BLUE"]
PriceVsValue = Literal["above_value", "in_value_zone", "below_value"]
FalseBreakoutStatus = Literal["none", "already_happened", "on_the_verge"]
Perfection = Literal["neither", "one", "both"]

# Elder's own example strategy's per-question scoring tables (docs/ideas.md's ch. 58 entry).
# Both Impulse questions (weekly and daily) share the identical Red=0/Green=1/Blue=2 scale --
# unusual at a glance (Green scoring lower than Blue), but this is *this specific example
# strategy's* own scoring choice, not a general "Green is best" rule -- see this module's
# docstring and the `decisions` entry for why it's implemented literally rather than
# "corrected" to some assumed more intuitive ordering.
_IMPULSE_SCORES: dict[ImpulseColor, int] = {"RED": 0, "GREEN": 1, "BLUE": 2}
_PRICE_VS_VALUE_SCORES: dict[PriceVsValue, int] = {
    "above_value": 0,
    "in_value_zone": 1,
    "below_value": 2,
}
_FALSE_BREAKOUT_SCORES: dict[FalseBreakoutStatus, int] = {
    "none": 0,
    "already_happened": 1,
    "on_the_verge": 2,
}
_PERFECTION_SCORES: dict[Perfection, int] = {"neither": 0, "one": 1, "both": 2}

# Elder's own explicit go/no-go threshold (docs/ideas.md's ch. 58 entry): "≥7 total with no
# single zero" -- both conditions are required together, not just the sum.
_GO_MINIMUM_TOTAL_SCORE = 7


def score_impulse(color: ImpulseColor) -> int:
    """Red=0, Green=1, Blue=2 -- shared scale for both the weekly-Impulse and daily-Impulse
    questions (docs/ideas.md's ch. 58 entry: "same scale")."""
    return _IMPULSE_SCORES[color]


def price_vs_value_zone(close: float, ema_13: float, ema_26: float) -> PriceVsValue:
    """Classifies `close` against ch. 41's "value zone" -- the band between EMA(13) and
    EMA(26) (whichever is the upper/lower bound at any moment depends on trend direction; an
    uptrend has EMA(13) > EMA(26), a downtrend the reverse, so this takes `min`/`max` of the
    two rather than assuming a fixed ordering).

    Deliberately the *value zone* (EMA13/EMA26 band, `docs/architecture/Frontend.md` §5's
    "value zone" shading), not the Autoenvelope/channel band `channel_upper`/`channel_lower`
    expose (`docs/Analyse.md` §4 row 6 -- EMA(13) ± average % deviation) -- the two are
    visually drawn on the same chart but are distinct indicators; see this module's own
    docstring and the `decisions` entry for why `channel_upper`/`channel_lower` are not used
    here despite the task description's own looser phrasing."""
    lower = min(ema_13, ema_26)
    upper = max(ema_13, ema_26)
    if close > upper:
        return "above_value"
    if close < lower:
        return "below_value"
    return "in_value_zone"


def score_price_vs_value(status: PriceVsValue) -> int:
    """Above value=0, in value zone=1, below value=2 (docs/ideas.md's ch. 58 entry) -- this
    example strategy buys weakness (a pullback into or below value), so a cheaper price scores
    higher, not lower."""
    return _PRICE_VS_VALUE_SCORES[status]


def score_false_breakout(status: FalseBreakoutStatus) -> int:
    """None=0, already happened=1, on the verge=2 (docs/ideas.md's ch. 58 entry). Manual input
    for this first version -- see this module's own docstring."""
    return _FALSE_BREAKOUT_SCORES[status]


def score_perfection(status: Perfection) -> int:
    """Neither timeframe looks ideal=0, one does=1, both do=2 (docs/ideas.md's ch. 58 entry,
    including Elder's own note that both being perfect is rare -- one perfect plus one merely
    good is fine). Manual input for this first version -- see this module's own docstring."""
    return _PERFECTION_SCORES[status]


@dataclass(frozen=True)
class TradeApgarQuestion:
    """One scored question on the Trade Apgar, in the fixed order docs/ideas.md's ch. 58
    entry lists them (weekly Impulse, daily Impulse, price vs. value, false breakout,
    perfection)."""

    key: Literal["weekly_impulse", "daily_impulse", "price_vs_value", "false_breakout", "perfection"]
    label: str
    value: str
    score: int
    source: Literal["auto", "manual"]


@dataclass(frozen=True)
class TradeApgarResult:
    """The full scored Trade Apgar: every question plus the combined go/no-go verdict."""

    questions: list[TradeApgarQuestion]
    total_score: int
    go: bool


def score_trade_apgar(
    *,
    weekly_impulse: ImpulseColor,
    daily_impulse: ImpulseColor,
    price_vs_value: PriceVsValue,
    false_breakout_status: FalseBreakoutStatus,
    perfection: Perfection,
) -> TradeApgarResult:
    """Scores all five questions and applies the go/no-go rule.

    `weekly_impulse`/`daily_impulse`/`price_vs_value` are auto-populated by the caller from
    `app.signals.engine.analyse()`'s own output for the ticker being evaluated (see this
    module's own docstring); `false_breakout_status`/`perfection` are the caller's own manual
    inputs. This function itself is pure -- it has no opinion on where its inputs came from,
    only how they're scored.

    `go` is true only when **both** of Elder's own conditions hold (docs/ideas.md's ch. 58
    entry): the summed score is >= 7, **and** no single question scored 0. Checking only the
    sum would let a trade with one badly-failing question (e.g. an active false breakdown, or
    a daily Impulse flatly contradicting the setup) still pass on the strength of the other
    four -- exactly the case Elder's own "no single zero" carve-out exists to block."""
    questions = [
        TradeApgarQuestion(
            key="weekly_impulse",
            label="Weekly Impulse",
            value=weekly_impulse,
            score=score_impulse(weekly_impulse),
            source="auto",
        ),
        TradeApgarQuestion(
            key="daily_impulse",
            label="Daily Impulse",
            value=daily_impulse,
            score=score_impulse(daily_impulse),
            source="auto",
        ),
        TradeApgarQuestion(
            key="price_vs_value",
            label="Daily price vs. value",
            value=price_vs_value,
            score=score_price_vs_value(price_vs_value),
            source="auto",
        ),
        TradeApgarQuestion(
            key="false_breakout",
            label="False breakout status",
            value=false_breakout_status,
            score=score_false_breakout(false_breakout_status),
            source="manual",
        ),
        TradeApgarQuestion(
            key="perfection",
            label="\"Perfection\" (both timeframes look ideal)",
            value=perfection,
            score=score_perfection(perfection),
            source="manual",
        ),
    ]
    total_score = sum(q.score for q in questions)
    go = total_score >= _GO_MINIMUM_TOTAL_SCORE and all(q.score > 0 for q in questions)
    return TradeApgarResult(questions=questions, total_score=total_score, go=go)
