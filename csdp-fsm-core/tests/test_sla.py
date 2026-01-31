from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.domain.apply_event import apply_event
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


def test_contract_deadlines_set(db_conn):
    _apply_migration(db_conn, "003_contracts.sql")
    now = datetime.now(timezone.utc)
    client_id = "00000000-0000-0000-0000-000000001100"
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO contracts (client_id, contract_type, active_from, reaction_minutes, restore_minutes, is_active)
            VALUES (%s, 'FULL_SERVICE', %s, 30, 120, TRUE)
            RETURNING contract_id
            """,
            (client_id, now - timedelta(days=1)),
        )
        contract_id = cur.fetchone()["contract_id"]

    work_order_id = "00000000-0000-0000-0000-000000001101"
    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": client_id,
        "asset_id": "00000000-0000-0000-0000-000000001102",
        "priority": "HIGH",
        "type": "MAINTENANCE",
        "description": "test",
        "contract_id": str(contract_id),
    }
    result = _submit_event(db_conn, created, Actor(role="DISPATCHER", actor_id=None))
    assert result["decision"] == "ACCEPTED"

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT reaction_deadline_at, restore_deadline_at FROM sla_view WHERE work_order_id = %s",
            (work_order_id,),
        )
        row = cur.fetchone()
    assert row["reaction_deadline_at"] is not None
    assert row["restore_deadline_at"] is not None


def test_missing_contract_deadlines_null(db_conn):
    _apply_migration(db_conn, "003_contracts.sql")
    work_order_id = "00000000-0000-0000-0000-000000001111"
    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000001112",
        "asset_id": "00000000-0000-0000-0000-000000001113",
        "priority": "LOW",
        "type": "MAINTENANCE",
        "description": "test",
    }
    result = _submit_event(db_conn, created, Actor(role="DISPATCHER", actor_id=None))
    assert result["decision"] == "ACCEPTED"

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT reaction_deadline_at, restore_deadline_at FROM sla_view WHERE work_order_id = %s",
            (work_order_id,),
        )
        row = cur.fetchone()
    assert row["reaction_deadline_at"] is None
    assert row["restore_deadline_at"] is None


def test_breach_on_late_start_uses_effective_time(db_conn):
    _apply_migration(db_conn, "003_contracts.sql")
    now = datetime.now(timezone.utc)
    client_id = "00000000-0000-0000-0000-000000001120"
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO contracts (client_id, contract_type, active_from, reaction_minutes, restore_minutes, is_active)
            VALUES (%s, 'BASIC_SUPPORT', %s, 0, 60, TRUE)
            RETURNING contract_id
            """,
            (client_id, now - timedelta(days=1)),
        )
        contract_id = cur.fetchone()["contract_id"]

    work_order_id = "00000000-0000-0000-0000-000000001121"
    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": client_id,
        "asset_id": "00000000-0000-0000-0000-000000001122",
        "priority": "LOW",
        "type": "MAINTENANCE",
        "description": "test",
        "contract_id": str(contract_id),
    }
    _submit_event(db_conn, created, Actor(role="DISPATCHER", actor_id=None))

    assigned = _base_envelope("WORK_ORDER.ASSIGNED", work_order_id)
    assigned["payload"] = {
        "engineer_id": "00000000-0000-0000-0000-000000001123",
        "scheduled_start": now.isoformat(),
        "scheduled_end": (now + timedelta(hours=1)).isoformat(),
    }
    _submit_event(db_conn, assigned, Actor(role="DISPATCHER", actor_id=None))

    started = _base_envelope("WORK.STARTED", work_order_id)
    started["payload"] = {"actual_start_reported": now.isoformat()}
    _submit_event(db_conn, started, Actor(role="ENGINEER", actor_id="00000000-0000-0000-0000-000000001123"))

    with db_conn.cursor() as cur:
        cur.execute("SELECT state FROM sla_view WHERE work_order_id = %s", (work_order_id,))
        row = cur.fetchone()
    assert row["state"] == "BREACHED"
