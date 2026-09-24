"""GET/PUT /api/settings/trading-mode (docs/architecture/API.md).

Persists the global, app-wide active trading mode -- 'swing' (this app's existing weekly/
daily behavior, unchanged) or 'day_trader' (a user-configured long-term/intermediate/
short-term timeframe triple, Elder ch. 39's "Choosing Timeframes -- the Factor of Five") --
via `app.trading_mode`/`TradingModeSettingORM` (`app/db/models.py`).

**Scope note** (docs/tasks/backend-day-trader-timeframe-mode.json): this endpoint is the
foundational settings-persistence piece (checklist item 3) of a larger, deliberately-split
feature. As of this task, switching to `'day_trader'` here changes nothing about how any
other endpoint computes signals -- `app.signals.engine`/`app.signals.triple_screen` still
unconditionally use the hard-coded weekly/daily scheme regardless of this setting. Wiring
the configured triple into actual IBKR intraday data fetching and generic Screen 1/2/3
evaluation is tracked as a dependent follow-up task
(`backend-day-trader-timeframe-mode-intraday-signal-engine`, `depends_on` this task).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import TimeframeTripleOut, TradingModeIn, TradingModeOut
from app.db.session import get_db
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import TradingModeSetting, get_trading_mode_setting, set_trading_mode_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_out(setting: TradingModeSetting) -> TradingModeOut:
    triple_out = None
    if setting.day_trader_timeframe_triple is not None:
        triple = setting.day_trader_timeframe_triple
        triple_out = TimeframeTripleOut(
            long_term=triple.long_term.code,
            intermediate=triple.intermediate.code,
            short_term=triple.short_term.code,
            factor_of_five_warnings=triple.factor_of_five_warnings(),
        )
    return TradingModeOut(mode=setting.mode.value, day_trader_timeframe_triple=triple_out)


@router.get(
    "/trading-mode",
    response_model=TradingModeOut,
    operation_id="get_trading_mode",
    summary="Get the global active trading mode",
)
def get_trading_mode(db: Session = Depends(get_db)) -> TradingModeOut:
    """The currently-active global trading mode and, if one has ever been configured, the
    persisted day-trader timeframe triple. Defaults to `mode='swing'` with a null triple for
    a database that has never had this setting written (never a 404 -- 'not yet configured'
    is this setting's normal starting state, not an error)."""
    return _to_out(get_trading_mode_setting(db))


@router.put(
    "/trading-mode",
    response_model=TradingModeOut,
    operation_id="update_trading_mode",
    summary="Switch the global active trading mode",
    responses={
        422: {
            "description": "`day_trader_timeframe_triple` is required when `mode` is "
            "'day_trader' (FastAPI's standard HTTPValidationError, raised at the request-"
            "schema level), or an otherwise-well-formed triple violates the hard `long_term "
            "> intermediate > short_term` ordering rule (`app.signals.timeframe"
            ".TimeframeTriple`'s own construction check) -- the latter is reported as a "
            "single-string `ErrorDetail`, the same dual-422-shape convention `GET "
            "/api/stocks/{ticker}/history` already documents.",
        },
    },
)
def update_trading_mode(body: TradingModeIn, db: Session = Depends(get_db)) -> TradingModeOut:
    """Switches the global trading mode, and, when `mode` is `'day_trader'`, persists the
    supplied timeframe triple as the new day-trader configuration (validated -- a 422 if its
    three legs aren't in strictly-decreasing order -- but never rejected merely for falling
    outside ch. 39's factor-of-five spacing *guideline*; see `TimeframeTripleOut
    .factor_of_five_warnings` on the response for that non-blocking notice instead).

    Switching to `'swing'` with no `day_trader_timeframe_triple` in the request body leaves
    any previously-configured day-trader triple untouched in storage (see
    `TradingModeSettingORM`'s own docstring) -- the response still echoes it back (`mode`
    just reads `'swing'` alongside it) so a caller can see what's saved for next time without
    a second request.

    See this router module's own docstring for what switching modes does **not** yet do."""
    triple: TimeframeTriple | None = None
    if body.day_trader_timeframe_triple is not None:
        try:
            triple = TimeframeTriple(
                long_term=TimeframeInterval.parse(body.day_trader_timeframe_triple.long_term),
                intermediate=TimeframeInterval.parse(body.day_trader_timeframe_triple.intermediate),
                short_term=TimeframeInterval.parse(body.day_trader_timeframe_triple.short_term),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    setting = set_trading_mode_setting(
        db, mode=TradingMode(body.mode), day_trader_timeframe_triple=triple
    )
    return _to_out(setting)
