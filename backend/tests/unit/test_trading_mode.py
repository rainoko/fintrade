"""Tests for app.trading_mode (global trading-mode settings persistence, docs/tasks/
backend-day-trader-timeframe-mode.json checklist item 3) against an in-memory SQLite session
-- independent of the API/router layer (see tests/integration/test_trading_mode.py for the
route-level tests).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.signals.timeframe import TimeframeInterval, TimeframeTriple, TradingMode
from app.trading_mode import get_trading_mode_setting, set_trading_mode_setting


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db: Session = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestGetTradingModeSetting:
    def test_defaults_to_swing_with_no_triple_when_never_configured(self, session: Session) -> None:
        setting = get_trading_mode_setting(session)
        assert setting.mode is TradingMode.SWING
        assert setting.day_trader_timeframe_triple is None


class TestSetTradingModeSetting:
    def test_switching_to_day_trader_persists_the_triple(self, session: Session) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        result = set_trading_mode_setting(
            session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=triple
        )
        assert result.mode is TradingMode.DAY_TRADER
        assert result.day_trader_timeframe_triple == triple

        reread = get_trading_mode_setting(session)
        assert reread.mode is TradingMode.DAY_TRADER
        assert reread.day_trader_timeframe_triple == triple

    def test_switching_back_to_swing_preserves_the_previously_configured_triple(
        self, session: Session
    ) -> None:
        triple = TimeframeTriple(
            long_term=TimeframeInterval.parse("1w"),
            intermediate=TimeframeInterval.parse("1d"),
            short_term=TimeframeInterval.parse("120m"),
        )
        set_trading_mode_setting(
            session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=triple
        )

        result = set_trading_mode_setting(
            session, mode=TradingMode.SWING, day_trader_timeframe_triple=None
        )
        assert result.mode is TradingMode.SWING
        # Preserved, not cleared -- see TradingModeSettingORM's own docstring.
        assert result.day_trader_timeframe_triple == triple

        reread = get_trading_mode_setting(session)
        assert reread.mode is TradingMode.SWING
        assert reread.day_trader_timeframe_triple == triple

    def test_reconfiguring_day_trader_triple_overwrites_the_previous_one(
        self, session: Session
    ) -> None:
        first = TimeframeTriple(
            long_term=TimeframeInterval.parse("25m"),
            intermediate=TimeframeInterval.parse("5m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        second = TimeframeTriple(
            long_term=TimeframeInterval.parse("39m"),
            intermediate=TimeframeInterval.parse("8m"),
            short_term=TimeframeInterval.parse("2m"),
        )
        set_trading_mode_setting(
            session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=first
        )
        result = set_trading_mode_setting(
            session, mode=TradingMode.DAY_TRADER, day_trader_timeframe_triple=second
        )
        assert result.day_trader_timeframe_triple == second

    def test_creates_the_singleton_row_on_first_write(self, session: Session) -> None:
        from app.db.models import TradingModeSettingORM

        assert session.get(TradingModeSettingORM, 1) is None
        set_trading_mode_setting(session, mode=TradingMode.SWING, day_trader_timeframe_triple=None)
        row = session.get(TradingModeSettingORM, 1)
        assert row is not None
        assert row.mode == "swing"
        assert row.updated_at is not None
