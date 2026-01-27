from fastapi import FastAPI

from src.api import routes_engineers, routes_events, routes_kpi, routes_ref, routes_sla, routes_work_orders


def create_app() -> FastAPI:
    app = FastAPI(title="CNC-FSM Core API")
    app.include_router(routes_events.router)
    app.include_router(routes_work_orders.router)
    app.include_router(routes_engineers.router)
    app.include_router(routes_sla.router)
    app.include_router(routes_ref.router)
    app.include_router(routes_kpi.router)
    return app


app = create_app()
