from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from src.storage.db import get_tx
from src.storage import projections_repo

router = APIRouter()


@router.get("/v1/engineers/board")
def get_engineer_board() -> Dict[str, Any]:
    with get_tx() as conn:
        items = projections_repo.fetch_engineer_board(conn)
    return {"items": items}
