from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request

from src.domain.apply_event import apply_event
from src.domain.validator import Actor, validate_event
from src.storage import event_store_repo
from src.storage.db import get_tx

router = APIRouter()


@router.post("/v1/events")
async def post_event(
    request: Request,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
    x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
) -> Dict[str, Any]:
    payload = await request.json()
    if x_idempotency_key and not payload.get("idempotency_key"):
        payload["idempotency_key"] = x_idempotency_key
    actor = Actor(role=(x_role or "SYSTEM"), actor_id=x_actor_id)

    with get_tx() as conn:
        validation = validate_event(conn, payload, actor)
        if validation.decision != "ACCEPTED":
            return {
                "decision": validation.decision,
                "reason_code": validation.reason_code,
                "details": validation.details,
            }

        normalized_event = validation.normalized_event or payload
        normalized_event["created_by"] = actor.actor_id
        event_id, duplicate = event_store_repo.insert_event(conn, normalized_event)
        if duplicate:
            return {
                "decision": "ACCEPTED",
                "reason_code": "DUPLICATE_IGNORED",
                "event_id": event_id,
            }

        stored = event_store_repo.fetch_event_by_id(conn, event_id)
        if not stored:
            raise HTTPException(status_code=500, detail="event_store insert failed")
        normalized_event["event_id"] = event_id
        normalized_event["created_at_system"] = stored["created_at_system"]
        apply_event(conn, normalized_event)
        return {
            "decision": "ACCEPTED",
            "reason_code": "OK",
            "event_id": event_id,
        }
