from __future__ import annotations

from typing import Any, Dict, Optional

import psycopg


def insert_event(conn: psycopg.Connection, event: Dict[str, Any]) -> tuple[str, bool]:
    query = """
        INSERT INTO event_store (
          entity_type,
          entity_id,
          event_type,
          payload,
          source,
          created_at_reported,
          client_event_id,
          idempotency_key,
          correlation_id,
          causation_id,
          schema_version,
          created_by
        ) VALUES (
          %(entity_type)s,
          %(entity_id)s,
          %(event_type)s,
          %(payload)s,
          %(source)s,
          %(created_at_reported)s,
          %(client_event_id)s,
          %(idempotency_key)s,
          %(correlation_id)s,
          %(causation_id)s,
          %(schema_version)s,
          %(created_by)s
        )
        RETURNING event_id
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, event)
            event_id = cur.fetchone()["event_id"]
        return event_id, False
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        event_id = _fetch_existing_event_id(conn, event)
        return event_id, True


def _fetch_existing_event_id(conn: psycopg.Connection, event: Dict[str, Any]) -> str:
    if event.get("client_event_id"):
        query = """
            SELECT event_id FROM event_store
            WHERE entity_id = %(entity_id)s AND client_event_id = %(client_event_id)s
        """
        params = {"entity_id": event["entity_id"], "client_event_id": event["client_event_id"]}
    elif event.get("idempotency_key"):
        query = """
            SELECT event_id FROM event_store
            WHERE entity_id = %(entity_id)s AND idempotency_key = %(idempotency_key)s
        """
        params = {"entity_id": event["entity_id"], "idempotency_key": event["idempotency_key"]}
    else:
        raise ValueError("No idempotency key to resolve duplicate")
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    if not row:
        raise ValueError("Duplicate event detected but existing event_id not found")
    return row["event_id"]


def fetch_event_by_id(conn: psycopg.Connection, event_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM event_store WHERE event_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, (event_id,))
        row = cur.fetchone()
    return row
