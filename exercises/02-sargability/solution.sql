CREATE INDEX idx_events_lower_email ON events (lower(email));

SELECT id, city FROM events WHERE lower(email) = 'known.user@example.com';
