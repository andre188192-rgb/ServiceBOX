CREATE TABLE work_orders_current (
  work_order_id UUID PRIMARY KEY,
  client_id UUID NOT NULL,
  asset_id UUID NOT NULL,
  priority TEXT NOT NULL,
  work_type TEXT NOT NULL,
  business_state TEXT NOT NULL,
  execution_state TEXT NOT NULL,
  sla_state TEXT NOT NULL,
  assigned_engineer_id UUID NULL,
  assigned_team_id UUID NULL,
  scheduled_start TIMESTAMPTZ NULL,
  scheduled_end TIMESTAMPTZ NULL,
  actual_start_reported TIMESTAMPTZ NULL,
  actual_end_reported TIMESTAMPTZ NULL,
  actual_start_effective TIMESTAMPTZ NULL,
  actual_end_effective TIMESTAMPTZ NULL,
  downtime_minutes INT NULL,
  last_event_id UUID NULL,
  last_event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  version INT NOT NULL DEFAULT 0
);

CREATE INDEX ix_work_orders_state ON work_orders_current(business_state, execution_state);
CREATE INDEX ix_work_orders_asset ON work_orders_current(asset_id);
CREATE INDEX ix_work_orders_engineer ON work_orders_current(assigned_engineer_id);

CREATE TABLE work_order_timeline (
  work_order_id UUID NOT NULL,
  event_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  created_at_system TIMESTAMPTZ NOT NULL,
  created_by UUID NULL,
  payload JSONB NOT NULL
);

CREATE INDEX ix_timeline_work_order ON work_order_timeline(work_order_id, created_at_system);

CREATE TABLE work_order_parts (
  work_order_id UUID NOT NULL REFERENCES work_orders_current(work_order_id) ON DELETE CASCADE,
  part_id UUID NOT NULL,
  reserved_qty INTEGER NOT NULL DEFAULT 0,
  installed_qty INTEGER NOT NULL DEFAULT 0,
  consumed_qty INTEGER NOT NULL DEFAULT 0,
  last_event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (work_order_id, part_id)
);

CREATE TABLE work_order_evidence (
  work_order_id UUID NOT NULL REFERENCES work_orders_current(work_order_id) ON DELETE CASCADE,
  evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('PHOTO','DOCUMENT','SIGNATURE')),
  url TEXT NOT NULL,
  meta JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID NULL
);

CREATE INDEX ix_evidence_work_order ON work_order_evidence(work_order_id, created_at);

CREATE TABLE engineer_board (
  engineer_id UUID PRIMARY KEY,
  status TEXT NOT NULL,
  current_work_order_id UUID NULL,
  last_seen_at TIMESTAMPTZ NULL,
  workload_minutes_7d INT NOT NULL DEFAULT 0
);

CREATE TABLE sla_view (
  work_order_id UUID PRIMARY KEY,
  reaction_deadline_at TIMESTAMPTZ NULL,
  restore_deadline_at TIMESTAMPTZ NULL,
  breached_at TIMESTAMPTZ NULL,
  state TEXT NOT NULL,
  last_calc_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ref_catalog_items (
  catalog TEXT NOT NULL,
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order INT NOT NULL DEFAULT 0,
  meta JSONB NULL,
  PRIMARY KEY (catalog, code)
);

CREATE INDEX ix_ref_catalog_active ON ref_catalog_items(catalog, is_active, sort_order);

INSERT INTO ref_catalog_items (catalog, code, title, sort_order) VALUES
  ('WORK_PAUSE_REASON', 'PARTS', 'Waiting for parts', 10),
  ('WORK_PAUSE_REASON', 'CLIENT', 'Waiting for client', 20),
  ('WORK_PAUSE_REASON', 'ACCESS', 'Access blocked', 30),
  ('WORK_PAUSE_REASON', 'SAFETY', 'Safety stop', 40),
  ('WORK_PAUSE_REASON', 'OTHER', 'Other', 50),
  ('CANCEL_REASON', 'DUPLICATE', 'Duplicate', 10),
  ('CANCEL_REASON', 'CLIENT_REQUEST', 'Client request', 20),
  ('CANCEL_REASON', 'NO_ACCESS', 'No access', 30),
  ('CANCEL_REASON', 'SCOPE_CHANGE', 'Scope change', 40),
  ('CANCEL_REASON', 'OTHER', 'Other', 50),
  ('DOC_TYPE', 'REPORT', 'Report', 10),
  ('DOC_TYPE', 'ACT', 'Act', 20),
  ('DOC_TYPE', 'INVOICE', 'Invoice', 30),
  ('DOC_TYPE', 'OTHER', 'Other', 40),
  ('SYMPTOM', 'GENERIC', 'Generic symptom', 10),
  ('CAUSE', 'GENERIC', 'Generic cause', 10),
  ('ACTION', 'GENERIC', 'Generic action', 10);
