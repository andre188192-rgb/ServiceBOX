from __future__ import annotations

from typing import Any, Dict, List, Optional

import psycopg


def fetch_work_order(conn: psycopg.Connection, work_order_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM work_orders_current WHERE work_order_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id,))
        return cur.fetchone()


def list_work_orders(
    conn: psycopg.Connection,
    business_state: Optional[str],
    assigned_engineer_id: Optional[str],
    asset_id: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> List[Dict[str, Any]]:
    clauses = []
    params: Dict[str, Any] = {}
    if business_state:
        clauses.append("business_state = %(business_state)s")
        params["business_state"] = business_state
    if assigned_engineer_id:
        clauses.append("assigned_engineer_id = %(assigned_engineer_id)s")
        params["assigned_engineer_id"] = assigned_engineer_id
    if asset_id:
        clauses.append("asset_id = %(asset_id)s")
        params["asset_id"] = asset_id
    if cursor:
        clauses.append("work_order_id > %(cursor)s")
        params["cursor"] = cursor
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"""
        SELECT * FROM work_orders_current
        {where}
        ORDER BY work_order_id
        LIMIT %(limit)s
    """
    params["limit"] = limit
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_timeline(conn: psycopg.Connection, work_order_id: str, limit: int) -> List[Dict[str, Any]]:
    query = """
        SELECT event_id, event_type, created_at_system, created_by, payload
        FROM work_order_timeline
        WHERE work_order_id = %s
        ORDER BY created_at_system
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id, limit))
        return cur.fetchall()


def fetch_parts(conn: psycopg.Connection, work_order_id: str) -> List[Dict[str, Any]]:
    query = """
        SELECT part_id, reserved_qty, installed_qty, consumed_qty, last_event_at
        FROM work_order_parts
        WHERE work_order_id = %s
        ORDER BY part_id
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id,))
        return cur.fetchall()


def fetch_evidence(conn: psycopg.Connection, work_order_id: str) -> List[Dict[str, Any]]:
    query = """
        SELECT evidence_id, evidence_type, url, meta, created_at, created_by
        FROM work_order_evidence
        WHERE work_order_id = %s
        ORDER BY created_at
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id,))
        return cur.fetchall()


def fetch_engineer_board(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    query = "SELECT * FROM engineer_board ORDER BY engineer_id"
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def fetch_sla_view(conn: psycopg.Connection, work_order_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM sla_view WHERE work_order_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id,))
        return cur.fetchone()


def list_ref_catalog(conn: psycopg.Connection, catalog: str, active_only: bool) -> List[Dict[str, Any]]:
    if active_only:
        query = """
            SELECT code, title, description, is_active, sort_order, meta
            FROM ref_catalog_items
            WHERE catalog = %s AND is_active = TRUE
            ORDER BY sort_order, code
        """
    else:
        query = """
            SELECT code, title, description, is_active, sort_order, meta
            FROM ref_catalog_items
            WHERE catalog = %s
            ORDER BY sort_order, code
        """
    with conn.cursor() as cur:
        cur.execute(query, (catalog,))
        return cur.fetchall()


def ref_code_exists(conn: psycopg.Connection, catalog: str, code: str) -> bool:
    query = """
        SELECT 1 FROM ref_catalog_items
        WHERE catalog = %s AND code = %s AND is_active = TRUE
    """
    with conn.cursor() as cur:
        cur.execute(query, (catalog, code))
        return cur.fetchone() is not None
