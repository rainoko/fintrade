"""Shared fixtures for tests/integration/*.

`db_session` and `client` were previously copy-pasted verbatim across
test_portfolio_positions.py, test_portfolio_get.py, and test_portfolio_delete_position.py; they
live here so future DB-touching route tests can reuse them instead of pasting a fourth copy.

test_portfolio_get.py additionally needs a `get_data_provider` override (a stub market-data
provider), so it keeps its own local `client` fixture that builds on the `db_session` fixture
defined here rather than using this module's `client`.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def db_session():
    # StaticPool keeps a single connection alive for the whole engine, which is required for
    # an in-memory SQLite database to be visible across threads — TestClient runs requests on
    # a separate thread from the one that created the tables below.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
