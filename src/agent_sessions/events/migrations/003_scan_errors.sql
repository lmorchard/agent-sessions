ALTER TABLE repository_state
  ADD COLUMN last_scan_error TEXT NOT NULL DEFAULT '';
