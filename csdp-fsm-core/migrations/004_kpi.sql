CREATE TABLE kpi_daily (
  day DATE NOT NULL,
  client_id UUID NULL,
  reaction_avg_minutes NUMERIC NULL,
  mttr_avg_minutes NUMERIC NULL,
  sla_compliance_percent NUMERIC NULL,
  work_orders_total INT NOT NULL DEFAULT 0,
  PRIMARY KEY (day, client_id)
);
