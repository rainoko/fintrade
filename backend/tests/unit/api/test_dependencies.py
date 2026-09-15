"""Unit test for app/api/dependencies.py's `get_data_provider` composition.

Only checks the object graph it wires together (real network calls would violate
docs/architecture/Testing.md's "no live network calls in any test" rule and aren't
exercised here — no provider method is ever called).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_data_provider
from app.data.cache import CachedDataProvider
from app.data.stooq_provider import StooqProvider
from app.data.yfinance_provider import YFinanceProvider
from app.db.models import Base


def test_get_data_provider_wires_yfinance_primary_stooq_fallback_and_cache() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    try:
        provider = get_data_provider(db=session)

        assert isinstance(provider, CachedDataProvider)
        assert isinstance(provider._primary, YFinanceProvider)
        assert isinstance(provider._fallback, StooqProvider)
        assert provider._db is session
    finally:
        session.close()
        engine.dispose()
