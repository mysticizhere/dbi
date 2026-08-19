# Correlated columns

## What happened

The planner estimates a conjunction by multiplying selectivities:

```
rows = total x p(city = 'Mumbai North') x p(pincode = 400038)
     = 10,000,000 x (1/200) x (1/200)
     = 250
```

That is right when the columns are independent. Here the second condition adds
no information at all — knowing the city determines the pincode — so the true
answer is `10,000,000 x 1/200 = 50,000`.

`CREATE STATISTICS` teaches the planner about the relationship:

- **`dependencies`** — functional dependency: knowing `city` determines
  `pincode`. This is the kind that fixes the estimate here.
- **`ndistinct`** — how many *distinct combinations* of the columns exist. The
  planner would otherwise assume 200 x 200 = 40,000; the truth is 200. Matters
  for `GROUP BY city, pincode` and for hash-join sizing.
- **`mcv`** — most common combined values. Helps when the skew is in specific
  pairs rather than the relationship as a whole.

## Measured on this dataset

| | Plan Rows | Actual Rows | Error |
|---|---|---|---|
| Default statistics | 104 | 16,620 | **160x under** |
| After `CREATE STATISTICS` + `ANALYZE` | 20,746 | 16,620 | 1.25x |

## Why underestimates are the dangerous direction

An overestimate makes the planner too cautious — it might hash-join when a nested
loop would have done. Wasteful, rarely catastrophic.

An **underestimate** makes it too brave. "Only 104 rows on this side, so a nested
loop is cheap" — and then 16,620 rows arrive and the inner side runs 16,620 times
instead of 104. That is how a query goes from 20 ms to 20 minutes, and it is why
estimate error is worth reading *before* wall time.

## Worth trying next

- Drop the `dependencies` kind and keep only `ndistinct`. Does the estimate
  improve? (It should not, for this query — they fix different things.)
- Add a third correlated column to the statistics object and see whether
  `ANALYZE` gets slower. Extended statistics are not free.
- `SELECT * FROM pg_stats_ext;` — read what was actually recorded.
