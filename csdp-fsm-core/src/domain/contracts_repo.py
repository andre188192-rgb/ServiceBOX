from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import psycopg


def get_contract_by_id(conn: psycopg.Connection, contract_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM contracts WHERE contract_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, (contract_id,))
        return cur.fetchone()


def get_active_contract_for_client(
    conn: psycopg.Connection, client_id: str, now_ts: datetime
) -> Optional[Dict[str, Any]]:
    query = """
        SELECT * FROM contracts
        WHERE client_id = %s
          AND is_active = TRUE
          AND active_from <= %s
          AND (active_to IS NULL OR active_to >= %s)
        ORDER BY active_from DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(query, (client_id, now_ts, now_ts))
        return cur.fetchone()
