from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import psycopg


def rebuild_kpi_daily(conn: psycopg.Connection, date_from: date, date_to: date) -> None:
    _clear_range(conn, date_from, date_to)
    events = _fetch_events(conn, date_from, date_to)
    work_orders = _build_work_order_metrics(events)
    _insert_kpi_rows(conn, work_orders)


def _clear_range(conn: psycopg.Connection, date_from: date, date_to: date) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM kpi_daily WHERE day >= %s AND day <= %s",
            (date_from, date_to),
        )


def _fetch_events(conn: psycopg.Connection, date_from: date, date_to: date) -> List[Dict[str, Any]]:
    query = """
        SELECT event_type, entity_id, payload, created_at_system, created_at_reported
        FROM event_store
        WHERE created_at_system::date >= %s AND created_at_system::date <= %s
          AND event_type IN (
            'WORK_ORDER.CREATED',
            'WORK.STARTED',
            'WORK.COMPLETED'
          )
        ORDER BY created_at_system
    """
    with conn.cursor() as cur:
        cur.execute(query, (date_from, date_to))
        return cur.fetchall()


def _effective_time(event_type: str, payload: Dict[str, Any], created_at_reported: Optional[datetime], created_at_system: datetime) -> datetime:
    if event_type == "WORK.STARTED":
        return _parse_time(payload.get("actual_start_reported")) or created_at_reported or created_at_system
    if event_type == "WORK.COMPLETED":
        return _parse_time(payload.get("actual_end_reported")) or created_at_reported or created_at_system
    return created_at_reported or created_at_system


def _build_work_order_metrics(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    per_work_order: Dict[str, Dict[str, Any]] = {}
    for event in events:
        event_type = event["event_type"]
        work_order_id = event["entity_id"]
        payload = event["payload"]
        created_at_system = event["created_at_system"]
        created_at_reported = event["created_at_reported"]
        record = per_work_order.setdefault(
            work_order_id,
            {
                "work_order_id": work_order_id,
                "created_time": None,
                "started_time": None,
                "completed_time": None,
                "client_id": None,
                "day": created_at_system.date(),
            },
        )
        if event_type == "WORK_ORDER.CREATED":
            record["created_time"] = _effective_time(event_type, payload, created_at_reported, created_at_system)
            record["client_id"] = payload.get("client_id")
            record["day"] = created_at_system.date()
        elif event_type == "WORK.STARTED":
            record["started_time"] = _effective_time(event_type, payload, created_at_reported, created_at_system)
        elif event_type == "WORK.COMPLETED":
            record["completed_time"] = _effective_time(event_type, payload, created_at_reported, created_at_system)
    return list(per_work_order.values())


def _insert_kpi_rows(conn: psycopg.Connection, work_orders: List[Dict[str, Any]]) -> None:
    aggregates: Dict[Tuple[date, Optional[str]], Dict[str, Any]] = {}
    for record in work_orders:
        day = record["day"]
        client_id = record["client_id"]
        key = (day, client_id)
        agg = aggregates.setdefault(
            key,
            {
                "reaction_sum": 0.0,
                "reaction_count": 0,
                "mttr_sum": 0.0,
                "mttr_count": 0,
                "work_orders": 0,
            },
        )
        agg["work_orders"] += 1
        if record["created_time"] and record["started_time"]:
            diff = record["started_time"] - record["created_time"]
            agg["reaction_sum"] += diff.total_seconds() / 60.0
            agg["reaction_count"] += 1
        if record["started_time"] and record["completed_time"]:
            diff = record["completed_time"] - record["started_time"]
            agg["mttr_sum"] += diff.total_seconds() / 60.0
            agg["mttr_count"] += 1

    sla_states = _fetch_sla_states(conn, work_orders)

    rows = []
    for (day, client_id), agg in aggregates.items():
        reaction_avg = agg["reaction_sum"] / agg["reaction_count"] if agg["reaction_count"] else None
        mttr_avg = agg["mttr_sum"] / agg["mttr_count"] if agg["mttr_count"] else None
        sla_percent = _calc_sla_percent(sla_states.get((day, client_id), []))
        rows.append((day, client_id, reaction_avg, mttr_avg, sla_percent, agg["work_orders"]))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO kpi_daily (day, client_id, reaction_avg_minutes, mttr_avg_minutes, sla_compliance_percent, work_orders_total)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            rows,
        )


def _fetch_sla_states(conn: psycopg.Connection, work_orders: List[Dict[str, Any]]) -> Dict[Tuple[date, Optional[str]], List[str]]:
    ids = [wo_id for wo_id in {w.get("work_order_id") for w in work_orders} if wo_id]
    if not ids:
        return {}
    query = "SELECT work_order_id, state FROM sla_view WHERE work_order_id = ANY(%s)"
    with conn.cursor() as cur:
        cur.execute(query, (ids,))
        rows = cur.fetchall()
    states_by_id = {row["work_order_id"]: row.get("state") for row in rows}
    states: Dict[Tuple[date, Optional[str]], List[str]] = {}
    for record in work_orders:
        key = (record["day"], record["client_id"])
        states.setdefault(key, []).append(states_by_id.get(record.get("work_order_id")))
    return states


def _calc_sla_percent(states: List[Optional[str]]) -> Optional[float]:
    if not states:
        return None
    total = len(states)
    compliant = sum(1 for state in states if state and state != "BREACHED")
    return (compliant / total) * 100.0


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
