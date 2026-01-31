from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from src.storage.db import get_tx
from src.storage import projections_repo

router = APIRouter()


@router.get("/v1/ref/{catalog}")
def get_ref_catalog(catalog: str, active: bool = Query(default=True)) -> Dict[str, Any]:
    with get_tx() as conn:
        items = projections_repo.list_ref_catalog(conn, catalog, active)
    return {"catalog": catalog, "items": items}
