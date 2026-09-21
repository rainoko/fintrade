"""POST/GET /api/daily-homework + GET /api/daily-homework/today +
GET /api/daily-homework/yesterday-trading-suggestion (docs/architecture/API.md).

Elder ch. 57's "Am I ready to trade?" 5-question daily psychological readiness self-test
(docs/ideas.md's ch. 57 entry) -- purely subjective, zero market data, zero provider calls.
One `DailyHomeworkEntryORM` row per calendar day (app/db/models.py); the summed-score
color-banding and the yesterday's-trading-suggestion are pure computations in
`app.portfolio.homework`, so they're testable without any of this router's I/O.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import (
    DailyHomeworkIn,
    DailyHomeworkListResponse,
    DailyHomeworkOut,
    DailyHomeworkTodayResponse,
    YesterdayTradingSuggestionOut,
)
from app.db.models import ClosedTradeORM, DailyHomeworkEntryORM
from app.db.session import get_db
from app.portfolio.homework import band_for_total_score, suggested_yesterday_trading_score
from app.time_utils import today, utcnow

router = APIRouter(prefix="/api/daily-homework", tags=["daily-homework"])


def _to_out(row: DailyHomeworkEntryORM) -> DailyHomeworkOut:
    total_score = (
        row.physical_state_score
        + row.yesterday_trading_score
        + row.trade_planning_score
        + row.mood_score
        + row.schedule_score
    )
    return DailyHomeworkOut(
        date=row.date,
        physical_state_score=row.physical_state_score,
        yesterday_trading_score=row.yesterday_trading_score,
        trade_planning_score=row.trade_planning_score,
        mood_score=row.mood_score,
        schedule_score=row.schedule_score,
        total_score=total_score,
        band=band_for_total_score(total_score),
        recorded_at=row.recorded_at,
    )


@router.post(
    "",
    response_model=DailyHomeworkOut,
    status_code=201,
    operation_id="record_daily_homework",
    summary="Record (or overwrite) a calendar day's 5-question self-test scores",
)
def record_daily_homework(
    entry: DailyHomeworkIn, db: Session = Depends(get_db)
) -> DailyHomeworkOut:
    """Records the day's five 0/1/2 scores (`entry.date`, defaulting to today) as one
    `daily_homework_entries` row. A second submission for a day that already has a recorded
    entry overwrites that day's scores (and `recorded_at`) rather than rejecting the request
    or creating a second row for the same day -- always `201`, whether this created a new row
    or overwrote an existing one, mirroring `POST /api/portfolio/positions`/
    `POST /api/watchlist`'s identical "same status code either way" convention -- see this
    task's `decisions` entry."""
    entry_date = entry.date if entry.date is not None else today()
    row = db.get(DailyHomeworkEntryORM, entry_date)
    if row is None:
        row = DailyHomeworkEntryORM(date=entry_date)
        db.add(row)

    row.physical_state_score = entry.physical_state_score
    row.yesterday_trading_score = entry.yesterday_trading_score
    row.trade_planning_score = entry.trade_planning_score
    row.mood_score = entry.mood_score
    row.schedule_score = entry.schedule_score
    row.recorded_at = utcnow()

    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get(
    "/today",
    response_model=DailyHomeworkTodayResponse,
    operation_id="get_daily_homework_today",
    summary="Get today's self-test entry, if recorded",
)
def get_daily_homework_today(db: Session = Depends(get_db)) -> DailyHomeworkTodayResponse:
    """Today's (server UTC date) recorded entry, or a null `entry` if today's self-test
    hasn't been recorded yet -- never a `404`, since "not done yet today" is the normal,
    expected state at the start of every day, not an error."""
    row = db.get(DailyHomeworkEntryORM, today())
    return DailyHomeworkTodayResponse(entry=_to_out(row) if row is not None else None)


@router.get(
    "",
    response_model=DailyHomeworkListResponse,
    operation_id="list_daily_homework",
    summary="List recorded self-test entries, most recent day first",
)
def list_daily_homework(db: Session = Depends(get_db)) -> DailyHomeworkListResponse:
    """Every recorded self-test entry, most recent `date` first -- a history/trend view of
    how "ready to trade" scores have looked over time."""
    rows = db.query(DailyHomeworkEntryORM).order_by(DailyHomeworkEntryORM.date.desc()).all()
    return DailyHomeworkListResponse(items=[_to_out(row) for row in rows])


@router.get(
    "/yesterday-trading-suggestion",
    response_model=YesterdayTradingSuggestionOut,
    operation_id="get_yesterday_trading_suggestion",
    summary="Suggest today's 'how did I trade yesterday?' score from yesterday's closed trades",
)
def get_yesterday_trading_suggestion(
    db: Session = Depends(get_db),
) -> YesterdayTradingSuggestionOut:
    """A suggested (never auto-applied) `yesterday_trading_score` derived from the net
    `realized_pnl` of every `closed_trades` row exited yesterday (server UTC 'today' minus one
    day) -- a cheap, optional enhancement over Elder's own fully-manual-recall version of this
    question. Never writes anything; a caller (e.g. the daily homework form) may use
    `suggested_score` to pre-fill the field, but `POST /api/daily-homework`'s
    `yesterday_trading_score` is always the caller's own explicit answer -- see this task's
    `decisions` entry for why this stays a suggestion rather than an auto-populated field."""
    yesterday = today() - timedelta(days=1)
    rows = db.query(ClosedTradeORM).filter(ClosedTradeORM.exit_date == yesterday).all()
    net_realized_pnl = sum(row.realized_pnl for row in rows) if rows else None
    return YesterdayTradingSuggestionOut(
        as_of_date=yesterday,
        net_realized_pnl=net_realized_pnl,
        suggested_score=suggested_yesterday_trading_score(net_realized_pnl),
    )
