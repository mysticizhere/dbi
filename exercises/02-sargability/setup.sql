DROP INDEX IF EXISTS idx_events_lower_email;
DROP INDEX IF EXISTS idx_events_email;

-- A known row, so the exercise has a deterministic target. The generated
-- addresses are random, and an exercise you cannot re-run is not an exercise.
UPDATE events SET email = 'Known.User@Example.com' WHERE id = 1;

-- The plausible-looking index that does not help.
CREATE INDEX idx_events_email ON events (email);

VACUUM ANALYZE events;
