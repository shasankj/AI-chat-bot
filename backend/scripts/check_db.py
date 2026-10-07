"""Step 1 check: connect with both roles and report what each is allowed to do.

Run from backend/:  python -m scripts.check_db
Read-only: it creates nothing permanent (the write test runs in a rolled-back transaction).
"""
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import owner_engine, read_engine


def probe(name: str, engine) -> None:
    print(f"\n=== {name} ===")
    with engine.connect() as conn:
        print("connected as:", conn.execute(text("select current_user")).scalar())
        print("pgvector    :", conn.execute(
            text("select extversion from pg_extension where extname='vector'")).scalar())

        # Existing tables in public schema (yours are safe: we never touch them).
        tables = conn.execute(text(
            "select table_name from information_schema.tables "
            "where table_schema='public' order by 1")).scalars().all()
        print("existing tables:", tables or "none")

        # Can this role create tables? Test inside a transaction we roll back.
        try:
            conn.execute(text("create table hc__write_probe (id int)"))
            print("can CREATE TABLE: YES")
        except DBAPIError:
            print("can CREATE TABLE: no")
        finally:
            conn.rollback()  # undo the probe no matter what


if __name__ == "__main__":
    probe("READ-ONLY url (DATABASE_URL)", read_engine)
    probe("OWNER url (OWNER_DATABASE_URL)", owner_engine)
