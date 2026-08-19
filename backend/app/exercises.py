"""Loads exercises from disk (spec F4, conventions section 9).

    exercises/
      05-index-only-scan/
        exercise.yaml
        setup.sql
        solution.sql
        notes.md

Files, not database rows -- so they diff, review and hand-edit like code. They
are re-read on every request rather than cached: there are a handful of small
files, and an edit showing up immediately is worth more than the microseconds.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config import REPO_ROOT
from app.models.exercise import Exercise, ExerciseMeta

EXERCISES_DIR = REPO_ROOT / "exercises"

_YAML_NAME = "exercise.yaml"
class ExerciseLoadError(Exception):
    """A malformed exercise directory. Names the file, so it is fixable."""


def _read_optional(directory: Path, filename: str) -> str:
    path = directory / filename
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def load_exercise(directory: Path) -> Exercise:
    manifest = directory / _YAML_NAME
    if not manifest.is_file():
        raise ExerciseLoadError(f"{directory.name}: no {_YAML_NAME}")

    try:
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExerciseLoadError(f"{directory.name}/{_YAML_NAME}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ExerciseLoadError(f"{directory.name}/{_YAML_NAME}: expected a mapping")

    try:
        meta = ExerciseMeta.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, reported verbatim
        raise ExerciseLoadError(f"{directory.name}/{_YAML_NAME}: {exc}") from exc

    return Exercise(
        **meta.model_dump(),
        slug=directory.name,
        setup_sql=_read_optional(directory, "setup.sql"),
        solution_sql=_read_optional(directory, "solution.sql"),
        notes_md=_read_optional(directory, "notes.md"),
    )


def load_all(root: Path | None = None) -> list[Exercise]:
    """Every exercise, ordered by directory name.

    The numeric prefix on each directory is the running order, which is why the
    sort is on the directory name rather than the id.
    """
    base = root or EXERCISES_DIR
    if not base.is_dir():
        return []

    found: list[Exercise] = []
    seen: dict[str, str] = {}
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        if not (directory / _YAML_NAME).is_file():
            continue  # not an exercise directory; ignore quietly
        exercise = load_exercise(directory)
        if exercise.id in seen:
            raise ExerciseLoadError(
                f"duplicate exercise id '{exercise.id}' in {seen[exercise.id]} "
                f"and {directory.name}"
            )
        seen[exercise.id] = directory.name
        found.append(exercise)
    return found


def get(exercise_id: str, root: Path | None = None) -> Exercise | None:
    return next((e for e in load_all(root) if e.id == exercise_id), None)
