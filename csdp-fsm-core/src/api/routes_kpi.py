from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from src.storage.db import get_tx

router = APIRouter()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(value)


@router.get("/v1/kpi")
def get_kpi(period_from: str | None = Query(default=None), period_to: str | None = Query(default=None)) -> Dict[str, Any]:
    date_from = _parse_date(period_from)
    date_to = _parse_date(period_to)
    with get_tx() as conn:
        items = _fetch_kpi_rows(conn, date_from, date_to)
    aggregate = _aggregate_kpi(items)
    return {
        "period_from": period_from,
        "period_to": period_to,
        "reaction_time_avg_minutes": aggregate["reaction_time_avg_minutes"],
        "mttr_avg_minutes": aggregate["mttr_avg_minutes"],
        "sla_compliance_percent": aggregate["sla_compliance_percent"],
        "work_orders_total": aggregate["work_orders_total"],
        "items": items,
    }


def _fetch_kpi_rows(conn, date_from: date | None, date_to: date | None) -> List[Dict[str, Any]]:
    clauses = []
    params: List[Any] = []
    if date_from:
        clauses.append("day >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("day <= %s")
        params.append(date_to)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"""
        SELECT day, client_id, reaction_avg_minutes, mttr_avg_minutes, sla_compliance_percent, work_orders_total
        FROM kpi_daily
        {where}
        ORDER BY day, client_id NULLS FIRST
    """
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _aggregate_kpi(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        return {
            "reaction_time_avg_minutes": None,
            "mttr_avg_minutes": None,
            "sla_compliance_percent": None,
            "work_orders_total": 0,
        }
    total_orders = sum(item["work_orders_total"] for item in items)
    reaction_values = [item["reaction_avg_minutes"] for item in items if item["reaction_avg_minutes"] is not None]
    mttr_values = [item["mttr_avg_minutes"] for item in items if item["mttr_avg_minutes"] is not None]
    sla_values = [item["sla_compliance_percent"] for item in items if item["sla_compliance_percent"] is not None]
    return {
        "reaction_time_avg_minutes": sum(reaction_values) / len(reaction_values) if reaction_values else None,
        "mttr_avg_minutes": sum(mttr_values) / len(mttr_values) if mttr_values else None,
        "sla_compliance_percent": sum(sla_values) / len(sla_values) if sla_values else None,
        "work_orders_total": total_orders,
    }
