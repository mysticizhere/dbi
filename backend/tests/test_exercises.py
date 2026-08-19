"""Exercise loader tests.

A broken exercise file must fail loudly at load time. The alternative -- loading
a half-parsed exercise and grading nothing -- looks like a pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import exercises as store
from app.exercises import ExerciseLoadError

VALID_YAML = """\
id: demo
title: A demo exercise
layer: 3
difficulty: 2
prompt: |
  Do the thing.
starting_query: |
  SELECT 1;
hints:
  - first hint
assertions:
  - type: no_node
    node_type: Seq Scan
    relation: events
"""


def write_exercise(root: Path, slug: str, yaml_text: str = VALID_YAML, **files: str) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "exercise.yaml").write_text(yaml_text, encoding="utf-8")
    for name, content in files.items():
        (directory / f"{name}.sql" if name != "notes" else directory / "notes.md").write_text(
            content, encoding="utf-8"
        )
    return directory


def test_loads_a_valid_exercise(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-demo", setup="CREATE INDEX i ON t(a);", notes="# notes")
    found = store.load_all(tmp_path)
    assert len(found) == 1
    e = found[0]
    assert e.id == "demo"
    assert e.slug == "01-demo"
    assert e.setup_sql.startswith("CREATE INDEX")
    assert e.notes_md == "# notes"
    assert e.solution_sql == ""  # optional file, absent


def test_orders_by_directory_name_not_id(tmp_path: Path) -> None:
    # The numeric prefix is the running order; ids are not sortable.
    write_exercise(tmp_path, "07-zulu", VALID_YAML.replace("id: demo", "id: zulu"))
    write_exercise(tmp_path, "01-alpha", VALID_YAML.replace("id: demo", "id: alpha"))
    assert [e.slug for e in store.load_all(tmp_path)] == ["01-alpha", "07-zulu"]


def test_ignores_directories_without_a_manifest(tmp_path: Path) -> None:
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "notes.md").write_text("wip", encoding="utf-8")
    write_exercise(tmp_path, "01-demo")
    assert len(store.load_all(tmp_path)) == 1


def test_missing_directory_is_empty_not_an_error(tmp_path: Path) -> None:
    assert store.load_all(tmp_path / "nope") == []


def test_malformed_yaml_names_the_file(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-bad", "id: demo\n  bad: [indent\n")
    with pytest.raises(ExerciseLoadError, match="01-bad/exercise.yaml"):
        store.load_all(tmp_path)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-bad", VALID_YAML.replace("title: A demo exercise\n", ""))
    with pytest.raises(ExerciseLoadError, match="title"):
        store.load_all(tmp_path)


def test_unknown_assertion_type_is_rejected(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-bad", VALID_YAML.replace("type: no_node", "type: no_seq_scan"))
    with pytest.raises(ExerciseLoadError, match="no_seq_scan"):
        store.load_all(tmp_path)


def test_assertion_missing_its_value_is_rejected(tmp_path: Path) -> None:
    broken = VALID_YAML.replace(
        "  - type: no_node\n    node_type: Seq Scan\n    relation: events\n",
        "  - type: max_total_blocks\n",
    )
    write_exercise(tmp_path, "01-bad", broken)
    with pytest.raises(ExerciseLoadError, match="requires a 'value'"):
        store.load_all(tmp_path)


def test_exercise_with_no_assertions_is_rejected(tmp_path: Path) -> None:
    broken = VALID_YAML.split("assertions:")[0] + "assertions: []\n"
    write_exercise(tmp_path, "01-bad", broken)
    with pytest.raises(ExerciseLoadError):
        store.load_all(tmp_path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-one")
    write_exercise(tmp_path, "02-two")
    with pytest.raises(ExerciseLoadError, match="duplicate exercise id 'demo'"):
        store.load_all(tmp_path)


def test_yaml_that_is_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-bad", "- just\n- a\n- list\n")
    with pytest.raises(ExerciseLoadError, match="expected a mapping"):
        store.load_all(tmp_path)


def test_get_by_id(tmp_path: Path) -> None:
    write_exercise(tmp_path, "01-demo")
    assert store.get("demo", tmp_path) is not None
    assert store.get("nope", tmp_path) is None


# --- the exercises actually shipped in this repo ----------------------------


def test_shipped_exercises_all_load() -> None:
    found = store.load_all()
    assert found, "no exercises found -- did the exercises/ directory move?"
    for e in found:
        assert e.prompt.strip(), f"{e.slug}: empty prompt"
        assert e.assertions, f"{e.slug}: no assertions"


def test_shipped_exercises_have_a_solution_and_notes() -> None:
    for e in store.load_all():
        assert e.solution_sql.strip(), f"{e.slug}: solution.sql is empty"
        assert e.notes_md.strip(), f"{e.slug}: notes.md is empty"
        assert e.starting_query.strip(), f"{e.slug}: no starting_query"


def test_shipped_exercises_have_unique_ids_and_slugs() -> None:
    found = store.load_all()
    assert len({e.id for e in found}) == len(found)
    assert len({e.slug for e in found}) == len(found)


def test_shipped_exercises_avoid_time_based_assertions() -> None:
    """Wall-clock thresholds are flaky across machines; buffers are not.

    Not a hard ban -- the assertion type exists -- but the seeded set should not
    rely on one, or the suite becomes machine-dependent.
    """
    for e in store.load_all():
        for a in e.assertions:
            assert a.type != "max_total_time_ms", f"{e.slug} uses a wall-clock assertion"
