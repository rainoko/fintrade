"""Idempotent fix-up for a known kind of pre-Alembic schema drift.

See docs/architecture/Backend.md §7: `alembic stamp head` against a database
seeded by app/main.py's `Base.metadata.create_all` stopgap only produces a
correct schema if the live tables already match what the initial migration
would create. The one specific, currently-known way they might not: a
`positions` table created before `unique=True` was added to
`PositionORM.ticker` (see the api-portfolio-add-position task's `decisions`)
has an *index* named `ix_positions_ticker` (from the `index=True` it always
had) but that index is not unique -- stamping such a database as head does
not retroactively fix that, since stamp only records a revision as applied
without touching the schema.

This script closes that specific gap: it connects to the database configured
via `app.config.get_settings().database_url` (the same source of truth
app/db/migrations/env.py uses) and ensures `positions.ticker` has a unique
index named `ix_positions_ticker`, matching what the initial migration
creates on a fresh database. It is safe to run any number of times, in any
order relative to `alembic stamp head`, against any database state:

- No `positions` table yet: does nothing (a subsequent `alembic upgrade head`
  on a fresh database creates the table, with the index, correctly).
- `positions` exists with the unique index already in place (a fresh
  create_all-seeded database, matching the current model): does nothing.
- `positions` exists with a same-named but *non-unique* index (the drifted
  case above): drops that index and recreates it as unique. Deliberately does
  NOT use `CREATE UNIQUE INDEX IF NOT EXISTS` for this case -- SQLite's
  `IF NOT EXISTS` only checks the index *name*, not its definition, so it
  would silently skip fixing a same-named-but-wrong index instead of
  correcting it.
- `positions` exists with duplicate ticker values under the old non-unique
  index: the `CREATE UNIQUE INDEX` fails loudly (an OperationalError /
  IntegrityError from the database, surfaced as a non-zero exit here) rather
  than silently leaving the table inconsistent -- that case is a genuine data
  problem (two rows claiming the same ticker) that needs a manual decision
  about which row wins, not something this script should paper over.

This only fixes this one specific, currently-known drift case; it is not a
general schema-diff tool. If app/db/models.py changes in a way that
introduces a new kind of possible drift for pre-Alembic databases, extend
this script (or replace it with a general check) rather than assuming it
still covers the new case -- see docs/tasks/db-migrations-followups.json's
decisions for why a narrow, targeted fix was chosen over a general one here.

Usage: python scripts/fix_schema_drift.py
(intended to be run once, as part of retrofitting Alembic onto a
create_all-seeded database -- see README.md's "Database migrations" section)
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import get_settings

POSITIONS_TABLE = "positions"
TICKER_COLUMN = "ticker"
UNIQUE_INDEX_NAME = "ix_positions_ticker"


def _index_is_correct(engine: Engine) -> tuple[bool, bool]:
    """Returns (table_exists, index_is_already_correct)."""
    inspector = inspect(engine)
    if POSITIONS_TABLE not in inspector.get_table_names():
        return False, False

    indexes = {idx["name"]: idx for idx in inspector.get_indexes(POSITIONS_TABLE)}
    existing = indexes.get(UNIQUE_INDEX_NAME)
    is_correct = (
        existing is not None
        and existing["unique"]
        and existing["column_names"] == [TICKER_COLUMN]
    )
    return True, is_correct


def ensure_positions_ticker_unique_index(database_url: str) -> bool:
    """Ensure `positions.ticker` has its unique index. Returns True if a fix was
    applied (drift was found and corrected), False if nothing needed doing
    (no `positions` table yet, or the index was already correct).

    Raises whatever the underlying database driver raises if the table has
    duplicate ticker values and the unique index genuinely can't be created --
    that's a real data problem, not something to swallow.
    """
    engine = create_engine(database_url)
    try:
        table_exists, is_correct = _index_is_correct(engine)
        if not table_exists or is_correct:
            return False

        with engine.begin() as conn:
            # Drop first (not `CREATE UNIQUE INDEX IF NOT EXISTS`): a same-named
            # but non-unique index from the pre-`unique=True` schema already
            # exists here, and IF NOT EXISTS only checks the name.
            conn.execute(text(f"DROP INDEX IF EXISTS {UNIQUE_INDEX_NAME}"))
            conn.execute(
                text(
                    f"CREATE UNIQUE INDEX {UNIQUE_INDEX_NAME} "
                    f"ON {POSITIONS_TABLE} ({TICKER_COLUMN})"
                )
            )
        return True
    finally:
        engine.dispose()


def main() -> int:
    database_url = get_settings().database_url
    try:
        fixed = ensure_positions_ticker_unique_index(database_url)
    except Exception as exc:  # noqa: BLE001 - deliberately fail loudly, see module docstring
        print(
            f"Could not create the unique index on positions.ticker against "
            f"{database_url}: {exc}\n"
            "This usually means the table already has duplicate ticker values "
            "under the old non-unique index -- resolve the duplicates manually "
            "(decide which row should win) before re-running this script.",
            file=sys.stderr,
        )
        return 1

    if fixed:
        print(
            f"Fixed schema drift: positions.ticker now has a unique index "
            f"({database_url})."
        )
    else:
        print(
            f"No drift found: positions.ticker's unique index is already "
            f"correct, or the table doesn't exist yet ({database_url})."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
