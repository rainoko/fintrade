"""Global, app-wide trading-mode settings persistence (docs/tasks/
backend-day-trader-timeframe-mode.json checklist item 3): reads/writes the single
`TradingModeSettingORM` row (`app/db/models.py`) backing `GET`/`PUT
/api/settings/trading-mode` (`app.api.routers.settings`).

Kept as its own top-level module (parallel to `app.config`'s env-based `Settings`, not nested
under `app.portfolio`/`app.signals`) since this is app-wide configuration state, not a
domain/signal concept itself -- `app.signals.timeframe` (the `TimeframeTriple`/`TradingMode`
domain model this module reads and writes) has no persistence or FastAPI knowledge of its own,
matching this codebase's existing "pure domain module + thin persistence/API layer" split
(e.g. `app.portfolio.homework`'s pure banding function vs. `app.api.routers.homework`'s
DB-backed routes).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import TradingModeSettingORM
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.time_utils import utcnow

_SETTINGS_ROW_ID = 1


@dataclass(frozen=True)
class TradingModeSetting:
    """The currently-active global trading mode, plus the day-trader timeframe triple last
    configured for it (present even while `mode == TradingMode.SWING` if one was ever
    configured before switching back -- see `TradingModeSettingORM`'s own docstring for why
    that's preserved rather than cleared)."""

    mode: TradingMode
    day_trader_timeframe_triple: TimeframeTriple | None


def _to_domain(row: TradingModeSettingORM) -> TradingModeSetting:
    triple = None
    if (
        row.day_trader_long_term is not None
        and row.day_trader_intermediate is not None
        and row.day_trader_short_term is not None
    ):
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse(row.day_trader_long_term),
            intermediate=TimeframeInterval.parse(row.day_trader_intermediate),
            short_term=TimeframeInterval.parse(row.day_trader_short_term),
        )
    return TradingModeSetting(mode=TradingMode(row.mode), day_trader_timeframe_triple=triple)


def get_trading_mode_setting(db: Session) -> TradingModeSetting:
    """The currently-active global trading mode. Defaults to `TradingMode.SWING` with no
    configured triple if the settings row doesn't exist yet (a brand-new database, or one
    that predates this task) -- this is a pure read, so it deliberately does **not** create
    the row itself; `set_trading_mode_setting` below is the only writer, matching
    `AccountORM`'s own "read defaults, only a write actually creates the row" convention
    (`app.api.routers.portfolio.get_portfolio`'s `db.get(AccountORM, 1)` -> default `cash=0.0`
    when absent)."""
    row = db.get(TradingModeSettingORM, _SETTINGS_ROW_ID)
    if row is None:
        return TradingModeSetting(mode=TradingMode.SWING, day_trader_timeframe_triple=None)
    return _to_domain(row)


def set_trading_mode_setting(
    db: Session, *, mode: TradingMode, day_trader_timeframe_triple: TimeframeTriple | None
) -> TradingModeSetting:
    """Persists `mode` (and, if given, `day_trader_timeframe_triple`) as the new global
    setting, creating the singleton row on first use. Commits the session itself (matching
    `POST /api/daily-homework`'s `record_daily_homework` convention of the persistence-layer
    call owning its own commit) since this is always called from a single-purpose API route
    with nothing else to batch into the same transaction.

    `day_trader_timeframe_triple=None` leaves any previously-persisted triple untouched
    (doesn't clear it) -- this is what lets a `PUT` that only switches `mode` back to
    `'swing'` (with no triple in the request) preserve a previously-configured day-trader
    triple for next time, per `TradingModeSettingORM`'s own documented "preserve across
    switches" decision. The caller (`app.api.routers.settings.update_trading_mode`) is
    responsible for the actual validation that a `day_trader` `mode` request always supplies
    a triple -- this function has no opinion on that, it just persists whatever combination
    it's given."""
    row = db.get(TradingModeSettingORM, _SETTINGS_ROW_ID)
    if row is None:
        row = TradingModeSettingORM(id=_SETTINGS_ROW_ID)
        db.add(row)

    row.mode = mode.value
    if day_trader_timeframe_triple is not None:
        row.day_trader_long_term = day_trader_timeframe_triple.long_term.code
        row.day_trader_intermediate = day_trader_timeframe_triple.intermediate.code
        row.day_trader_short_term = day_trader_timeframe_triple.short_term.code
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return _to_domain(row)
