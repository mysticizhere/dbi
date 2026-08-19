# The selectivity crossover

## Why a crossover exists at all

A sequential scan reads every page once, in physical order, and the OS can
read ahead. An index scan reads a little of the index and then jumps to the heap
once per matching row, in whatever order the index gives — random I/O, and the
same page may be visited many times.

So the index wins when "a little of the index plus a few random heap visits" is
less work than "every page in order". Past some fraction of the table, it isn't.

## Measured on this dataset

`SELECT sum(pincode) FROM events WHERE score < N`, at the default
`random_page_cost = 4`:

| Threshold | Selectivity | Plan | Blocks touched |
|---|---|---|---|
| 20,000 | 0.2% | Bitmap Heap Scan | ~125,000 |
| 100,000 | 1% | **Seq Scan** | ~194,000 |
| 200,000 | 2% | Seq Scan | ~194,000 |
| 500,000 | 5% | Seq Scan | ~194,000 |

The crossover sits between 0.2% and 1%.

Note the seq scan number barely moves: it reads the whole table regardless of how
selective the predicate is. That flat line is the thing to remember.

## Part two: random_page_cost

`random_page_cost` (default `4`) is the planner's estimate of how much more
expensive a random page fetch is than a sequential one. On SSDs the real ratio is
much closer to 1, so lowering it is standard advice.

Try it:

```sql
SET LOCAL random_page_cost = 1.1;
SELECT sum(pincode) FROM events WHERE score < 200000;
```

The plan flips from Seq Scan to Index Scan — the crossover moved from ~0.5% out
to ~3%, exactly as advertised.

Now look at the blocks:

| Setting | Plan | Blocks touched |
|---|---|---|
| `random_page_cost = 4` | Seq Scan | ~194,000 |
| `random_page_cost = 1.1` | Index Scan | **~2,000,000** |

**The "tuned" setting made it ten times worse.** At 2% selectivity the index scan
visits the heap 2 million times, and the same pages over and over, because the
rows are scattered. The planner did what it was told; it was told something
false for *this* query.

This is the honest lesson: `random_page_cost = 1.1` is usually right on SSDs, and
it is still capable of choosing a plan an order of magnitude worse. Settings are
inputs to a cost model, not improvements.

## Worth trying next

- Add `id` to the index (`CREATE INDEX ON events (score) INCLUDE (pincode)`), so
  the query can be answered index-only. Where does the crossover move to?
- Run the same sweep on a column with a *skewed* distribution, e.g. `user_id`.
  Does a single crossover point even exist there?
