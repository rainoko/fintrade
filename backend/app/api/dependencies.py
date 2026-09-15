"""Shared FastAPI dependencies for the API routers (app/api/routers/*.py).

Kept separate from app/db/session.py (which only knows about the DB session)
so any router needing market data — the first is GET /api/portfolio's price
enrichment — depends on one composed `DataProvider` rather than each router
wiring up YFinanceProvider/StooqProvider/CachedDataProvider by hand. See the
api-portfolio-get task's `decisions` entry for why this lives here instead of
inline in app/data/cache.py.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.data.base import DataProvider
from app.data.cache import CachedDataProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.session import get_db


def get_data_provider(db: Session = Depends(get_db)) -> DataProvider:
    """The market-data provider used by API routes: yfinance primary, Stooq
    fallback (docs/Analyse.md §9), both behind the SQLite read-through cache
    (docs/architecture/Backend.md §7). A fresh pair of provider adapters is
    constructed per request — they're stateless, so this is cheap — while the
    cache shares the request's `db` session.
    """
    return CachedDataProvider(YFinanceProvider(), StooqProvider(), db)
