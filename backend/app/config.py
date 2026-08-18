"""Runtime configuration.

Local-only single-user app: defaults are the docker-compose values, and the
password is deliberately trivial because the port is bound to 127.0.0.1.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAB_", env_file=".env", extra="ignore")

    # Host port 5433: the native postgresql-x64-17 Windows service owns 5432.
    meta_dsn: str = "postgresql://lab:lab@127.0.0.1:5433/lab_meta"
    data_dsn: str = "postgresql://lab:lab@127.0.0.1:5433/lab_data"

    host: str = "127.0.0.1"
    port: int = 8000

    # Vite dev server, for CORS during development.
    frontend_origin: str = "http://127.0.0.1:5173"

    # F1 defaults.
    statement_timeout_ms: int = 30_000
    max_statement_timeout_ms: int = 600_000
    result_row_cap: int = 200
    default_repeat: int = 5

    # F2 warning thresholds. Tunable because "large" depends on the machine, but
    # the defaults are the ones the spec names.
    estimate_error_threshold: float = 10.0
    estimate_error_critical: float = 100.0
    # 1000 pages = 8MB. Below that a seq scan is usually the right call anyway.
    seq_scan_pages_threshold: int = 1000
    nested_loop_loops_threshold: int = 1000
    filter_discard_ratio: float = 10.0
    filter_discard_min_rows: int = 1000

    @property
    def meta_schema_path(self) -> Path:
        return REPO_ROOT / "docker" / "initdb" / "03-meta-schema.sql"


settings = Settings()
