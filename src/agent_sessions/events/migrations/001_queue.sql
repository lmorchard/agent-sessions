CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE repository_state (
  repository_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
  installation_id INTEGER, last_hint_at TEXT, last_scan_started_at TEXT,
  last_scan_success_at TEXT, scan_lease_owner TEXT, scan_lease_until TEXT
);
CREATE TABLE webhook_deliveries (
  delivery_guid TEXT PRIMARY KEY, event_type TEXT NOT NULL, action TEXT NOT NULL,
  repository_id INTEGER, received_at TEXT NOT NULL, disposition TEXT NOT NULL,
  raw_body BLOB NOT NULL, diagnostic_json TEXT NOT NULL
);
CREATE TABLE invalidations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT NOT NULL, source_key TEXT NOT NULL,
  repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL,
  observed_at TEXT NOT NULL, diagnostic_json TEXT NOT NULL,
  FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id)
);
CREATE TABLE dirty_targets (
  repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL,
  generation INTEGER NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  lease_owner TEXT, lease_until TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT, last_error TEXT,
  PRIMARY KEY(repository_id, target_kind, target_key),
  FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id)
);
CREATE INDEX invalidations_retention_idx ON invalidations(observed_at);
CREATE INDEX deliveries_retention_idx ON webhook_deliveries(received_at);
CREATE INDEX dirty_claim_idx ON dirty_targets(repository_id, lease_until, next_attempt_at);
CREATE INDEX repository_status_idx ON repository_state(last_hint_at, last_scan_success_at);
