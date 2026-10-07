"""Run a .sql file against the database as the OWNER role, in ONE transaction.

Usage (from backend/):
    python -m scripts.run_sql db/001_schema.sql --dry-run   # execute, then ROLL BACK
    python -m scripts.run_sql db/001_schema.sql             # execute and COMMIT

One transaction = all-or-nothing: if any statement fails, nothing is applied.
"""
import argparse
from pathlib import Path

from app.db import owner_engine


class DryRun(Exception):
    """Raised on purpose to force a rollback in --dry-run mode."""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_file")
    parser.add_argument("--dry-run", action="store_true", help="roll back instead of commit")
    args = parser.parse_args()

    sql = Path(args.sql_file).read_text()
    try:
        # engine.begin() commits on success and rolls back on any exception.
        with owner_engine.begin() as conn:
            # No bind parameters -> psycopg allows many statements in one string.
            conn.exec_driver_sql(sql)
            if args.dry_run:
                raise DryRun
        print(f"COMMITTED: {args.sql_file}")
    except DryRun:
        print(f"DRY RUN OK (rolled back, nothing changed): {args.sql_file}")


if __name__ == "__main__":
    main()
