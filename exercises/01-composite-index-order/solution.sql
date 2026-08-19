CREATE INDEX idx_events_score ON events (score);

SELECT count(*) FROM events WHERE score < 2000;
