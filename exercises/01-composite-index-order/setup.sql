-- The deliberately wrong index: leading column is city, so a predicate on score
-- alone has no contiguous range to seek to.
DROP INDEX IF EXISTS idx_events_city_score;
DROP INDEX IF EXISTS idx_events_score;
CREATE INDEX idx_events_city_score ON events (city, score);

-- Baseline the visibility map so index-only scans are not penalised by
-- unrelated bloat. Exercise 5 is where a stale map is the point.
VACUUM ANALYZE events;
