from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
# expire_on_commit=False: a request-scoped session is shared with CachedDataProvider
# (app/data/cache.py), whose per-ticker cache-miss upsert commits mid-loop while a route
# handler (e.g. GET /api/portfolio's enrich_positions_with_price loop) is still iterating
# over already-loaded ORM rows from an earlier query on the same session. The SQLAlchemy
# default (True) would expire every loaded row on that commit, turning each subsequent
# attribute access into its own re-SELECT -- an N+1 query pattern on any cache miss. Explicit
# db.refresh() calls (e.g. app/api/routers/portfolio.py's add_position) are unaffected: they
# always re-fetch regardless of this setting. See the api-portfolio-get-followups task's
# `decisions` entry.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
