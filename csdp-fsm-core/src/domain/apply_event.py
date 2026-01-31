from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import psycopg


def apply_event(conn: psycopg.Connection, event: Dict[str, Any]) -> None:
    event_type = event["event_type"]
    payload = event["payload"]
    work_order_id = event["entity_id"]
    effective_time = event.get("effective_time")
    event_id = event["event_id"]
    created_by = event.get("created_by")

    projection = _fetch_projection(conn, work_order_id)

    if event_type == "WORK_ORDER.CREATED":
        _insert_work_order(conn, event, payload)
        projection = _fetch_projection(conn, work_order_id)
        if projection:
            _ensure_sla_deadlines(conn, projection, event)

    elif event_type == "WORK_ORDER.ASSIGNED":
        _update_projection(
            conn,
            work_order_id,
            {
                "last_event_id": event_id,
                "assigned_engineer_id": payload.get("engineer_id"),
                "assigned_team_id": payload.get("team_id"),
                "scheduled_start": payload.get("scheduled_start"),
                "scheduled_end": payload.get("scheduled_end"),
                "business_state": "PLANNED",
            },
        )
        projection = _fetch_projection(conn, work_order_id)
        if projection:
            _ensure_sla_deadlines(conn, projection, event)

    elif event_type == "WORK.DISPATCHED":
        if projection and projection["execution_state"] == "NOT_STARTED":
            _update_projection(conn, work_order_id, {"execution_state": "TRAVEL", "last_event_id": event_id})

    elif event_type == "WORK.ARRIVED_ON_SITE":
        # arrival makes sense only from TRAVEL
        if projection and projection["execution_state"] == "TRAVEL":
            _update_projection(conn, work_order_id, {"execution_state": "WORK", "last_event_id": event_id})

    elif event_type == "WORK.STARTED":
        updates = {
            "last_event_id": event_id,
            "business_state": "IN_PROGRESS",
            "actual_start_reported": payload.get("actual_start_reported") or event.get("created_at_reported"),
            "actual_start_effective": effective_time,
        }
        if projection and projection["execution_state"] in {"NOT_STARTED", "TRAVEL"}:
            updates["execution_state"] = "WORK"
        _update_projection(conn, work_order_id, updates)
        projection = _fetch_projection(conn, work_order_id)
        if projection:
            _apply_reaction_deadline(conn, projection, effective_time)

    elif event_type == "WORK.PAUSED":
        reason = payload.get("reason_code")
        updates = {"business_state": "ON_HOLD", "last_event_id": event_id}

        # execution_state flips only from WORK
        if projection and projection.get("execution_state") == "WORK":
            if reason == "PARTS":
                updates["execution_state"] = "WAITING_PARTS"
            elif reason == "CLIENT":
                updates["execution_state"] = "WAITING_CLIENT"
            # else: keep execution_state=WORK

        _update_projection(conn, work_order_id, updates)

    elif event_type == "WORK.RESUMED":
        _update_projection(
            conn,
            work_order_id,
            {"business_state": "IN_PROGRESS", "execution_state": "WORK", "last_event_id": event_id},
        )

    elif event_type == "WORK.COMPLETED":
        updates = {
            "last_event_id": event_id,
            "business_state": "COMPLETED",
            "execution_state": "FINISHED",
            "actual_end_reported": payload.get("actual_end_reported") or event.get("created_at_reported"),
            "actual_end_effective": effective_time,
        }
        if projection and projection.get("actual_start_effective") and effective_time:
            start = projection["actual_start_effective"]
            if isinstance(start, str):
                start = datetime.fromisoformat(start.replace("Z", "+00:00"))

            eff = effective_time
            if isinstance(eff, str):
                eff = datetime.fromisoformat(eff.replace("Z", "+00:00"))

            diff = eff - start
            updates["downtime_minutes"] = int(diff.total_seconds() // 60)

        _update_projection(conn, work_order_id, updates)
        projection = _fetch_projection(conn, work_order_id)
        if projection:
            _apply_restore_deadline(conn, projection, effective_time)

    elif event_type == "WORK_ORDER.CLOSED":
        _update_projection(conn, work_order_id, {"business_state": "CLOSED", "last_event_id": event_id})

    elif event_type == "WORK_ORDER.CANCELLED":
        _update_projection(conn, work_order_id, {"business_state": "CANCELLED", "last_event_id": event_id})

    elif event_type.startswith("SLA."):
        sla_state = _sla_state_from_event(event_type)
        _update_projection(conn, work_order_id, {"sla_state": sla_state, "last_event_id": event_id})
        _upsert_sla_view(conn, work_order_id, sla_state)

    if event_type.startswith("PART."):
        _apply_parts(conn, work_order_id, payload, event_type)

    if event_type.startswith("EVIDENCE."):
        _insert_evidence(conn, work_order_id, payload, event_type, created_by)

    _insert_timeline(conn, work_order_id, event_id, event_type, payload, created_by)

    projection = _fetch_projection(conn, work_order_id)
    if projection and projection.get("assigned_engineer_id"):
        _update_engineer_board(conn, projection)


def _fetch_projection(conn: psycopg.Connection, work_order_id: str) -> Dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM work_orders_current WHERE work_order_id = %s", (work_order_id,))
        return cur.fetchone()


def _insert_work_order(conn: psycopg.Connection, event: Dict[str, Any], payload: Dict[str, Any]) -> None:
    query = """
        INSERT INTO work_orders_current (
          work_order_id,
          client_id,
          asset_id,
          priority,
          work_type,
          business_state,
          execution_state,
          sla_state,
          last_event_id,
          last_event_at,
          version
        ) VALUES (
          %(work_order_id)s,
          %(client_id)s,
          %(asset_id)s,
          %(priority)s,
          %(work_type)s,
          'NEW',
          'NOT_STARTED',
          'IN_SLA',
          %(last_event_id)s,
          now(),
          1
        )
    """
    with conn.cursor() as cur:
        cur.execute(
            query,
            {
                "work_order_id": event["entity_id"],
                "client_id": payload["client_id"],
                "asset_id": payload["asset_id"],
                "priority": payload["priority"],
                "work_type": payload["type"],
                "last_event_id": event["event_id"],
            },
        )


def _update_projection(conn: psycopg.Connection, work_order_id: str, updates: Dict[str, Any]) -> None:
    updates["last_event_at"] = datetime.now(timezone.utc)
    set_clause = ", ".join([f"{key} = %({key})s" for key in updates.keys()])
    query = f"""
        UPDATE work_orders_current
        SET {set_clause},
            version = version + 1
        WHERE work_order_id = %(work_order_id)s
    """
    updates["work_order_id"] = work_order_id
    with conn.cursor() as cur:
        cur.execute(query, updates)


def _insert_timeline(
    conn: psycopg.Connection,
    work_order_id: str,
    event_id: str,
    event_type: str,
    payload: Dict[str, Any],
    created_by: str | None,
) -> None:
    query = """
        INSERT INTO work_order_timeline (
          work_order_id,
          event_id,
          event_type,
          created_at_system,
          created_by,
          payload
        ) VALUES (%s, %s, %s, now(), %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id, event_id, event_type, created_by, payload))


def _apply_parts(conn: psycopg.Connection, work_order_id: str, payload: Dict[str, Any], event_type: str) -> None:
    qty_field = {
        "PART.RESERVED": "reserved_qty",
        "PART.INSTALLED": "installed_qty",
        "PART.CONSUMED": "consumed_qty",
    }[event_type]
    query = f"""
        INSERT INTO work_order_parts (work_order_id, part_id, {qty_field}, last_event_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (work_order_id, part_id)
        DO UPDATE SET {qty_field} = work_order_parts.{qty_field} + EXCLUDED.{qty_field},
                      last_event_at = now()
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id, payload["part_id"], payload["quantity"]))


def _insert_evidence(
    conn: psycopg.Connection,
    work_order_id: str,
    payload: Dict[str, Any],
    event_type: str,
    created_by: str | None,
) -> None:
    evidence_type = {
        "EVIDENCE.PHOTO_ADDED": "PHOTO",
        "EVIDENCE.DOCUMENT_ADDED": "DOCUMENT",
        "EVIDENCE.SIGNATURE_CAPTURED": "SIGNATURE",
    }[event_type]
    meta = payload.copy()
    url = meta.pop("url", None) or meta.pop("signature_url", None)
    query = """
        INSERT INTO work_order_evidence (work_order_id, evidence_type, url, meta, created_by)
        VALUES (%s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id, evidence_type, url, meta, created_by))


def _update_engineer_board(conn: psycopg.Connection, projection: Dict[str, Any]) -> None:
    engineer_id = projection["assigned_engineer_id"]
    status = _map_engineer_status(projection["execution_state"])
    query = """
        INSERT INTO engineer_board (engineer_id, status, current_work_order_id, last_seen_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (engineer_id)
        DO UPDATE SET status = EXCLUDED.status,
                      current_work_order_id = EXCLUDED.current_work_order_id,
                      last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        cur.execute(query, (engineer_id, status, projection["work_order_id"]))


def _map_engineer_status(execution_state: str) -> str:
    if execution_state == "TRAVEL":
        return "TRAVEL"
    if execution_state in {"WORK", "WAITING_PARTS", "WAITING_CLIENT"}:
        return "WORK"
    if execution_state == "FINISHED":
        return "AVAILABLE"
    return "AVAILABLE"


def _sla_state_from_event(event_type: str) -> str:
    return {
        "SLA.AT_RISK": "AT_RISK",
        "SLA.RECOVERED": "IN_SLA",
        "SLA.BREACHED": "BREACHED",
        "SLA.BREACH_ACCEPTED": "ACCEPTED_BREACH",
    }[event_type]


def _ensure_sla_deadlines(conn: psycopg.Connection, projection: Dict[str, Any], event: Dict[str, Any]) -> None:
    priority = projection["priority"]
    reaction_delta, restore_delta = _sla_durations(priority)

    # Base SLA deadlines on scheduled_start if provided, otherwise created_at_system.
    base = projection.get("scheduled_start") or event.get("created_at_system")
    if isinstance(base, str):
        base = datetime.fromisoformat(base.replace("Z", "+00:00"))
    if base is None:
        base = datetime.now(timezone.utc)

    reaction_deadline = base + reaction_delta
    restore_deadline = base + restore_delta

    query = """
        INSERT INTO sla_view (work_order_id, reaction_deadline_at, restore_deadline_at, state, last_calc_at)
        VALUES (%s, %s, %s, 'IN_SLA', now())
        ON CONFLICT (work_order_id)
        DO UPDATE SET reaction_deadline_at = COALESCE(sla_view.reaction_deadline_at, EXCLUDED.reaction_deadline_at),
                      restore_deadline_at = COALESCE(sla_view.restore_deadline_at, EXCLUDED.restore_deadline_at),
                      last_calc_at = EXCLUDED.last_calc_at
    """
    with conn.cursor() as cur:
        cur.execute(query, (projection["work_order_id"], reaction_deadline, restore_deadline))


def _apply_reaction_deadline(conn: psycopg.Connection, projection: Dict[str, Any], effective_time: Any) -> None:
    if effective_time is None:
        return
    if isinstance(effective_time, str):
        effective_time = datetime.fromisoformat(effective_time.replace("Z", "+00:00"))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT reaction_deadline_at FROM sla_view WHERE work_order_id = %s",
            (projection["work_order_id"],),
        )
        row = cur.fetchone()

    if not row or row["reaction_deadline_at"] is None:
        return

    deadline = row["reaction_deadline_at"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))

    if effective_time > deadline:
        _mark_sla_breached(conn, projection["work_order_id"])


def _apply_restore_deadline(conn: psycopg.Connection, projection: Dict[str, Any], effective_time: Any) -> None:
    if effective_time is None:
        return
    if isinstance(effective_time, str):
        effective_time = datetime.fromisoformat(effective_time.replace("Z", "+00:00"))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT restore_deadline_at FROM sla_view WHERE work_order_id = %s",
            (projection["work_order_id"],),
        )
        row = cur.fetchone()

    if not row or row["restore_deadline_at"] is None:
        return

    deadline = row["restore_deadline_at"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))

    if effective_time > deadline:
        _mark_sla_breached(conn, projection["work_order_id"])


def _mark_sla_breached(conn: psycopg.Connection, work_order_id: str) -> None:
    query = """
        UPDATE sla_view
        SET state = 'BREACHED',
            breached_at = COALESCE(breached_at, now()),
            last_calc_at = now()
        WHERE work_order_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id,))


def _sla_durations(priority: str) -> tuple[timedelta, timedelta]:
    mapping = {
        "CRITICAL": (timedelta(hours=2), timedelta(hours=8)),
        "HIGH": (timedelta(hours=4), timedelta(hours=16)),
        "MEDIUM": (timedelta(hours=8), timedelta(hours=48)),
        "LOW": (timedelta(hours=8), timedelta(hours=72)),
    }
    return mapping.get(priority, (timedelta(hours=8), timedelta(hours=72)))


def _upsert_sla_view(conn: psycopg.Connection, work_order_id: str, state: str) -> None:
    query = """
        INSERT INTO sla_view (work_order_id, state, last_calc_at)
        VALUES (%s, %s, now())
        ON CONFLICT (work_order_id)
        DO UPDATE SET state = EXCLUDED.state,
                      last_calc_at = EXCLUDED.last_calc_at
    """
    with conn.cursor() as cur:
        cur.execute(query, (work_order_id, state))
