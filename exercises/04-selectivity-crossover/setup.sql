DROP INDEX IF EXISTS idx_events_city_score;
DROP INDEX IF EXISTS idx_events_score;
CREATE INDEX idx_events_score ON events (score);

VACUUM ANALYZE events;
