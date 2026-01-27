from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/v1/kpi")
def get_kpi(period_from: str | None = Query(default=None), period_to: str | None = Query(default=None)) -> Dict[str, Any]:
    return {
        "period_from": period_from,
        "period_to": period_to,
        "reaction_time_avg_minutes": None,
        "mttr_avg_minutes": None,
        "sla_compliance_percent": None,
        "first_time_fix_percent": None,
    }
