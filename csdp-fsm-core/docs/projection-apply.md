# Event → Projection Changeset (apply_event)

## 1) Terms
- `P` — `work_orders_current` row for `work_order_id`
- `E` — incoming event (envelope + payload)
- `t_sys = E.created_at_system` (DB write time)
- `t_rep = E.created_at_reported` or event-specific reported time
- `t_eff` — effective_time from time-policy

## 2) Baseline actions (all accepted events)
When `ACCEPTED`:
- `P.last_event_id = event_id`
- `P.last_event_at = now()`
- `P.version = P.version + 1`

## 3) Changes by event (v1)

### WORK_ORDER.CREATED
**Guard:** aggregate does not exist
**Changeset:**
- create `P`:
  - `P.work_order_id = entity_id`
  - `P.client_id = payload.client_id`
  - `P.asset_id = payload.asset_id`
  - `P.priority = payload.priority`
  - `P.work_type = payload.type`
  - `P.business_state = NEW`
  - `P.execution_state = NOT_STARTED`
  - `P.sla_state = IN_SLA`

### WORK_ORDER.ASSIGNED
**Guard:** `P.business_state == NEW`, assignment and schedule valid
**Changeset:**
- `P.assigned_engineer_id = payload.engineer_id` (nullable)
- `P.assigned_team_id = payload.team_id` (nullable)
- `P.scheduled_start = payload.scheduled_start`
- `P.scheduled_end = payload.scheduled_end`
- `P.business_state = PLANNED`
- `P.execution_state` unchanged (`NOT_STARTED`)

### WORK.DISPATCHED
**Guard:** ABAC (engineer only own), Business ∈ {PLANNED, IN_PROGRESS}
**Changeset:**
- `P.execution_state = TRAVEL` **if** `P.execution_state == NOT_STARTED`
- if already `TRAVEL/WORK/...`, event may be idempotent (no state change)

### WORK.ARRIVED_ON_SITE
**Guard:** `P.execution_state == TRAVEL`
**Changeset:**
- `P.execution_state = WORK`

### WORK.STARTED
**Guard:** `P.business_state == PLANNED`
**Reported time extraction:** `rt = payload.actual_start_reported ?? E.created_at_reported`
**Changeset:**
- `P.business_state = IN_PROGRESS`
- `P.actual_start_reported = coalesce(P.actual_start_reported, rt)`
- `P.actual_start_effective = coalesce(P.actual_start_effective, t_eff)`
- `P.execution_state`:
  - if `NOT_STARTED` → `WORK`
  - if `TRAVEL` → `WORK`
  - if already `WORK/WAITING_*` → unchanged

### WORK.PAUSED
**Guard:** Business ∈ {PLANNED, IN_PROGRESS}, `payload.reason_code` valid
**Changeset:**
- `P.business_state = ON_HOLD`
- `P.execution_state`:
  - `reason_code == PARTS` → `WAITING_PARTS`
  - `reason_code == CLIENT` → `WAITING_CLIENT`
  - else → keep `WORK` (MVP)

### WORK.RESUMED
**Guard:** `P.business_state == ON_HOLD`
**Changeset:**
- `P.business_state = IN_PROGRESS`
- `P.execution_state = WORK` (if previously waiting)

### PART.RESERVED / PART.INSTALLED / PART.CONSUMED
**Guard:** part exists; qty > 0
**Changeset:**
- no direct update to `P` in MVP
- update `work_order_parts` (see below)

### EVIDENCE.PHOTO_ADDED / DOCUMENT_ADDED / SIGNATURE_CAPTURED
**Changeset:**
- no direct update to `P` in MVP
- insert into `work_order_evidence` (see below)

### WORK.COMPLETED
**Guard:** `P.business_state == IN_PROGRESS`, checklist minimum ok
**Reported time extraction:** `rt = payload.actual_end_reported ?? E.created_at_reported`
**Changeset:**
- `P.business_state = COMPLETED`
- `P.execution_state = FINISHED`
- `P.actual_end_reported = coalesce(P.actual_end_reported, rt)`
- `P.actual_end_effective = coalesce(P.actual_end_effective, t_eff)`
- if `P.actual_start_effective` and `P.actual_end_effective`:
  - `P.downtime_minutes = floor(extract(epoch from (end_eff - start_eff))/60)`

### WORK_ORDER.CLOSED
**Guard:** `P.business_state == COMPLETED` and evidence/parts policy satisfied
**Changeset:**
- `P.business_state = CLOSED`
- `P.execution_state` remains `FINISHED`

### WORK_ORDER.CANCELLED
**Guard:** `P.business_state ∈ {NEW, PLANNED, IN_PROGRESS, ON_HOLD}`
**Changeset:**
- `P.business_state = CANCELLED`
- `P.execution_state` unchanged (MVP)

### SLA.* (server-only)
**Changeset:**
- `P.sla_state = ...` based on event
- update `sla_view` (deadlines/breached_at)

## 4) Additional projections (MVP)

### work_order_parts
```sql
CREATE TABLE work_order_parts (
  work_order_id UUID NOT NULL,
  part_id UUID NOT NULL,
  reserved_qty NUMERIC NOT NULL DEFAULT 0,
  installed_qty NUMERIC NOT NULL DEFAULT 0,
  consumed_qty NUMERIC NOT NULL DEFAULT 0,
  last_event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (work_order_id, part_id)
);
```

**Apply rules:**
- `PART.RESERVED` → `reserved_qty += qty`
- `PART.INSTALLED` → `installed_qty += qty`
- `PART.CONSUMED` → `consumed_qty += qty`

### work_order_evidence
```sql
CREATE TABLE work_order_evidence (
  work_order_id UUID NOT NULL,
  evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('PHOTO','DOCUMENT','SIGNATURE')),
  url TEXT NOT NULL,
  meta JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID NULL
);
CREATE INDEX ix_evidence_work_order ON work_order_evidence(work_order_id, created_at);
```

**Apply rules:**
- `EVIDENCE.PHOTO_ADDED` → insert PHOTO
- `EVIDENCE.DOCUMENT_ADDED` → insert DOCUMENT
- `EVIDENCE.SIGNATURE_CAPTURED` → insert SIGNATURE
