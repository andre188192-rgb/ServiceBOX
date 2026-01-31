from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.domain.apply_event import apply_event
from src.domain.kpi import rebuild_kpi_daily
from src.domain.validator import Actor, validate_event
from src.storage import event_store_repo


def _apply_migration(conn, name: str) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    sql = (migrations_dir / name).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def _submit_event(conn, envelope, actor):
    validation = validate_event(conn, envelope, actor)
    if validation.decision != "ACCEPTED":
        return validation
    normalized = validation.normalized_event or envelope
    normalized["created_by"] = actor.actor_id
    event_id, duplicate = event_store_repo.insert_event(conn, normalized)
    if duplicate:
        return {"decision": "ACCEPTED", "reason_code": "DUPLICATE_IGNORED", "event_id": event_id}
    stored = event_store_repo.fetch_event_by_id(conn, event_id)
    normalized["event_id"] = event_id
    normalized["created_at_system"] = stored["created_at_system"]
    apply_event(conn, normalized)
    return {"decision": "ACCEPTED", "reason_code": "OK", "event_id": event_id}


def _base_envelope(event_type, entity_id):
    return {
        "event_type": event_type,
        "entity_type": "work_order",
        "entity_id": entity_id,
        "source": "web",
        "payload": {},
    }


def test_kpi_daily_averages(db_conn):
    _apply_migration(db_conn, "004_kpi.sql")

    now = datetime.now(timezone.utc)
    work_order_id = "00000000-0000-0000-0000-000000002001"
    engineer_id = "00000000-0000-0000-0000-000000002002"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["created_at_reported"] = (now - timedelta(hours=2)).isoformat()
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000002003",
        "asset_id": "00000000-0000-0000-0000-000000002004",
        "priority": "LOW",
        "type": "MAINTENANCE",
        "description": "test",
    }
    _submit_event(db_conn, created, Actor(role="DISPATCHER", actor_id=None))

    assigned = _base_envelope("WORK_ORDER.ASSIGNED", work_order_id)
    assigned["payload"] = {
        "engineer_id": engineer_id,
        "scheduled_start": now.isoformat(),
        "scheduled_end": (now + timedelta(hours=1)).isoformat(),
    }
    _submit_event(db_conn, assigned, Actor(role="DISPATCHER", actor_id=None))

    started = _base_envelope("WORK.STARTED", work_order_id)
    started["payload"] = {"actual_start_reported": (now - timedelta(hours=1)).isoformat()}
    _submit_event(db_conn, started, Actor(role="ENGINEER", actor_id=engineer_id))

    completed = _base_envelope("WORK.COMPLETED", work_order_id)
    completed["payload"] = {"work_summary": "done", "actual_end_reported": now.isoformat()}
    _submit_event(db_conn, completed, Actor(role="ENGINEER", actor_id=engineer_id))

    today = date.today()
    rebuild_kpi_daily(db_conn, today, today)

    with db_conn.cursor() as cur:
        cur.execute("SELECT reaction_avg_minutes, mttr_avg_minutes FROM kpi_daily WHERE day = %s AND client_id IS NULL", (today,))
        row = cur.fetchone()
    assert row is None

    with db_conn.cursor() as cur:
        cur.execute("SELECT reaction_avg_minutes, mttr_avg_minutes, work_orders_total FROM kpi_daily WHERE day = %s AND client_id = %s", (today, created["payload"]["client_id"]))
        row = cur.fetchone()
    assert row["work_orders_total"] == 1
    assert float(row["reaction_avg_minutes"]) == 60.0
    assert float(row["mttr_avg_minutes"]) == 60.0
