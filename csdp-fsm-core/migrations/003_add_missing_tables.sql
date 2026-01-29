CREATE TABLE IF NOT EXISTS work_order_parts (
  work_order_id UUID NOT NULL,
  part_id UUID NOT NULL,
  reserved_qty NUMERIC NOT NULL DEFAULT 0,
  installed_qty NUMERIC NOT NULL DEFAULT 0,
  consumed_qty NUMERIC NOT NULL DEFAULT 0,
  last_event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (work_order_id, part_id)
);

CREATE TABLE IF NOT EXISTS work_order_evidence (
  work_order_id UUID NOT NULL,
  evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('PHOTO','DOCUMENT','SIGNATURE')),
  url TEXT NOT NULL,
  meta JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID NULL
);

CREATE INDEX IF NOT EXISTS ix_evidence_work_order ON work_order_evidence(work_order_id, created_at);
