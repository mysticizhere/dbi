-- The playground. Disposable by design: `lab.ps1 reset` drops and recreates it.
-- lab_meta is created by the entrypoint from POSTGRES_DB.
CREATE DATABASE lab_data;

COMMENT ON DATABASE lab_meta IS 'Perf Lab application state: attempts, benchmarks, notes.';
COMMENT ON DATABASE lab_data IS 'Perf Lab playground. All user SQL runs here. Safe to drop.';
