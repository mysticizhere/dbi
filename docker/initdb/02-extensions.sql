-- pg_stat_statements is cluster-wide, but the views only exist in databases
-- where the extension is installed -- so install it in both.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

\connect lab_data

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pageinspect;     -- F3 mode A: real B+tree walking
CREATE EXTENSION IF NOT EXISTS pgstattuple;     -- F6: bloat measurement
CREATE EXTENSION IF NOT EXISTS pg_prewarm;      -- F1: warm-cache runs
CREATE EXTENSION IF NOT EXISTS pg_buffercache;  -- F6: what is actually cached
CREATE EXTENSION IF NOT EXISTS hypopg;          -- F6: hypothetical indexes
