CREATE STATISTICS stx_events_city_pincode (dependencies, ndistinct)
    ON city, pincode FROM events;

ANALYZE events;

SELECT count(*) FROM events
WHERE city = 'Mumbai North' AND pincode = 400038;
