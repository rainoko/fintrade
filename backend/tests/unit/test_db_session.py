"""Tests for app/db/session.py's engine/SessionLocal/get_db wiring to app/config.py's database_url."""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal, engine, get_db


def test_engine_is_wired_to_settings_database_url() -> None:
    assert str(engine.url) == get_settings().database_url


def test_session_local_produces_sqlalchemy_sessions() -> None:
    session = SessionLocal()
    try:
        assert isinstance(session, Session)
    finally:
        session.close()


def test_session_local_does_not_expire_objects_on_commit() -> None:
    """expire_on_commit=False -- see this module's `SessionLocal` comment and the
    api-portfolio-get-followups task's `decisions` entry: a request-scoped session is shared
    with CachedDataProvider (app/data/cache.py), whose per-ticker cache-miss upsert commits
    mid-loop while a route handler is still iterating over already-loaded ORM rows from an
    earlier query on the same session. The SQLAlchemy default (True) would expire every
    loaded row on that commit, turning each subsequent attribute access into its own
    re-SELECT (an N+1 query pattern) -- see
    tests/integration/test_portfolio_pricing_session.py for a behavioral reproduction."""
    assert SessionLocal.kw["expire_on_commit"] is False


def test_get_db_yields_a_session_and_closes_it_afterward() -> None:
    generator = get_db()
    db = next(generator)
    assert isinstance(db, Session)
    assert db.is_active

    # Exhausting the generator should run the `finally: db.close()` cleanup.
    generator_exhausted = False
    try:
        next(generator)
    except StopIteration:
        generator_exhausted = True
    assert generator_exhausted

    # A closed SQLAlchemy Session can still be used (it opens a fresh connection
    # transparently); what we care about is that close() actually ran without error,
    # which the generator completing without raising already demonstrates.
