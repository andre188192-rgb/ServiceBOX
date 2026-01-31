CREATE TABLE contracts (
  contract_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL,
  contract_type TEXT NOT NULL CHECK (contract_type IN ('FULL_SERVICE','EXTENDED_SUPPORT','BASIC_SUPPORT')),
  active_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  active_to TIMESTAMPTZ NULL,
  reaction_minutes INT NOT NULL,
  restore_minutes INT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE work_orders_current
  ADD COLUMN contract_id UUID NULL;

CREATE INDEX ix_contracts_client_active ON contracts(client_id, is_active);
CREATE INDEX ix_work_orders_contract ON work_orders_current(contract_id);
