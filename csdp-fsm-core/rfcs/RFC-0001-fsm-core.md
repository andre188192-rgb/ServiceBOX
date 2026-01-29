# RFC-0001: CNC-FSM Core (Event-driven FSM Kernel)
Status: Proposed
Author: <owner>
Date: 2026-01-27

## 1. Abstract
This RFC defines the CNC-FSM Core as an event-driven kernel for field service operations, using formal state machines, an append-only event store, rebuildable projections, and server-side arbitration for offline and SLA/KPI correctness.

## 2. Motivation
Prior FSM implementations fail due to:
- mutable states without auditability
- offline edits corrupting truth
- SLA/KPI computed from overwritten fields
- inability to reproduce decisions retroactively

This RFC mandates event-sourced truth, formal transition validation, and time semantics.

## 3. Definitions
- Event: immutable record describing a domain fact
- Projection: derived query model, rebuildable from events
- effective_time: server-approved time used for calculations
- Business/Execution/SLA: orthogonal state machines for a work order

## 4. Requirements (Normative)
MUST:
- persist all state changes as append-only events
- validate transitions server-side using formal FSM rules
- compute SLA/KPI from events using effective_time
- support offline via client_event_id and idempotent ingestion
- keep projections rebuildable by replay

MUST NOT:
- allow direct status mutation without an event
- overwrite history
- compute SLA on the client
- compute KPI from mutable fields

## 5. State Machines
The work order state is defined by three orthogonal FSMs:
- Business State
- Execution State
- SLA State

Transitions are triggered by events and validated by guards.

## 6. Event Model
All events MUST include:
- event_id, entity_type, entity_id, event_type
- payload (schema_versioned)
- created_at_system, created_at_reported
- created_by, source
- client_event_id or idempotency_key for offline sources

## 7. Offline Conflict Policy
- clients submit events; server is arbiter
- ingestion is idempotent
- server returns ACCEPTED/REJECTED/NEEDS_REVIEW
- REJECTED events MUST include reason codes and remediation hints

## 8. Projections
Projections MAY be updated transactionally or asynchronously but MUST be rebuildable from event_store.

## 9. Security and Audit
- RBAC is enforced for event submission
- every event carries actor identity
- audit is obtained by replay + timeline projection

## 10. Rollout Plan
- v1 (MVP): taxonomy v1, core projections, offline queue, SLA minimal
- v2: expanded taxonomy, approvals, logistics, diagnostics, billing hooks

## 11. Open Questions
- transactional vs async projection updates
- exact effective_time policy per contract
- retention and compaction strategy for event_store
