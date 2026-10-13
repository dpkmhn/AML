-- Runs once, when the volume is first created (docker-entrypoint-initdb.d).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE customers (
  customer_id        text PRIMARY KEY,           -- CUS-0001
  full_name          text NOT NULL,
  segment            text NOT NULL CHECK (segment IN ('salaried','business','student','retiree')),
  occupation         text NOT NULL,
  declared_monthly_income_aed numeric(14,2) NOT NULL,
  expected_activity  text NOT NULL,              -- free text, e.g. 'salary in, rent and cards out'
  risk_rating        text NOT NULL CHECK (risk_rating IN ('low','medium','high')),
  is_pep             boolean NOT NULL DEFAULT false,
  nationality        char(2) NOT NULL,
  account_opened     date NOT NULL,
  kyc_notes          text NOT NULL DEFAULT ''
);

CREATE TABLE transactions (
  txn_id               text PRIMARY KEY,         -- TXN-000001
  customer_id          text NOT NULL REFERENCES customers,
  ts                   timestamptz NOT NULL,
  amount_aed           numeric(14,2) NOT NULL CHECK (amount_aed > 0),
  direction            text NOT NULL CHECK (direction IN ('in','out')),
  channel              text NOT NULL CHECK (channel IN ('cash','transfer','card')),
  counterparty_id      text,
  counterparty_name    text,
  counterparty_country char(2),
  reference            text                      -- customer-written: untrusted
);
CREATE INDEX ON transactions (customer_id, ts);

CREATE TABLE alerts (
  alert_id     text PRIMARY KEY,                 -- ALT-0001
  customer_id  text NOT NULL REFERENCES customers,
  rule_id      text NOT NULL,                    -- TM-STR-01 etc.
  window_start date NOT NULL,
  window_end   date NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_review','closed'))
);
CREATE INDEX ON alerts (customer_id);

CREATE TABLE cases (
  case_id           text PRIMARY KEY,            -- CASE-0001, also the LangGraph thread_id
  alert_id          text NOT NULL REFERENCES alerts,
  kind              text NOT NULL DEFAULT 'case' CHECK (kind IN ('case', 'eval')),
  recommended_route text,
  final_route       text,
  reviewer          text,
  override_reason   text,
  pack              jsonb,                       -- findings, assessment, route reasons
  narrative         text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  decided_at        timestamptz
);
-- one real case per alert; evaluation runs (EVAL-<run>-<alert>) may repeat an alert
CREATE UNIQUE INDEX cases_alert_once ON cases (alert_id) WHERE kind = 'case';

CREATE TABLE audit_log (
  id             bigserial PRIMARY KEY,
  case_id        text NOT NULL REFERENCES cases,
  step           text NOT NULL,                  -- node name
  model          text,
  prompt_version text,
  input          jsonb,
  output         jsonb,
  tokens_in      int,
  tokens_out     int,
  latency_ms     int,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE guidance_chunks (
  chunk_id  text PRIMARY KEY,                    -- CHK-TYP-STR-03
  doc_id    text NOT NULL,
  typology  text NOT NULL,
  section   text NOT NULL,
  content   text NOT NULL,
  embedding vector(1536)                         -- must equal EMBED_DIM
);
