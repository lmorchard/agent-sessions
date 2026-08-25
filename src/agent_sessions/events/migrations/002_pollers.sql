CREATE TABLE webhook_deliveries_rebuilt (
  delivery_guid TEXT PRIMARY KEY, event_type TEXT NOT NULL, action TEXT NOT NULL,
  repository_id INTEGER, received_at TEXT NOT NULL, disposition TEXT NOT NULL,
  raw_body BLOB NOT NULL, diagnostic_json TEXT NOT NULL
);
INSERT INTO webhook_deliveries_rebuilt
  SELECT delivery_guid, event_type, action, repository_id, received_at, disposition, raw_body, diagnostic_json
  FROM webhook_deliveries;
DROP TABLE webhook_deliveries;
ALTER TABLE webhook_deliveries_rebuilt RENAME TO webhook_deliveries;
CREATE INDEX deliveries_retention_idx ON webhook_deliveries(received_at);

CREATE TABLE project_items (
  board_key TEXT NOT NULL, item_node_id TEXT NOT NULL, repository_id INTEGER NOT NULL,
  content_kind TEXT NOT NULL, content_number INTEGER NOT NULL, status TEXT, priority TEXT,
  last_seen_at TEXT NOT NULL, PRIMARY KEY(board_key, item_node_id),
  FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id)
);
CREATE TABLE poll_watches (
  repository_id INTEGER NOT NULL, issue_number INTEGER NOT NULL, predicate TEXT NOT NULL,
  parked_at TEXT NOT NULL, last_value INTEGER, last_checked_at TEXT,
  PRIMARY KEY(repository_id, issue_number, predicate),
  FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id)
);
CREATE TABLE poller_state (
  source_key TEXT PRIMARY KEY, lease_owner TEXT, lease_until TEXT,
  last_success_at TEXT, last_error TEXT
);
CREATE INDEX project_items_board_idx ON project_items(board_key, repository_id);
CREATE INDEX poll_watches_repository_idx ON poll_watches(repository_id, issue_number);
