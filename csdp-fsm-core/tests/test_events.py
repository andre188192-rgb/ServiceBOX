from datetime import datetime, timedelta, timezone

from src.domain.apply_event import apply_event
from src.domain.validator import Actor, validate_event
from src.storage import event_store_repo


def _submit_event(conn, envelope, actor):
    validation = validate_event(conn, envelope, actor)
    if validation.decision != "ACCEPTED":
        return validation
    normalized = validation.normalized_event or envelope
    normalized["created_by"] = actor.actor_id
    event_id, duplicate = event_store_repo.insert_event(conn, normalized)
    if duplicate:
        return {
            "decision": "ACCEPTED",
            "reason_code": "DUPLICATE_IGNORED",
            "event_id": event_id,
        }
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


def _fetch_projection(conn, work_order_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM work_orders_current WHERE work_order_id = %s", (work_order_id,))
        return cur.fetchone()


def test_full_lifecycle_accept(db_conn):
    actor = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000001"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000010",
        "asset_id": "00000000-0000-0000-0000-000000000020",
        "priority": "CRITICAL",
        "type": "EMERGENCY_REPAIR",
        "description": "Alarm",
    }
    assert _submit_event(db_conn, created, actor)["decision"] == "ACCEPTED"

    assigned = _base_envelope("WORK_ORDER.ASSIGNED", work_order_id)
    assigned["payload"] = {
        "engineer_id": "00000000-0000-0000-0000-000000000030",
        "scheduled_start": datetime.now(timezone.utc).isoformat(),
        "scheduled_end": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    assert _submit_event(db_conn, assigned, actor)["decision"] == "ACCEPTED"

    started = _base_envelope("WORK.STARTED", work_order_id)
    started["payload"] = {"actual_start_reported": datetime.now(timezone.utc).isoformat()}
    assert _submit_event(
        db_conn,
        started,
        Actor(role="ENGINEER", actor_id="00000000-0000-0000-0000-000000000030"),
    )["decision"] == "ACCEPTED"

    paused = _base_envelope("WORK.PAUSED", work_order_id)
    paused["payload"] = {"reason_code": "PARTS"}
    assert _submit_event(
        db_conn,
        paused,
        Actor(role="ENGINEER", actor_id="00000000-0000-0000-0000-000000000030"),
    )["decision"] == "ACCEPTED"

    resumed = _base_envelope("WORK.RESUMED", work_order_id)
    resumed["payload"] = {"comment": "ok"}
    assert _submit_event(
        db_conn,
        resumed,
        Actor(role="ENGINEER", actor_id="00000000-0000-0000-0000-000000000030"),
    )["decision"] == "ACCEPTED"

    completed = _base_envelope("WORK.COMPLETED", work_order_id)
    completed["payload"] = {"work_summary": "done"}
    assert _submit_event(
        db_conn,
        completed,
        Actor(role="ENGINEER", actor_id="00000000-0000-0000-0000-000000000030"),
    )["decision"] == "ACCEPTED"

    closed = _base_envelope("WORK_ORDER.CLOSED", work_order_id)
    assert _submit_event(db_conn, closed, Actor(role="DISPATCHER", actor_id=None))["decision"] == "ACCEPTED"


def test_cancel_transition(db_conn):
    dispatcher = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000015"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000016",
        "asset_id": "00000000-0000-0000-0000-000000000017",
        "priority": "LOW",
        "type": "MAINTENANCE",
        "description": "test",
    }
    _submit_event(db_conn, created, dispatcher)

    cancelled = _base_envelope("WORK_ORDER.CANCELLED", work_order_id)
    cancelled["payload"] = {"reason_code": "CLIENT_REQUEST"}
    assert _submit_event(db_conn, cancelled, dispatcher)["decision"] == "ACCEPTED"

    projection = _fetch_projection(db_conn, work_order_id)
    assert projection["business_state"] == "CANCELLED"


def test_invalid_transition_close_from_planned(db_conn):
    actor = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000101"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000110",
        "asset_id": "00000000-0000-0000-0000-000000000120",
        "priority": "HIGH",
        "type": "MAINTENANCE",
        "description": "test",
    }
    _submit_event(db_conn, created, actor)

    assigned = _base_envelope("WORK_ORDER.ASSIGNED", work_order_id)
    assigned["payload"] = {
        "engineer_id": "00000000-0000-0000-0000-000000000130",
        "scheduled_start": datetime.now(timezone.utc).isoformat(),
        "scheduled_end": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    _submit_event(db_conn, assigned, actor)

    closed = _base_envelope("WORK_ORDER.CLOSED", work_order_id)
    validation = validate_event(db_conn, closed, actor)
    assert validation.decision == "REJECTED"
    assert validation.reason_code == "ERR_INVALID_TRANSITION"


def test_execution_transitions(db_conn):
    dispatcher = Actor(role="DISPATCHER", actor_id=None)
    engineer_id = "00000000-0000-0000-0000-000000000050"
    work_order_id = "00000000-0000-0000-0000-000000000051"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000052",
        "asset_id": "00000000-0000-0000-0000-000000000053",
        "priority": "LOW",
        "type": "MAINTENANCE",
        "description": "test",
    }
    _submit_event(db_conn, created, dispatcher)

    assigned = _base_envelope("WORK_ORDER.ASSIGNED", work_order_id)
    assigned["payload"] = {
        "engineer_id": engineer_id,
        "scheduled_start": datetime.now(timezone.utc).isoformat(),
        "scheduled_end": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    _submit_event(db_conn, assigned, dispatcher)

    dispatched = _base_envelope("WORK.DISPATCHED", work_order_id)
    _submit_event(db_conn, dispatched, dispatcher)
    projection = _fetch_projection(db_conn, work_order_id)
    assert projection["execution_state"] == "TRAVEL"

    arrived = _base_envelope("WORK.ARRIVED_ON_SITE", work_order_id)
    _submit_event(db_conn, arrived, Actor(role="ENGINEER", actor_id=engineer_id))
    projection = _fetch_projection(db_conn, work_order_id)
    assert projection["execution_state"] == "WORK"

    paused = _base_envelope("WORK.PAUSED", work_order_id)
    paused["payload"] = {"reason_code": "PARTS"}
    _submit_event(db_conn, paused, Actor(role="ENGINEER", actor_id=engineer_id))
    projection = _fetch_projection(db_conn, work_order_id)
    assert projection["business_state"] == "ON_HOLD"
    assert projection["execution_state"] == "WAITING_PARTS"

    resumed = _base_envelope("WORK.RESUMED", work_order_id)
    resumed["payload"] = {"comment": "ok"}
    _submit_event(db_conn, resumed, Actor(role="ENGINEER", actor_id=engineer_id))
    projection = _fetch_projection(db_conn, work_order_id)
    assert projection["business_state"] == "IN_PROGRESS"
    assert projection["execution_state"] == "WORK"


def test_rbac_engineer_other_work_order(db_conn):
    dispatcher = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000201"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000210",
        "asset_id": "00000000-0000-0000-0000-000000000220",
        "priority": "LOW",
        "type": "TRAINING",
        "description": "test",
    }
    _submit_event(db_conn, created, dispatcher)

    assigned = _base_envelope("WORK_ORDER.ASSIGNED", work_order_id)
    assigned["payload"] = {
        "engineer_id": "00000000-0000-0000-0000-000000000230",
        "scheduled_start": datetime.now(timezone.utc).isoformat(),
        "scheduled_end": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    _submit_event(db_conn, assigned, dispatcher)

    started = _base_envelope("WORK.STARTED", work_order_id)
    validation = validate_event(
        db_conn,
        started,
        Actor(role="ENGINEER", actor_id="00000000-0000-0000-0000-000000000231"),
    )
    assert validation.decision == "REJECTED"
    assert validation.reason_code == "ERR_RBAC_DENIED"


def test_idempotency_duplicate_client_event_id(db_conn):
    actor = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000301"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["client_event_id"] = "client-1234"
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000310",
        "asset_id": "00000000-0000-0000-0000-000000000320",
        "priority": "MEDIUM",
        "type": "MAINTENANCE",
        "description": "test",
    }
    first = _submit_event(db_conn, created, actor)
    second = _submit_event(db_conn, created, actor)
    assert first["decision"] == "ACCEPTED"
    assert second["decision"] == "ACCEPTED"
    assert second["reason_code"] == "DUPLICATE_IGNORED"


def test_time_policy_drift_mobile(db_conn):
    actor = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000401"
    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["source"] = "mobile"
    created["created_at_reported"] = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000410",
        "asset_id": "00000000-0000-0000-0000-000000000420",
        "priority": "LOW",
        "type": "MAINTENANCE",
        "description": "test",
    }
    result = validate_event(db_conn, created, actor)
    assert result.decision == "NEEDS_REVIEW"
    assert result.reason_code == "REV_AMBIGUOUS_TIME"


def test_sla_deadlines_set_on_created(db_conn):
    dispatcher = Actor(role="DISPATCHER", actor_id=None)
    work_order_id = "00000000-0000-0000-0000-000000000430"

    created = _base_envelope("WORK_ORDER.CREATED", work_order_id)
    created["payload"] = {
        "client_id": "00000000-0000-0000-0000-000000000431",
        "asset_id": "00000000-0000-0000-0000-000000000432",
        "priority": "HIGH",
        "type": "MAINTENANCE",
        "description": "test",
    }
    _submit_event(db_conn, created, dispatcher)

    with db_conn.cursor() as cur:
        cur.execute(
            "SEL
