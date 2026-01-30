# FSM Transition Guard Matrix

## 0) Validator rules (normative)
Input: `current_state` (projection), `event` (command), `actor`, `source`.
Output: `ACCEPTED | REJECTED | NEEDS_REVIEW + reason_code`.

MUST:
- verify RBAC (role → allowed `event_type`)
- verify transition (from_state → event → to_state)
- enforce guards (required payload fields, prerequisites)
- enforce idempotency: `(entity_id, client_event_id)` or `idempotency_key`
- when accepted → append to `event_store`, update/schedule projections

## 1) Business State (Work Order)
States: `NEW`, `PLANNED`, `IN_PROGRESS`, `ON_HOLD`, `COMPLETED`, `CLOSED`, `CANCELLED`.

| From | Event type | To | Actor roles | Guard (preconditions) | Payload MUST | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | `WORK_ORDER.CREATED` | `NEW` | Dispatcher, API, System | asset_id exists; client exists | `asset_id`, `client_id`, `priority`, `type`, `description` | creates aggregate |
| `NEW` | `WORK_ORDER.ASSIGNED` | `PLANNED` | Dispatcher, System | engineer/team exists; schedule ok | `engineer_id` OR `team_id`, `scheduled_start`, `scheduled_end` | parts reservation can be separate |
| `NEW` | `WORK_ORDER.CANCELLED` | `CANCELLED` | Dispatcher | no work performed | `reason_code`, `comment?` | cancel before start |
| `PLANNED` | `WORK.STARTED` | `IN_PROGRESS` | Engineer, Dispatcher | engineer assigned; (optional) arrived_on_site | `actual_start_reported?` | actual time via policy |
| `PLANNED` | `WORK.PAUSED` | `ON_HOLD` | Engineer, Dispatcher | pause_reason valid | `reason_code`, `comment?`, `eta_minutes?` | business on-hold |
| `PLANNED` | `WORK_ORDER.CANCELLED` | `CANCELLED` | Dispatcher | work not started | `reason_code` |  |
| `IN_PROGRESS` | `WORK.PAUSED` | `ON_HOLD` | Engineer, Dispatcher | pause_reason valid | `reason_code`, `comment?`, `eta_minutes?` |  |
| `ON_HOLD` | `WORK.RESUMED` | `IN_PROGRESS` | Engineer, Dispatcher | prior pause; reason cleared | `comment?` |  |
| `IN_PROGRESS` | `WORK.COMPLETED` | `COMPLETED` | Engineer | `WORK.STARTED` exists; checklist minimum ok | `actual_end_reported?`, `summary?`, `actions[]?` | not closing yet |
| `COMPLETED` | `WORK_ORDER.CLOSED` | `CLOSED` | Dispatcher, Engineer (if allowed), System | signature/docs/parts policy satisfied | `downtime?` (optional), `signature_url?` | server recomputes downtime |
| `CLOSED` | `WORK_ORDER.REOPENED` | `IN_PROGRESS` | Dispatcher, Manager | reopen policy; reason | `reason_code`, `comment` | optional |
| ANY (except `CLOSED`/`CANCELLED`) | `WORK_ORDER.CANCELLED` | `CANCELLED` | Dispatcher, Manager | forbidden if `COMPLETED` | `reason_code` | cancellation in `COMPLETED` forbidden |

**Hard rejects (REJECTED):**
- `WORK_ORDER.CLOSED` not from `COMPLETED`.
- `WORK_ORDER.CANCELLED` from `COMPLETED` or `CLOSED`.
- `WORK.COMPLETED` without `WORK.STARTED`.

## 2) Execution State (Engineer)
States: `NOT_STARTED`, `TRAVEL`, `WORK`, `WAITING_PARTS`, `WAITING_CLIENT`, `FINISHED`.

| From | Event type | To | Actor roles | Guard | Payload MUST | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `NOT_STARTED` | `WORK.DISPATCHED` | `TRAVEL` | Dispatcher, Engineer | work order assigned to engineer | `dispatch_time_reported?` | can be auto-generated |
| `TRAVEL` | `WORK.ARRIVED_ON_SITE` | `WORK` | Engineer | was dispatched | `arrived_time_reported?` |  |
| `WORK` | `WORK.PAUSED` | `WAITING_PARTS` | Engineer | `reason=PARTS` | `reason_code=PARTS`, `comment?`, `eta_minutes?` |  |
| `WORK` | `WORK.PAUSED` | `WAITING_CLIENT` | Engineer | `reason=CLIENT` | `reason_code=CLIENT`, `comment?`, `eta_minutes?` |  |
| `WAITING_PARTS` | `WORK.RESUMED` | `WORK` | Engineer | reason cleared | `comment?` |  |
| `WAITING_CLIENT` | `WORK.RESUMED` | `WORK` | Engineer | reason cleared | `comment?` |  |
| `WORK` | `WORK.COMPLETED` | `FINISHED` | Engineer | checklist minimum ok | `work_summary`, `actions[]`, `causes[]?`, `symptoms[]?` |  |
| `FINISHED` | (none) | (terminal) | — | — | — | further execution events forbidden |

Recommendation:
If you want strict separation of travel and work, keep `WORK.STARTED` in business and `WORK.ARRIVED_ON_SITE` in execution.

## 3) SLA State (server-only)
States: `IN_SLA`, `AT_RISK`, `BREACHED`, `ACCEPTED_BREACH`.

| From | Event type | To | Actor | Guard | Payload MUST |
| --- | --- | --- | --- | --- | --- |
| `IN_SLA` | `SLA.AT_RISK` | `AT_RISK` | System | deadline exists | `metric`, `deadline_at`, `remaining_minutes` |
| `AT_RISK` | `SLA.RECOVERED` | `IN_SLA` | System | risk cleared | `metric` |
| `IN_SLA` | `SLA.BREACHED` | `BREACHED` | System | deadline passed | `metric`, `breached_at` |
| `AT_RISK` | `SLA.BREACHED` | `BREACHED` | System | deadline passed | `metric`, `breached_at` |
| `BREACHED` | `SLA.BREACH_ACCEPTED` | `ACCEPTED_BREACH` | Manager/Dispatcher | approval policy | `approved_by`, `doc_ref?`, `comment?` |

Hard rule: if `source != system` and event starts with `SLA.` → REJECTED (`ERR_SLA_SERVER_ONLY`).

## 4) Composite Guards (cross-dimension)
These rules run after local FSM validation.

| Condition | Requirement | Otherwise |
| --- | --- | --- |
| Business=`NEW` | Execution MUST = `NOT_STARTED` | REJECTED `ERR_STATE_MISMATCH` |
| Business=`PLANNED` | Execution MUST ∈ {`NOT_STARTED`, `TRAVEL`} | REJECTED |
| Business=`IN_PROGRESS` | Execution MUST ∈ {`TRAVEL`, `WORK`, `WAITING_*`} | REJECTED |
| Business=`COMPLETED` | Execution MUST = `FINISHED` | REJECTED |
| Business=`CLOSED`/`CANCELLED` | Execution MUST be terminal (no new events) | REJECTED |
| `WORK.COMPLETED` accepted | Business must become `COMPLETED` and Execution=`FINISHED` (same tx or guaranteed handler) | NEEDS_REVIEW if mismatch |
| `WORK_ORDER.CLOSED` accepted | forbid subsequent events except `REOPEN` (if enabled) | REJECTED |

## 5) Standard validator response codes
**REJECTED**
- `ERR_INVALID_TRANSITION` — forbidden event from current state
- `ERR_GUARD_FAILED` — guard/precondition failed
- `ERR_PAYLOAD_MISSING` — required payload fields missing
- `ERR_RBAC_DENIED` — role not permitted
- `ERR_SLA_SERVER_ONLY` — SLA events must be server-only
- `ERR_IDEMPOTENCY_CONFLICT` — idempotency conflict (policy-defined)
- `ERR_STATE_MISMATCH` — cross-dimension mismatch

**NEEDS_REVIEW**
- `REV_CONFLICT_OFFLINE` — late offline event conflicts
- `REV_AMBIGUOUS_TIME` — reported time too divergent
- `REV_POLICY_EXCEPTION` — closure/docs policy exception

## 6) Codex task prompt (copy-paste)
Task: implement event ingestion + validation

Implement JSON Schema validation:
- validate EventEnvelope
- then validate payload by `event_type` via `schemas/events/index.json`

Implement FSM validation per guard matrices above:
- Business FSM
- Execution FSM
- SLA server-only rule
- Composite guards

Implement idempotency:
- for mobile: `(entity_id, client_event_id)`
- for web/api: `(entity_id, idempotency_key)` if provided

Response:
`ACCEPTED | REJECTED | NEEDS_REVIEW + reason_code + details`

Tests:
- one test per valid transition
- one test per hard reject and RBAC denial
- test repeated `client_event_id`
