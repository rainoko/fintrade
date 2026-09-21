"""Elder ch. 57's "Am I ready to trade?" 5-question daily psychological readiness self-test
(docs/ideas.md's ch. 57 entry) -- purely subjective, zero market data, zero provider calls.
Each of the five questions is scored 0/1/2 by the trader; this module is the pure-computation
half (color-banding the summed score, and suggesting -- never dictating -- one of those five
scores from data this app already has) that `app.api.routers.homework` calls.

Scoped to just this self-test, not ch. 57's broader 17-line market-context homework
spreadsheet (see the backend-daily-homework-self-test task's own description for why that's a
separate, larger idea).
"""

from typing import Literal

HomeworkBand = Literal["red", "yellow", "green"]


def band_for_total_score(total_score: int) -> HomeworkBand:
    """The book's own color-banding thresholds over the 0-10 summed score (docs/ideas.md's
    ch. 57 entry, itself quoting ch. 57 directly): <=4 red ("don't trade"), 5-6 yellow ("trade
    cautiously"), 7-8 green, 9-10 yellow again -- Elder's own explanation for that second
    yellow band is that "with everything so perfect, any change is bound to be for the worse".
    Pure function over the already-summed score; does not itself validate that `total_score`
    is actually in 0-10 (each of the five inputs it's summed from is already range-validated
    at the `DailyHomeworkIn` schema layer, so an out-of-range total can't reach here via the
    API -- see this task's `decisions` entry)."""
    if total_score <= 4:
        return "red"
    if total_score <= 6:
        return "yellow"
    if total_score <= 8:
        return "green"
    return "yellow"


def suggested_yesterday_trading_score(net_realized_pnl: float | None) -> int | None:
    """A suggested (never auto-committed) score for "how did I trade yesterday?", derived from
    yesterday's `closed_trades` realized P&L -- see the backend-daily-homework-self-test
    task's `decisions` entry for why this is a suggestion a caller may use to pre-fill the
    form, not a value this module or the API ever writes on the user's behalf: Elder's own
    question is a subjective self-assessment ("how did I trade"), and a purely mechanical P&L
    read can't see e.g. a profitable trade taken by breaking the trading plan, or a small
    disciplined loss taken exactly on-stop -- both of which the trader may reasonably want to
    score differently than the raw dollar sign alone would suggest.

    `None` if `net_realized_pnl` is `None` (no `closed_trades` rows exited yesterday --
    nothing to base a suggestion on; the question stays fully manual for that day). Otherwise
    a net gain suggests 2 (traded well), exactly breakeven suggests 1 (neutral), and a net
    loss suggests 0 (traded poorly) -- the same 0/1/2 scale as every other question."""
    if net_realized_pnl is None:
        return None
    if net_realized_pnl > 0:
        return 2
    if net_realized_pnl == 0:
        return 1
    return 0
