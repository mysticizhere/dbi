-- 0.2% of the table: comfortably below the crossover.
SELECT sum(pincode) FROM events WHERE score < 20000;
