CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE event_store (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  source TEXT NOT NULL,
  created_at_system TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at_reported TIMESTAMPTZ NULL,
  client_event_id TEXT NULL,
  idempotency_key TEXT NULL,
  correlation_id UUID NULL,
  causation_id UUID NULL,
  schema_version INT NOT NULL DEFAULT 1,
  created_by UUID NULL
);

CREATE INDEX ix_event_store_entity ON event_store(entity_id, created_at_system);
CREATE INDEX ix_event_store_type ON event_store(event_type, created_at_system);
CREATE UNIQUE INDEX uq_event_store_client_event
  ON event_store(entity_id, client_event_id)
  WHERE client_event_id IS NOT NULL;
CREATE UNIQUE INDEX uq_event_store_idempotency
  ON event_store(entity_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
