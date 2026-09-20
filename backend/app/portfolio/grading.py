"""Post-trade "A-trade" grading, Elder ch. 55 ("Is This an A-Trade?") -- three exact,
checkable formulas for grading a *completed* trade (docs/Analyse.md §7 / docs/ideas.md's
ch. 55 cross-check), unlocked once a closed trade's entry/exit price+date exist
(`ClosedTradeORM`, `app/db/models.py`, from the `backend-trade-history-table` task) and that
day's OHLC + entry-day channel bounds (`app.indicators.autoenvelope.autoenvelope`, from the
`backend-channel-envelope-exposure` task) are available.

All three grades are preferred over grading a trade by raw dollars/percent-return alone,
since they account for how much was *realistically available to capture* that day/that
channel, not just what was actually captured.
"""

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.indicators.autoenvelope import autoenvelope
from app.signals.engine import drop_malformed_daily_bars


@dataclass(frozen=True)
class TradeGrade:
    """The three grade percentages for one closed trade. Each is `None` when its own
    formula's denominator is undefined (non-positive, or NaN/infinite from a value this
    trade's own data couldn't supply -- see `_ratio_pct`), never a fabricated 0.0 or an
    exception -- a trade that can't be graded is a real, unremarkable case (e.g. its ticker's
    fetched history doesn't reach back to entry_date, or entry_date falls inside the
    Autoenvelope's own ~100-bar warm-up window), not an error."""

    buy_grade_pct: float | None
    sell_grade_pct: float | None
    trade_grade_pct: float | None


def _ratio_pct(numerator: float, denominator: float) -> float | None:
    """`numerator / denominator * 100`, or `None` if the ratio is undefined: `denominator`
    is non-positive (a day with no trading range at all, or `channel_upper <= channel_lower`
    -- both degenerate but real inputs, not something to divide by zero on), or either input
    is NaN/infinite (e.g. a bar that didn't survive `drop_malformed_daily_bars`, or an
    Autoenvelope band still inside its own warm-up window -- see `autoenvelope`'s own
    docstring)."""
    if not (math.isfinite(numerator) and math.isfinite(denominator)) or denominator <= 0:
        return None
    return numerator / denominator * 100.0


def buy_grade_pct(buy_price: float, entry_day_high: float, entry_day_low: float) -> float | None:
    """`(day's high - buy price) / (day's high - day's low)` -- how close to the entry day's
    low the buy actually was. >50% is "very good" (docs/ideas.md ch. 55)."""
    return _ratio_pct(entry_day_high - buy_price, entry_day_high - entry_day_low)


def sell_grade_pct(sell_price: float, exit_day_high: float, exit_day_low: float) -> float | None:
    """`(sell price - day's low) / (day's high - day's low)` -- how close to the exit day's
    high the sell actually was. >50% is "very good"."""
    return _ratio_pct(sell_price - exit_day_low, exit_day_high - exit_day_low)


def trade_grade_pct(
    buy_price: float,
    sell_price: float,
    channel_upper_entry_day: float,
    channel_lower_entry_day: float,
) -> float | None:
    """`(sell price - buy price) / (channel high - channel low, measured on entry day)` --
    the trade's actual gain as a fraction of the entry day's channel height (the Autoenvelope
    band, docs/Analyse.md §4). A >=30% capture is an "A" trade, ~10% a "C" trade
    (docs/ideas.md ch. 55/ch. 33's own preview)."""
    return _ratio_pct(
        sell_price - buy_price, channel_upper_entry_day - channel_lower_entry_day
    )


def grade_trade(
    *,
    buy_price: float,
    entry_day_high: float,
    entry_day_low: float,
    sell_price: float,
    exit_day_high: float,
    exit_day_low: float,
    channel_upper_entry_day: float,
    channel_lower_entry_day: float,
) -> TradeGrade:
    """Combines the three grade formulas above into one `TradeGrade`. Pure -- no I/O, no
    DataProvider dependency; see `grade_closed_trade` below for the data-fetching wrapper
    that derives these eight arguments from a ticker's daily OHLCV history."""
    return TradeGrade(
        buy_grade_pct=buy_grade_pct(buy_price, entry_day_high, entry_day_low),
        sell_grade_pct=sell_grade_pct(sell_price, exit_day_high, exit_day_low),
        trade_grade_pct=trade_grade_pct(
            buy_price, sell_price, channel_upper_entry_day, channel_lower_entry_day
        ),
    )


def grade_trade_from_filtered_history(
    *,
    entry_price: float,
    entry_date: date,
    exit_price: float,
    exit_date: date,
    filtered_daily_ohlcv: pd.DataFrame,
    channel: pd.DataFrame,
) -> TradeGrade:
    """Grades a closed trade from a ticker's *already-filtered-and-channeled* daily history --
    `filtered_daily_ohlcv` must already have been through
    `app.signals.engine.drop_malformed_daily_bars`, and `channel` must already be
    `autoenvelope(filtered_daily_ohlcv["close"])` (or an index-compatible equivalent).

    This is the shared per-row grading step both `grade_closed_trade` (below, for a single
    trade against its own freshly-fetched history) and a caller grading many closed trades for
    the *same* ticker (e.g. `app.api.routers.portfolio._grade_closed_trades`) delegate to --
    the latter derives `filtered_daily_ohlcv`/`channel` once per ticker and calls this function
    once per row, instead of paying `drop_malformed_daily_bars`'s dropna pass and
    `autoenvelope`'s full rolling-window computation again for every closed trade on that
    ticker (see the `backend-trade-grading-followups` task).

    Returns an all-`None` `TradeGrade` (never raises) whenever `entry_date` or `exit_date`
    isn't present as an exact row in `filtered_daily_ohlcv` -- e.g. the ticker's cached/
    fetched history doesn't reach back that far, that day was dropped as malformed, or (for a
    position built from more than one buy -- see `ClosedTradeORM`'s own docstring on why
    `entry_price`/`entry_date` can be a blended, quantity-weighted value rather than a single
    literal day's purchase) `entry_date` doesn't correspond to a real trading day for this
    ticker at all -- rather than guessing from a nearby bar, since Elder's formulas are
    specifically about *that exact day's* range.
    """
    entry_ts = pd.Timestamp(entry_date)
    exit_ts = pd.Timestamp(exit_date)
    if entry_ts not in filtered_daily_ohlcv.index or exit_ts not in filtered_daily_ohlcv.index:
        return TradeGrade(buy_grade_pct=None, sell_grade_pct=None, trade_grade_pct=None)

    entry_row = filtered_daily_ohlcv.loc[entry_ts]
    exit_row = filtered_daily_ohlcv.loc[exit_ts]

    return grade_trade(
        buy_price=entry_price,
        entry_day_high=float(entry_row["high"]),
        entry_day_low=float(entry_row["low"]),
        sell_price=exit_price,
        exit_day_high=float(exit_row["high"]),
        exit_day_low=float(exit_row["low"]),
        channel_upper_entry_day=float(channel.loc[entry_ts, "upper"]),
        channel_lower_entry_day=float(channel.loc[entry_ts, "lower"]),
    )


def grade_closed_trade(
    *,
    entry_price: float,
    entry_date: date,
    exit_price: float,
    exit_date: date,
    daily_ohlcv: pd.DataFrame,
) -> TradeGrade:
    """Grades a closed trade from a ticker's full daily OHLCV history (the same frame shape
    `app.data.base.DataProvider.get_daily_ohlcv` returns -- indexed by date/Timestamp,
    oldest-first), deriving the entry/exit day's own high/low plus the entry-day channel
    bounds (`app.indicators.autoenvelope.autoenvelope`, EMA(13) +/- avg % deviation -- same
    definition as `AnalysisResponse.indicators.channel_upper`/`channel_lower`) from it, then
    delegating to `grade_trade_from_filtered_history` above.

    `daily_ohlcv` is passed through `app.signals.engine.drop_malformed_daily_bars` first
    (default `require_full_ohlc_on_latest_bar=True`, i.e. *every* bar needs full OHLC, not
    just the latest -- unlike `GET /api/portfolio/risk`'s more lenient call, this needs a
    real high/low for `entry_date`/`exit_date` specifically, which are essentially never the
    latest bar) -- see that function's own docstring for why a malformed bar's NaN
    open/high/low must never silently flow into a computation that reads them.

    This function derives `filtered_daily_ohlcv`/`channel` itself and is the right entry point
    for grading a single trade in isolation (e.g. unit tests below). A caller grading several
    closed trades for the *same* ticker should instead derive those two once and call
    `grade_trade_from_filtered_history` directly per row -- see that function's own docstring.
    """
    filtered_daily_ohlcv = drop_malformed_daily_bars(daily_ohlcv)
    channel = autoenvelope(filtered_daily_ohlcv["close"])
    return grade_trade_from_filtered_history(
        entry_price=entry_price,
        entry_date=entry_date,
        exit_price=exit_price,
        exit_date=exit_date,
        filtered_daily_ohlcv=filtered_daily_ohlcv,
        channel=channel,
    )
