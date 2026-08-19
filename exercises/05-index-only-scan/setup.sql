DROP INDEX IF EXISTS idx_events_city_score;
DROP INDEX IF EXISTS idx_events_score;
CREATE INDEX idx_events_score ON events (score);

-- Start from a clean visibility map...
VACUUM ANALYZE events;

-- ...then dirty it. `score = score` changes nothing about the data, but it is
-- still an UPDATE: MVCC writes a new row version and the old one becomes dead,
-- so every page involved loses its all-visible bit.
UPDATE events SET score = score WHERE id <= 300000;

ANALYZE events;
