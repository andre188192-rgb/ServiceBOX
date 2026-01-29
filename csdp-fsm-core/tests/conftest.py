import os
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def _db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/csdp_fsm_test"))


def _apply_migrations(conn: psycopg.Connection) -> None:
    migrations_dir = ROOT / "migrations"
    for name in ["001_event_store.sql", "002_projections.sql", "003_add_missing_tables.sql"]:
        sql = (migrations_dir / name).read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)


@pytest.fixture()
def db_conn():
    conn = psycopg.connect(_db_url(), row_factory=dict_row)
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute("GRANT ALL ON SCHEMA public TO public")
    _apply_migrations(conn)
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()
