# CSDP / CNC-FSM Core — Architecture

## 1. Scope
CNC-FSM Core owns:
- Work Order lifecycle (formal FSM)
- Append-only Event Log (event store)
- Projections (query models)
- SLA/KPI computation policies
- Offline conflict arbitration

Out of scope (integrations): CRM/ERP, maps, telephony/email ingestion, BI frontends.

## 2. Architectural style
- Event-driven core with append-only event store
- CQRS: Command API (events) + Query API (projections)
- Server as the arbiter of truth: clients propose events, server validates

## 3. Data stores
- PostgreSQL:
  - event_store (immutable)
  - projections (mutable, rebuildable)
  - reference data (catalogs)
- Redis (optional): caching and short-lived locks
- Object storage: photos/documents/signatures

## 4. Core entities
- WorkOrder (aggregate root)
- Asset (+ time-valid configuration snapshots)
- Engineer (availability, skills)
- Contract/SLA policy

## 5. Event Store
### 5.1. Guarantees
- Append-only
- Idempotent ingestion (client_event_id/idempotency_key)
- Correlation/causation IDs for tracing

### 5.2. Rebuild strategy
- Projections must be rebuildable by replaying events.
- Backup must include: event_store + projection schemas.

## 6. Projections (examples)
- work_orders_current: current state, schedule, assignment
- work_order_timeline: ordered events for audit
- engineer_board: dispatch/travel/work status
- sla_view: computed SLA state and deadlines
- kpi_aggregates: MTTR, reaction time, etc.

## 7. APIs
### 7.1. Command API (write)
- POST /v1/events
  - validates transition rules (FSM)
  - persists event
  - updates projections asynchronously or transactionally (policy choice)

### 7.2. Query API (read)
- GET /v1/work-orders
- GET /v1/work-orders/{id}
- GET /v1/work-orders/{id}/timeline
- GET /v1/engineers/board
- GET /v1/kpi

### 7.3. Real-time
- WebSocket / SSE: projection updates, notifications

## 8. Offline sync
- Mobile keeps a local event queue.
- Each event has client_event_id.
- Server responses: ACCEPTED | REJECTED | NEEDS_REVIEW.
- Conflict policy: server wins; rejected events are explainable (reason codes).

## 9. SLA/KPI computation
- SLA is server-only and derived from contract policy + effective_time.
- KPI is computed from events (never from mutable fields).

## 10. Security
- OAuth2/JWT
- RBAC: engineer/dispatcher/manager/admin
- Audit: every command is an event with actor identity

## 11. Observability
- Structured logs with correlation_id
- Metrics: event ingestion latency, projection lag, SLA breach rates
- Tracing across integrations via correlation_id
