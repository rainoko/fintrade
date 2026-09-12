from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PositionORM(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    quantity: Mapped[float] = mapped_column(Float)
    avg_cost_basis: Mapped[float] = mapped_column(Float)
    entry_date: Mapped[date] = mapped_column(Date)


class AccountORM(Base):
    """Single-row table holding the cash balance for this single-user MVP (docs/Architecture.md §4)."""

    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    cash: Mapped[float] = mapped_column(Float, default=0.0)


class OHLCVCacheORM(Base):
    """Cached market data, keyed by ticker + date + interval (docs/architecture/Backend.md §7)."""

    __tablename__ = "ohlcv_cache"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    interval: Mapped[str] = mapped_column(String, primary_key=True)  # 'daily' | 'weekly'
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
