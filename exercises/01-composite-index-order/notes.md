# Composite index column order

## What happened

A B+tree index on `(city, score)` is sorted by `city` first, and only by `score`
*within* each city. There are 200 cities, so the ~20,000 rows matching
`score < 2000` are spread across 200 separate ranges of the index. There is no
single contiguous span to seek to, so the planner correctly decides that reading
the whole heap sequentially is cheaper than a scattered index traversal.

Swap the column order and the same 20,000 rows become one contiguous run.

## Measured on this dataset

| Index | Plan | Blocks touched |
|---|---|---|
| `(city, score)` | Parallel Seq Scan | ~194,000 |
| `(score)` | Index Only Scan | ~10,000 |

About 20x less work for the same answer.

## The rule

An index on `(a, b)` can serve:

- `WHERE a = ...`
- `WHERE a = ... AND b = ...`
- `WHERE a = ... ORDER BY b`

but **not** `WHERE b = ...` on its own — not efficiently. The leading column is
the one that has to appear in the predicate.

## Worth trying next

- Does `(score, city)` work as well as `(score)` for this query? Compare blocks.
  It should be close, but the index is physically larger, so slightly worse.
- Now query `WHERE city = 'Mumbai North' AND score < 2000`. Which of the three
  indexes wins, and why?
