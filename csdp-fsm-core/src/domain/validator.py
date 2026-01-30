from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jsonschema import Draft202012Validator

from src.storage import projections_repo

SCHEMAS_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "schemas")
)


@dataclass
class Actor:
    role: str
    actor_id: Optional[str]


@dataclass
class ValidationResult:
    decision: str
    reason_code: str
    normalized_event: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None


BUSINESS_TRANSITIONS = {
    "NEW": {
        "WORK_ORDER.ASSIGNED": "PLANNED",
        "WORK_ORDER.CANCELLED": "CANCELLED",
    },
    "PLANNED": {
        "WORK.STARTED": "IN_PROGRESS",
        "WORK.PAUSED": "ON_HOLD",
        "WORK_ORDER.CANCELLED": "CANCELLED",
    },
    "IN_PROGRESS": {
        "WORK.PAUSED": "ON_HOLD",
        "WORK.COMPLETED": "COMPLETED",
    },
    "ON_HOLD": {
        "WORK.RESUMED": "IN_PROGRESS",
    },
    "COMPLETED": {
        "WORK_ORDER.CLOSED": "CLOSED",
    },
}

# Execution FSM валидация здесь делается через "разрешенные события из состояния".
# Конкретный next-state (WAITING_PARTS/WAITING_CLIENT и т.п.) вычисляется в apply_event,
# т.к. зависит от payload.reason_code.
EXECUTION_ALLOWED = {
    "NOT_STARTED": {"WORK.DISPATCHED", "WORK.STARTED"},
    "TRAVEL": {"WORK.ARRIVED_ON_SITE", "WORK.STARTED"},
    "WORK": {"WORK.PAUSED", "WORK.COMPLETED"},
    "WAITING_PARTS": {"WORK.RESUMED"},
    "WAITING_CLIENT": {"WORK.RESUMED"},
    "FINISHED": set(),
}

SLA_TRANSITIONS = {
    "IN_SLA": {"SLA.AT_RISK": "AT_RISK", "SLA.BREACHED": "BREACHED"},
    "AT_RISK": {"SLA.RECOVERED": "IN_SLA", "SLA.BREACHED": "BREACHED"},
    "BREACHED": {"SLA.BREACH_ACCEPTED": "ACCEPTED_BREACH"},
}

ROLE_RULES = {
    "WORK_ORDER.CREATED": {"DISPATCHER", "ADMIN", "SYSTEM"},
    "WORK_ORDER.ASSIGNED": {"DISPATCHER", "SYSTEM", "ADMIN"},
    "WORK_ORDER.CANCELLED": {"DISPATCHER", "MANAGER", "ADMIN"},
    "WORK_ORDER.CLOSED": {"DISPATCHER", "ENGINEER", "MANAGER", "ADMIN", "SYSTEM"},
    "WORK.STARTED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "WORK.PAUSED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "WORK.RESUMED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "WORK.COMPLETED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "WORK.DISPATCHED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "WORK.ARRIVED_ON_SITE": {"ENGINEER", "DISPATCHER", "ADMIN"},
    # parts: строгая модель — reserved/consumed не для инженера
    "PART.RESERVED": {"DISPATCHER", "ADMIN", "SYSTEM"},
    "PART.INSTALLED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "PART.CONSUMED": {"DISPATCHER", "ADMIN", "SYSTEM"},
    "EVIDENCE.PHOTO_ADDED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "EVIDENCE.DOCUMENT_ADDED": {"ENGINEER", "DISPATCHER", "ADMIN"},
    "EVIDENCE.SIGNATURE_CAPTURED": {"ENGINEER", "DISPATCHER", "ADMIN"},
}


def validate_event(conn, envelope: Dict[str, Any], actor: Actor) -> ValidationResult:
    envelope_validator = _load_validator("event-envelope.schema.json")
    errors = sorted(envelope_validator.iter_errors(envelope), key=lambda e: e.path)
    if errors:
        return ValidationResult(
            "REJECTED",
            "ERR_PAYLOAD_MISSING",
            details={"errors": [e.message for e in errors]},
        )

    event_type = envelope["event_type"]

    try:
        payload_schema_path = _load_event_schema_path(event_type)
        payload_validator = _load_validator(payload_schema_path)
        payload_errors = sorted(payload_validator.iter_errors(envelope["payload"]), key=lambda e: e.path)
        if payload_errors:
            return ValidationResult(
                "REJECTED",
                "ERR_PAYLOAD_MISSING",
                details={"errors": [e.message for e in payload_errors]},
            )
    except ValueError as exc:
        return ValidationResult("REJECTED", "ERR_GUARD_FAILED", details={"error": str(exc)})

    # SLA-ивенты только сервером
    if event_type.startswith("SLA.") and envelope.get("source") != "system":
        return ValidationResult("REJECTED", "ERR_SLA_SERVER_ONLY")

    # RBAC по типу события
    if actor.role not in ROLE_RULES.get(event_type, {actor.role}):
        return ValidationResult("REJECTED", "ERR_RBAC_DENIED")

    # Текущее состояние по work_order
    projection = projections_repo.fetch_work_order(conn, envelope["entity_id"])

    # ENGINEER должен совпадать с assigned_engineer_id (если projection уже есть)
    if actor.role == "ENGINEER" and projection:
        assigned_engineer = projection.get("assigned_engineer_id")
        if not assigned_engineer or assigned_engineer != actor.actor_id:
            return ValidationResult("REJECTED", "ERR_RBAC_DENIED")

    # Все кроме CREATED требуют существующий work_order
    if event_type != "WORK_ORDER.CREATED" and projection is None:
        return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")

    # Политика времени
    time_result = _evaluate_time_policy(envelope, projection)
    if time_result.decision != "ACCEPTED":
        return time_result

    # Guards по справочникам
    if event_type == "WORK.PAUSED":
        if not projections_repo.ref_code_exists(conn, "WORK_PAUSE_REASON", envelope["payload"]["reason_code"]):
            return ValidationResult("REJECTED", "ERR_GUARD_FAILED")

    if event_type == "WORK_ORDER.CANCELLED":
        if not projections_repo.ref_code_exists(conn, "CANCEL_REASON", envelope["payload"]["reason_code"]):
            return ValidationResult("REJECTED", "ERR_GUARD_FAILED")

    if event_type == "WORK.COMPLETED":
        for catalog, key in (("SYMPTOM", "symptoms"), ("CAUSE", "causes"), ("ACTION", "actions")):
            values = envelope["payload"].get(key) or []
            for code in values:
                if not projections_repo.ref_code_exists(conn, catalog, code):
                    return ValidationResult("REJECTED", "ERR_GUARD_FAILED")

    # FSM переходы/инварианты
    transition_result = _validate_fsm(event_type, envelope, projection)
    if transition_result.decision != "ACCEPTED":
        return transition_result

    normalized_event = {
        **envelope,
        "effective_time": time_result.normalized_event["effective_time"],
    }
    return ValidationResult("ACCEPTED", "OK", normalized_event=normalized_event)


def _validate_fsm(event_type: str, envelope: Dict[str, Any], projection: Optional[Dict[str, Any]]) -> ValidationResult:
    # CREATE — единственное событие, допустимое без projection
    if event_type == "WORK_ORDER.CREATED":
        if projection is not None:
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        return ValidationResult("ACCEPTED", "OK", normalized_event=envelope)

    business_state = projection["business_state"]
    execution_state = projection["execution_state"]
    sla_state = projection["sla_state"]

    # Инварианты согласованности business_state и execution_state
    composite = _check_composite_guards(business_state, execution_state)
    if composite:
        return ValidationResult("REJECTED", "ERR_STATE_MISMATCH", details=composite)

    # SLA FSM
    if event_type.startswith("SLA."):
        if event_type not in SLA_TRANSITIONS.get(sla_state, {}):
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        return ValidationResult("ACCEPTED", "OK", normalized_event=envelope)

    # BUSINESS FSM
    if event_type in BUSINESS_TRANSITIONS.get(business_state, {}):
        # Дополнительные строгие условия (на случай расширений таблиц)
        if event_type == "WORK.STARTED" and business_state != "PLANNED":
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.PAUSED" and business_state not in {"PLANNED", "IN_PROGRESS"}:
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.RESUMED" and business_state != "ON_HOLD":
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.COMPLETED" and business_state != "IN_PROGRESS":
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        return ValidationResult("ACCEPTED", "OK", normalized_event=envelope)

    # EXECUTION FSM — допустимость execution-ивентов из execution_state
    if event_type in EXECUTION_ALLOWED.get(execution_state, set()):
        # Согласование execution события с business_state (композитные правила)
        if event_type in {"WORK.DISPATCHED", "WORK.ARRIVED_ON_SITE"} and business_state not in {"PLANNED", "IN_PROGRESS"}:
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.STARTED" and business_state != "PLANNED":
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.PAUSED" and business_state not in {"PLANNED", "IN_PROGRESS"}:
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.RESUMED" and business_state != "ON_HOLD":
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
        if event_type == "WORK.COMPLETED" and business_state != "IN_PROGRESS":
            return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")

        return ValidationResult("ACCEPTED", "OK", normalized_event=envelope)

    # Финальные инварианты (в дополнение к таблицам)
    if event_type == "WORK_ORDER.CLOSED" and business_state != "COMPLETED":
        return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")
    if event_type == "WORK_ORDER.CANCELLED" and business_state in {"COMPLETED", "CLOSED"}:
        return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")

    return ValidationResult("REJECTED", "ERR_INVALID_TRANSITION")


def _check_composite_guards(business_state: str, execution_state: str) -> Optional[Dict[str, Any]]:
    if business_state == "NEW" and execution_state != "NOT_STARTED":
        return {"business_state": business_state, "execution_state": execution_state}
    if business_state == "PLANNED" and execution_state not in {"NOT_STARTED", "TRAVEL"}:
        return {"business_state": business_state, "execution_state": execution_state}
    if business_state == "IN_PROGRESS" and execution_state not in {"TRAVEL", "WORK", "WAITING_PARTS", "WAITING_CLIENT"}:
        return {"business_state": business_state, "execution_state": execution_state}
    if business_state == "ON_HOLD" and execution_state not in {"WORK", "WAITING_PARTS", "WAITING_CLIENT"}:
        return {"business_state": business_state, "execution_state": execution_state}
    if business_state == "COMPLETED" and execution_state != "FINISHED":
        return {"business_state": business_state, "execution_state": execution_state}
    if business_state in {"CLOSED", "CANCELLED"} and execution_state not in {"FINISHED", "NOT_STARTED"}:
        return {"business_state": business_state, "execution_state": execution_state}
    return None


def _evaluate_time_policy(envelope: Dict[str, Any], projection: Optional[Dict[str, Any]]) -> ValidationResult:
    now = datetime.now(timezone.utc)
    source = envelope.get("source")
    event_type = envelope["event_type"]
    reported_time = envelope.get("created_at_reported")

    if event_type == "WORK.STARTED":
        reported_time = envelope["payload"].get("actual_start_reported") or reported_time
    if event_type == "WORK.COMPLETED":
        reported_time = envelope["payload"].get("actual_end_reported") or reported_time

    t_rep = _parse_time(reported_time) if reported_time else None

    # Отсечение будущего времени (скью)
    if t_rep and t_rep > now + timedelta(minutes=5):
        return ValidationResult("REJECTED", "ERR_GUARD_FAILED", details={"reason": "future skew"})

    # Mobile: большой дрейф → в ревью
    if source == "mobile" and t_rep:
        if abs((t_rep - now).total_seconds()) > 180 * 60:
            return ValidationResult(
                "NEEDS_REVIEW",
                "REV_AMBIGUOUS_TIME",
                normalized_event={"effective_time": now},
            )

    effective_time = t_rep or now

    # Конец не может быть раньше начала (если start уже записан)
    if event_type == "WORK.COMPLETED" and projection and projection.get("actual_start_effective"):
        start_eff = projection["actual_start_effective"]
        if isinstance(start_eff, str):
            start_eff = _parse_time(start_eff)
        if start_eff and effective_time < start_eff:
            return ValidationResult("REJECTED", "ERR_GUARD_FAILED", details={"reason": "end before start"})

    return ValidationResult("ACCEPTED", "OK", normalized_event={"effective_time": effective_time})


def _load_validator(schema_path: str) -> Draft202012Validator:
    full_path = os.path.join(SCHEMAS_BASE, schema_path)
    with open(full_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return Draft202012Validator(data)


def _load_event_schema_path(event_type: str) -> str:
    mapping_path = os.path.join(SCHEMAS_BASE, "events", "index.json")
    with open(mapping_path, "r", encoding="utf-8") as handle:
        mapping = json.load(handle)
    if event_type not in mapping:
        raise ValueError(f"Unknown event_type: {event_type}")
    return os.path.relpath(mapping[event_type], SCHEMAS_BASE)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
