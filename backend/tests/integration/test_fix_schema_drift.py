"""Regression tests for scripts/fix_schema_drift.py -- the follow-up from PR #46's
review (docs/tasks/db-migrations-followups.json) closing the gap where a `positions`
table predating `unique=True` on `PositionORM.ticker` doesn't retroactively gain that
unique index just from `alembic stamp head` (see docs/architecture/Backend.md §7).

Covers, against a real throwaway SQLite file (no network, sqlite3 is stdlib only):

1. No `positions` table yet -> no-op.
2. A `positions` table with the old non-unique `ix_positions_ticker` index (the actual
   drifted shape, reproduced with raw SQL matching the pre-`unique=True` model) -> the
   index is corrected to unique, and it stays correct if run again (idempotent).
3. The same drifted table but with duplicate ticker values already present -> fails
   loudly (raises / non-zero exit) instead of silently leaving the table inconsistent.
4. A fresh, already-correct database (create_all with the current model) -> no-op.
5. End-to-end: fix the drift, then `alembic stamp head` against it, matching the
   documented retrofit workflow in README.md.
"""

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.db.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "fix_schema_drift.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("fix_schema_drift", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fix_schema_drift = _load_script_module()


def _run_script(database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=BACKEND_DIR,
        env={**os.environ, "FINTRADE_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _create_drifted_positions_table(db_path: Path, *, ticker_rows: list[tuple[str, str, float, float, str]]) -> None:
    """Reproduces the pre-`unique=True` schema: a `positions` table with a non-unique
    index named `ix_positions_ticker` (from `index=True`, which the column always had),
    seeded with the given rows."""
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "CREATE TABLE positions ("
            "id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, quantity FLOAT NOT NULL, "
            "avg_cost_basis FLOAT NOT NULL, entry_date DATE NOT NULL, "
            "PRIMARY KEY (id))"
        )
        con.execute("CREATE INDEX ix_positions_ticker ON positions (ticker)")
        con.executemany(
            "INSERT INTO positions (id, ticker, quantity, avg_cost_basis, entry_date) "
            "VALUES (?, ?, ?, ?, ?)",
            ticker_rows,
        )
        con.commit()
    finally:
        con.close()


def _index_info(db_path: Path, index_name: str) -> tuple[bool, bool]:
    """Returns (exists, is_unique)."""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        for idx in inspector.get_indexes("positions"):
            if idx["name"] == index_name:
                return True, bool(idx["unique"])
        return False, False
    finally:
        engine.dispose()


class TestNoPositionsTableYet:
    def test_is_a_no_op(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        fixed = fix_schema_drift.ensure_positions_ticker_unique_index(f"sqlite:///{db_path}")

        assert fixed is False

    def test_subprocess_exits_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        result = _run_script(f"sqlite:///{db_path}")

        assert result.returncode == 0, result.stderr
        assert "No drift found" in result.stdout


class TestDriftedTableWithUniqueTickers:
    def test_corrects_the_index_to_unique(self, tmp_path: Path) -> None:
        db_path = tmp_path / "drifted.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[("1", "AAPL", 10.0, 100.0, "2026-01-01")],
        )
        assert _index_info(db_path, "ix_positions_ticker") == (True, False)

        fixed = fix_schema_drift.ensure_positions_ticker_unique_index(f"sqlite:///{db_path}")

        assert fixed is True
        assert _index_info(db_path, "ix_positions_ticker") == (True, True)

    def test_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "drifted.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[("1", "AAPL", 10.0, 100.0, "2026-01-01")],
        )
        database_url = f"sqlite:///{db_path}"

        first = fix_schema_drift.ensure_positions_ticker_unique_index(database_url)
        second = fix_schema_drift.ensure_positions_ticker_unique_index(database_url)

        assert first is True
        assert second is False
        assert _index_info(db_path, "ix_positions_ticker") == (True, True)

    def test_now_actually_rejects_a_duplicate_ticker_insert(self, tmp_path: Path) -> None:
        db_path = tmp_path / "drifted.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[("1", "AAPL", 10.0, 100.0, "2026-01-01")],
        )
        fix_schema_drift.ensure_positions_ticker_unique_index(f"sqlite:///{db_path}")

        con = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO positions (id, ticker, quantity, avg_cost_basis, entry_date) "
                    "VALUES ('2', 'AAPL', 5.0, 90.0, '2026-02-01')"
                )
        finally:
            con.close()

    def test_subprocess_reports_the_fix(self, tmp_path: Path) -> None:
        db_path = tmp_path / "drifted.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[("1", "AAPL", 10.0, 100.0, "2026-01-01")],
        )
        result = _run_script(f"sqlite:///{db_path}")

        assert result.returncode == 0, result.stderr
        assert "Fixed schema drift" in result.stdout


class TestDriftedTableWithDuplicateTickers:
    """The genuinely-inconsistent case: two rows already claim the same ticker under
    the old non-unique index. Must fail loudly, not silently succeed or corrupt data."""

    def test_raises_instead_of_silently_leaving_duplicates(self, tmp_path: Path) -> None:
        db_path = tmp_path / "duplicated.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[
                ("1", "AAPL", 10.0, 100.0, "2026-01-01"),
                ("2", "AAPL", 5.0, 90.0, "2026-02-01"),
            ],
        )

        with pytest.raises(fix_schema_drift.DuplicateTickerError):
            fix_schema_drift.ensure_positions_ticker_unique_index(f"sqlite:///{db_path}")

        # The duplicate check runs *before* the old index is ever dropped, so the
        # pre-existing (non-unique) index must survive untouched -- not be left
        # missing/partial -- and the duplicate rows are untouched (nothing silently
        # dropped).
        assert _index_info(db_path, "ix_positions_ticker") == (True, False)
        con = sqlite3.connect(db_path)
        try:
            (count,) = con.execute("SELECT COUNT(*) FROM positions WHERE ticker = 'AAPL'").fetchone()
        finally:
            con.close()
        assert count == 2

    def test_subprocess_exits_non_zero_with_a_helpful_message(self, tmp_path: Path) -> None:
        db_path = tmp_path / "duplicated.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[
                ("1", "AAPL", 10.0, 100.0, "2026-01-01"),
                ("2", "AAPL", 5.0, 90.0, "2026-02-01"),
            ],
        )
        result = _run_script(f"sqlite:///{db_path}")

        assert result.returncode == 1
        assert "duplicate ticker" in result.stderr


class TestAlreadyCorrectDatabase:
    """A fresh create_all-seeded database, matching the current model -- the common
    case, not the drifted one."""

    def test_is_a_no_op(self, tmp_path: Path) -> None:
        db_path = tmp_path / "fresh.db"
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
        assert _index_info(db_path, "ix_positions_ticker") == (True, True)

        fixed = fix_schema_drift.ensure_positions_ticker_unique_index(f"sqlite:///{db_path}")

        assert fixed is False
        assert _index_info(db_path, "ix_positions_ticker") == (True, True)


class TestEndToEndWithAlembicStampHead:
    def _run_alembic(self, *args: str, database_url: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env={**os.environ, "FINTRADE_DATABASE_URL": database_url},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_fix_then_stamp_leaves_a_correct_and_up_to_date_schema(self, tmp_path: Path) -> None:
        db_path = tmp_path / "retrofit.db"
        _create_drifted_positions_table(
            db_path,
            ticker_rows=[("1", "AAPL", 10.0, 100.0, "2026-01-01")],
        )
        database_url = f"sqlite:///{db_path}"

        fix_result = _run_script(database_url)
        assert fix_result.returncode == 0, fix_result.stderr

        stamp_result = self._run_alembic("stamp", "head", database_url=database_url)
        assert stamp_result.returncode == 0, stamp_result.stderr

        assert _index_info(db_path, "ix_positions_ticker") == (True, True)

        upgrade_result = self._run_alembic("upgrade", "head", database_url=database_url)
        assert upgrade_result.returncode == 0, upgrade_result.stderr
