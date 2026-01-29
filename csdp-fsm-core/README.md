# CNC-FSM Core (MVP)

## Requirements
- Python 3.11+
- PostgreSQL
- Dependencies: `fastapi`, `uvicorn`, `psycopg`, `jsonschema`, `pytest`

## Local Postgres (docker-compose)
```bash
docker compose up -d postgres
```

## Apply migrations
```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/csdp_fsm
psql "$DATABASE_URL" -f migrations/001_event_store.sql
psql "$DATABASE_URL" -f migrations/002_projections.sql
psql "$DATABASE_URL" -f migrations/003_add_missing_tables.sql
```

## Run API
```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/csdp_fsm
uvicorn src.main:app --reload
```

## Example lifecycle (curl)
```bash
curl -X POST http://localhost:8000/v1/events \
  -H 'Content-Type: application/json' \
  -H 'X-Role: DISPATCHER' \
  -H 'X-Actor-Id: 00000000-0000-0000-0000-000000000001' \
  -d '{
    "event_type":"WORK_ORDER.CREATED",
    "entity_type":"work_order",
    "entity_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "source":"web",
    "payload":{
      "client_id":"9b8b0d4a-9bb1-4a21-8fd2-8d8f2a0a2f2b",
      "asset_id":"0b2c7b0c-7f7c-4ed2-9ad4-1b0a0c3c0d0e",
      "priority":"CRITICAL",
      "type":"EMERGENCY_REPAIR",
      "description":"Machine stopped with alarm 401"
    }
  }'
```

```bash
curl -X POST http://localhost:8000/v1/events \
  -H 'Content-Type: application/json' \
  -H 'X-Role: DISPATCHER' \
  -d '{
    "event_type":"WORK_ORDER.ASSIGNED",
    "entity_type":"work_order",
    "entity_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "source":"web",
    "payload":{
      "engineer_id":"b7f68f50-5c1f-4f58-8f93-82f2d9c7b3aa",
      "scheduled_start":"2026-01-27T09:00:00Z",
      "scheduled_end":"2026-01-27T11:00:00Z"
    }
  }'
```

## Run tests
```bash
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/csdp_fsm_test
pytest
```
