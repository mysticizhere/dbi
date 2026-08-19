# Sargability

## What happened

An index on `email` stores the values as written: `Known.User@Example.com`. The
query asks for rows where `lower(email)` equals a lowercase string. Postgres
cannot assume `lower()` preserves the index's ordering — for a general function
it does not — so the index is unusable and the only option is to read every row
and apply the function.

An **expression index** stores the computed value instead, so the predicate
matches the index exactly.

## Measured on this dataset

| Index | Plan | Blocks touched |
|---|---|---|
| `(email)` | Parallel Seq Scan | ~194,000 |
| `(lower(email))` | Bitmap Index Scan | **5** |

Roughly 39,000x less work.

## The general shape

Any function or arithmetic wrapped around an indexed **column** kills the index:

```sql
WHERE lower(email) = ...           -- needs an index on lower(email)
WHERE created_at::date = ...       -- needs a range predicate, or an index on the cast
WHERE score + 1 > 100              -- rewrite as score > 99
WHERE extract(year from created_at) = 2024
```

The last one is worth internalising: rewrite it as a range instead.

```sql
WHERE created_at >= '2024-01-01' AND created_at < '2025-01-01'
```

That form uses a plain index on `created_at`, needs no extra index, and stays
correct across time zones in a way `extract` does not.

Functions on the **literal** side are fine — they are evaluated once, before the
scan. It is only functions on the column that hurt.

## Worth trying next

- Add `WHERE lower(email) LIKE 'known.%'`. Does the expression index still help?
  (Prefix `LIKE` needs `text_pattern_ops` unless the database collation is C.
  This lab runs with `--locale=C`, so it works here and might not on your server.)
