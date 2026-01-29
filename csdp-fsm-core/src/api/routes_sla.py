from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from src.storage.db import get_tx
from src.storage import projections_repo

router = APIRouter()


@router.get("/v1/sla/{work_order_id}")
def get_sla_view(work_order_id: str) -> Dict[str, Any]:
    with get_tx() as conn:
        row = projections_repo.fetch_sla_view(conn, work_order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row
