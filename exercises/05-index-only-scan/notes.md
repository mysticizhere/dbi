# Index-only scans and the visibility map

## What happened

An index entry stores the indexed value and a pointer to the heap tuple. What it
does **not** store is whether that tuple is visible to your snapshot — under MVCC
a row can be deleted, updated, or newer than your transaction started.

So in general, an index scan must visit the heap to check visibility, which
defeats the purpose of an "index-only" scan.

The **visibility map** is the escape hatch: one bit per heap page meaning "every
tuple on this page is visible to every transaction". When the bit is set, the
scan trusts the index and skips the heap. When it is not, it fetches — and that
fetch is counted as `Heap Fetches`.

`VACUUM` is what sets those bits.

## Measured on this dataset

| State | all-visible pages | Heap Fetches |
|---|---|---|
| After `VACUUM` | 100% | 0 |
| After a 300,000-row `UPDATE` | 93.3% | **12,128** |
| After `VACUUM` again | 100% | 0 |

6.7% of pages losing their bit cost 12,128 heap fetches on a query returning
about 200,000 rows.

## Why sandbox mode cannot run this

`VACUUM` cannot run inside a transaction block, and it is not alone:

- `VACUUM`
- `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` / `REINDEX CONCURRENTLY`
- `CREATE DATABASE`, `DROP DATABASE`
- `ALTER SYSTEM`

The workbench detects these and refuses with an explanation rather than letting
the server return a bare `25001`.

## What this means in production

`Heap Fetches` climbing on a hot index-only scan is a signal that autovacuum is
falling behind on that table. The usual causes:

- a long-running transaction holding back the xmin horizon, so `VACUUM` cannot
  mark pages all-visible even when it runs (exercise 11)
- an update-heavy table with default autovacuum thresholds
- a table so large the default `autovacuum_vacuum_scale_factor` (20%) means
  millions of rows of churn before it triggers

## Worth trying next

- Re-run the `UPDATE` and check `Heap Fetches` *without* vacuuming. Does it drift
  as autovacuum eventually catches up?
- `SELECT relallvisible, relpages FROM pg_class WHERE relname = 'events';` — watch
  the ratio move as you update and vacuum.
