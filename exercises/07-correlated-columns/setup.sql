-- Remove any extended statistics a previous attempt left behind, so the
-- exercise always starts from the broken estimate.
DROP STATISTICS IF EXISTS stx_events_city_pincode;

ANALYZE events;
