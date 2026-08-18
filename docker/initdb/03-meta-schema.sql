-- lab_meta schema (spec section 5).
--
-- Single source of truth: docker's initdb runs this on first boot, and the
-- backend re-applies it on every startup. Everything here must therefore stay
-- idempotent, so that schema changes land without wiping the volume.

CREATE TABLE IF NOT EXISTS attempts (
  id            bigserial PRIMARY KEY,
  exercise_id   text NOT NULL,
  sql           text NOT NULL,
  plan_json     jsonb,
  passed        boolean NOT NULL,
  assertions    jsonb NOT NULL,   -- per-assertion result + observed value
  median_ms     double precision,
  shared_hit    bigint,
  shared_read   bigint,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS attempts_exercise_created_idx
  ON attempts (exercise_id, created_at DESC);

CREATE TABLE IF NOT EXISTS benchmarks (
  id          bigserial PRIMARY KEY,
  name        text NOT NULL,
  spec        jsonb NOT NULL,
  status      text NOT NULL,      -- pending | running | done | failed
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS benchmark_points (
  benchmark_id bigint REFERENCES benchmarks(id) ON DELETE CASCADE,
  series       text NOT NULL,
  x            double precision NOT NULL,
  median_ms    double precision,
  p25_ms       double precision,
  p75_ms       double precision,
  shared_hit   bigint,
  shared_read  bigint,
  node_type    text,
  PRIMARY KEY (benchmark_id, series, x)
);

CREATE TABLE IF NOT EXISTS notes (
  id          bigserial PRIMARY KEY,
  exercise_id text,
  body_md     text NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Spec section 6: "record row counts + relation sizes to lab_meta" after seeding.
CREATE TABLE IF NOT EXISTS seed_runs (
  id          bigserial PRIMARY KEY,
  scale       text NOT NULL,           -- 1m | 10m | 100m
  seed        bigint NOT NULL,         -- RNG seed, so a scale is reproducible
  relations   jsonb NOT NULL,          -- [{relation, rows, total_bytes, index_bytes}]
  duration_s  double precision,
  created_at  timestamptz NOT NULL DEFAULT now()
);
