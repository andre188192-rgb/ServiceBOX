from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from src.storage.db import get_tx
from src.storage import projections_repo

router = APIRouter()


@router.get("/v1/work-orders")
def list_work_orders(
    business_state: str | None = Query(default=None),
    assigned_engineer_id: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> Dict[str, Any]:
    with get_tx() as conn:
        items = projections_repo.list_work_orders(conn, business_state, assigned_engineer_id, asset_id, limit, cursor)
    return {"items": items, "next_cursor": None}


@router.get("/v1/work-orders/{work_order_id}")
def get_work_order(work_order_id: str) -> Dict[str, Any]:
    with get_tx() as conn:
        row = projections_repo.fetch_work_order(conn, work_order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.get("/v1/work-orders/{work_order_id}/timeline")
def get_work_order_timeline(work_order_id: str, limit: int = Query(default=200, ge=1, le=500)) -> Dict[str, Any]:
    with get_tx() as conn:
        events = projections_repo.fetch_timeline(conn, work_order_id, limit)
    return {"work_order_id": work_order_id, "events": events}


@router.get("/v1/work-orders/{work_order_id}/parts")
def get_work_order_parts(work_order_id: str) -> Dict[str, Any]:
    with get_tx() as conn:
        items = projections_repo.fetch_parts(conn, work_order_id)
    return {"work_order_id": work_order_id, "items": items}


@router.get("/v1/work-orders/{work_order_id}/evidence")
def get_work_order_evidence(work_order_id: str) -> Dict[str, Any]:
    with get_tx() as conn:
        items = projections_repo.fetch_evidence(conn, work_order_id)
    return {"work_order_id": work_order_id, "items": items}
