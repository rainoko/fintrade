"""CRUD tests for the SQLAlchemy ORM models (app/db/models.py) against an in-memory SQLite session.

Exercises PositionORM, AccountORM, and OHLCVCacheORM independently of any API/router layer.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AccountORM, Base, OHLCVCacheORM, PositionORM, WatchlistItemORM


@pytest.fixture
def session():
    """A fresh in-memory SQLite database + session per test, created from Base.metadata."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db: Session = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


class TestPositionORM:
    def test_create_and_read(self, session: Session) -> None:
        position = PositionORM(
            id="pos_123",
            ticker="AAPL",
            quantity=100,
            avg_cost_basis=195.30,
            entry_date=date(2026, 5, 14),
        )
        session.add(position)
        session.commit()

        fetched = session.get(PositionORM, "pos_123")
        assert fetched is not None
        assert fetched.ticker == "AAPL"
        assert fetched.quantity == 100
        assert fetched.avg_cost_basis == 195.30
        assert fetched.entry_date == date(2026, 5, 14)

    def test_update(self, session: Session) -> None:
        session.add(
            PositionORM(
                id="pos_1",
                ticker="MSFT",
                quantity=10,
                avg_cost_basis=300.0,
                entry_date=date(2026, 1, 1),
            )
        )
        session.commit()

        position = session.get(PositionORM, "pos_1")
        assert position is not None
        position.quantity = 20
        session.commit()

        refetched = session.get(PositionORM, "pos_1")
        assert refetched is not None
        assert refetched.quantity == 20

    def test_delete(self, session: Session) -> None:
        session.add(
            PositionORM(
                id="pos_2",
                ticker="GOOG",
                quantity=5,
                avg_cost_basis=150.0,
                entry_date=date(2026, 2, 1),
            )
        )
        session.commit()

        position = session.get(PositionORM, "pos_2")
        assert position is not None
        session.delete(position)
        session.commit()

        assert session.get(PositionORM, "pos_2") is None

    def test_list_multiple_positions(self, session: Session) -> None:
        session.add_all(
            [
                PositionORM(
                    id="pos_a",
                    ticker="AAPL",
                    quantity=1,
                    avg_cost_basis=1.0,
                    entry_date=date(2026, 1, 1),
                ),
                PositionORM(
                    id="pos_b",
                    ticker="TSLA",
                    quantity=2,
                    avg_cost_basis=2.0,
                    entry_date=date(2026, 1, 2),
                ),
            ]
        )
        session.commit()

        positions = session.query(PositionORM).order_by(PositionORM.id).all()
        assert [p.id for p in positions] == ["pos_a", "pos_b"]


class TestAccountORM:
    def test_create_and_read(self, session: Session) -> None:
        account = AccountORM(id=1, cash=5000.0)
        session.add(account)
        session.commit()

        fetched = session.get(AccountORM, 1)
        assert fetched is not None
        assert fetched.cash == 5000.0

    def test_default_cash_is_zero(self, session: Session) -> None:
        account = AccountORM(id=1)
        session.add(account)
        session.commit()
        session.refresh(account)

        assert account.cash == 0.0

    def test_single_row_update(self, session: Session) -> None:
        session.add(AccountORM(id=1, cash=1000.0))
        session.commit()

        account = session.get(AccountORM, 1)
        assert account is not None
        account.cash = 1500.0
        session.commit()

        refetched = session.get(AccountORM, 1)
        assert refetched is not None
        assert refetched.cash == 1500.0


class TestOHLCVCacheORM:
    def test_create_and_read_composite_key(self, session: Session) -> None:
        row = OHLCVCacheORM(
            ticker="AAPL",
            date=date(2026, 5, 14),
            interval="daily",
            open=190.0,
            high=195.0,
            low=188.0,
            close=193.5,
            volume=1_000_000,
            fetched_at=datetime(2026, 5, 14, 21, 0, 0),
        )
        session.add(row)
        session.commit()

        fetched = session.get(OHLCVCacheORM, ("AAPL", date(2026, 5, 14), "daily"))
        assert fetched is not None
        assert fetched.close == 193.5
        assert fetched.volume == 1_000_000

    def test_same_ticker_different_interval_is_distinct_row(self, session: Session) -> None:
        common = {
            "ticker": "AAPL",
            "date": date(2026, 5, 14),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 100,
            "fetched_at": datetime(2026, 5, 14),
        }
        session.add(OHLCVCacheORM(interval="daily", **common))
        session.add(OHLCVCacheORM(interval="weekly", **common))
        session.commit()

        rows = session.query(OHLCVCacheORM).filter_by(ticker="AAPL", date=date(2026, 5, 14)).all()
        assert {r.interval for r in rows} == {"daily", "weekly"}

    def test_delete(self, session: Session) -> None:
        row = OHLCVCacheORM(
            ticker="MSFT",
            date=date(2026, 1, 1),
            interval="daily",
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
            fetched_at=datetime(2026, 1, 1),
        )
        session.add(row)
        session.commit()

        key = ("MSFT", date(2026, 1, 1), "daily")
        fetched = session.get(OHLCVCacheORM, key)
        assert fetched is not None
        session.delete(fetched)
        session.commit()

        assert session.get(OHLCVCacheORM, key) is None


class TestWatchlistItemORM:
    def test_create_and_read(self, session: Session) -> None:
        item = WatchlistItemORM(ticker="AAPL", added_at=datetime(2026, 5, 14, 12, 0, 0))
        session.add(item)
        session.commit()

        fetched = session.get(WatchlistItemORM, "AAPL")
        assert fetched is not None
        assert fetched.ticker == "AAPL"
        assert fetched.added_at == datetime(2026, 5, 14, 12, 0, 0)

    def test_ticker_is_the_primary_key(self, session: Session) -> None:
        session.add(WatchlistItemORM(ticker="AAPL", added_at=datetime(2026, 1, 1)))
        session.commit()

        # Re-adding the same ticker (same primary key) must be rejected at the DB level --
        # a watchlist holds at most one entry per ticker.
        session.add(WatchlistItemORM(ticker="AAPL", added_at=datetime(2026, 1, 2)))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_delete(self, session: Session) -> None:
        session.add(WatchlistItemORM(ticker="TSLA", added_at=datetime(2026, 3, 1)))
        session.commit()

        item = session.get(WatchlistItemORM, "TSLA")
        assert item is not None
        session.delete(item)
        session.commit()

        assert session.get(WatchlistItemORM, "TSLA") is None

    def test_list_multiple_items(self, session: Session) -> None:
        session.add_all(
            [
                WatchlistItemORM(ticker="AAPL", added_at=datetime(2026, 1, 1)),
                WatchlistItemORM(ticker="TSLA", added_at=datetime(2026, 1, 2)),
            ]
        )
        session.commit()

        items = session.query(WatchlistItemORM).order_by(WatchlistItemORM.ticker).all()
        assert [i.ticker for i in items] == ["AAPL", "TSLA"]
