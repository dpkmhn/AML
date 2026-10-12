-- Two least-privilege roles. Passwords are for local development only.
-- copilot_ro: what the copilot's tools read. It cannot write anything.
CREATE ROLE copilot_ro LOGIN PASSWORD 'copilot_ro';
GRANT CONNECT ON DATABASE aml TO copilot_ro;
GRANT USAGE ON SCHEMA public TO copilot_ro;
GRANT SELECT ON customers, transactions, alerts, guidance_chunks TO copilot_ro;

-- copilot_rw: writes cases and the audit log, and moves an alert's status.
CREATE ROLE copilot_rw LOGIN PASSWORD 'copilot_rw';
GRANT CONNECT ON DATABASE aml TO copilot_rw;
GRANT USAGE ON SCHEMA public TO copilot_rw;
GRANT SELECT, INSERT, UPDATE ON cases TO copilot_rw;
GRANT SELECT, INSERT ON audit_log TO copilot_rw;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO copilot_rw;
GRANT SELECT, UPDATE (status) ON alerts TO copilot_rw;
