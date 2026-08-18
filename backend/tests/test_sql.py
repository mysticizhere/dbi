"""Tests for statement splitting and classification.

A semicolon inside a string or a comment must not end a statement -- getting
this wrong would silently truncate a user's setup DDL and produce a confusing
plan rather than an error.
"""

from __future__ import annotations

import pytest

from app.sql import (
    is_explainable,
    non_transactional_reason,
    split_statements,
    strip_leading_comments,
)


def test_splits_on_plain_semicolons() -> None:
    assert split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]


def test_drops_empty_statements_and_trailing_semicolon() -> None:
    assert split_statements("SELECT 1;;  ;\n") == ["SELECT 1"]
    assert split_statements("   \n  ") == []


def test_semicolon_inside_a_string_is_not_a_boundary() -> None:
    stmts = split_statements("SELECT 'a;b' AS x; SELECT 2")
    assert stmts == ["SELECT 'a;b' AS x", "SELECT 2"]


def test_doubled_quote_is_an_escaped_quote() -> None:
    assert split_statements("SELECT 'it''s; fine'") == ["SELECT 'it''s; fine'"]


def test_backslash_escapes_only_apply_to_e_strings() -> None:
    # In a plain string standard_conforming_strings means \' does NOT escape,
    # so the literal ends at the second quote and the semicolon does split.
    assert len(split_statements(r"SELECT 'a\'; SELECT 2")) == 2
    # In an E-string the backslash does escape, so it is all one statement.
    assert len(split_statements(r"SELECT E'a\'; SELECT 2'")) == 1


def test_quoted_identifiers_are_respected() -> None:
    assert split_statements('SELECT 1 AS "a;b"; SELECT 2') == ['SELECT 1 AS "a;b"', "SELECT 2"]


def test_semicolon_in_a_line_comment_is_ignored() -> None:
    assert split_statements("SELECT 1 -- ; not a boundary\n; SELECT 2") == [
        "SELECT 1 -- ; not a boundary",
        "SELECT 2",
    ]


def test_semicolon_in_a_block_comment_is_ignored() -> None:
    assert split_statements("SELECT /* ; */ 1; SELECT 2") == ["SELECT /* ; */ 1", "SELECT 2"]


def test_block_comments_nest() -> None:
    # Postgres nests these, unlike C. An unbalanced count would end the comment
    # early and treat SQL text as code.
    assert split_statements("SELECT /* a /* ; */ b ; */ 1; SELECT 2") == [
        "SELECT /* a /* ; */ b ; */ 1",
        "SELECT 2",
    ]


def test_dollar_quoted_bodies_are_opaque() -> None:
    body = "CREATE FUNCTION f() RETURNS int AS $$ BEGIN; RETURN 1; END; $$ LANGUAGE plpgsql"
    assert split_statements(body + "; SELECT 1") == [body, "SELECT 1"]


def test_tagged_dollar_quotes() -> None:
    body = "SELECT $tag$ ; $notatag$ ; $tag$"
    assert split_statements(body + "; SELECT 1") == [body, "SELECT 1"]


def test_bare_dollar_is_not_a_quote() -> None:
    # $1 is a parameter placeholder, not the start of a dollar-quoted body.
    assert split_statements("SELECT $1; SELECT 2") == ["SELECT $1", "SELECT 2"]


def test_unterminated_string_yields_one_statement() -> None:
    # Let the server produce the syntax error rather than guessing here.
    assert split_statements("SELECT 'oops; SELECT 2") == ["SELECT 'oops; SELECT 2"]


# --- transaction-hostile statements ----------------------------------------


@pytest.mark.parametrize(
    "stmt,expected",
    [
        ("CREATE INDEX CONCURRENTLY i ON t(a)", "CREATE INDEX CONCURRENTLY"),
        ("create   index\n concurrently i ON t(a)", "CREATE INDEX CONCURRENTLY"),
        ("DROP INDEX CONCURRENTLY i", "DROP INDEX CONCURRENTLY"),
        ("REINDEX INDEX CONCURRENTLY i", "REINDEX CONCURRENTLY"),
        ("VACUUM ANALYZE events", "VACUUM"),
        ("ALTER SYSTEM SET work_mem = '64MB'", "ALTER SYSTEM"),
        ("-- comment\nCREATE INDEX CONCURRENTLY i ON t(a)", "CREATE INDEX CONCURRENTLY"),
        ("/* c */ VACUUM", "VACUUM"),
    ],
)
def test_detects_non_transactional_statements(stmt: str, expected: str) -> None:
    assert non_transactional_reason(stmt) == expected


@pytest.mark.parametrize(
    "stmt",
    [
        "CREATE INDEX i ON t(a)",
        "SELECT 1",
        "ANALYZE events",  # ANALYZE is fine in a transaction; VACUUM is not
        "REINDEX INDEX i",
        "SELECT 'CREATE INDEX CONCURRENTLY'",
    ],
)
def test_allows_transactional_statements(stmt: str) -> None:
    assert non_transactional_reason(stmt) is None


# --- explainability ---------------------------------------------------------


@pytest.mark.parametrize(
    "stmt",
    [
        "SELECT 1",
        "  select 1",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "VALUES (1)",
        "TABLE events",
        "CREATE TABLE t2 AS SELECT * FROM t",
        "CREATE MATERIALIZED VIEW mv AS SELECT 1",
        "-- lead comment\nSELECT 1",
    ],
)
def test_explainable(stmt: str) -> None:
    assert is_explainable(stmt)


@pytest.mark.parametrize(
    "stmt",
    [
        "CREATE INDEX i ON t(a)",
        "CREATE TABLE t (a int)",
        "ANALYZE events",
        "SET work_mem = '64MB'",
        "DROP TABLE t",
        "",
    ],
)
def test_not_explainable(stmt: str) -> None:
    assert not is_explainable(stmt)


def test_strip_leading_comments() -> None:
    assert strip_leading_comments("  -- a\n /* b */\n SELECT 1") == "SELECT 1"
    assert strip_leading_comments("SELECT 1") == "SELECT 1"


def test_comment_only_fragments_are_not_statements() -> None:
    # A trailing block of commented-out examples must not become the target.
    sql = """
    SELECT 1;

    -- Then try this instead:
    --   CREATE INDEX i ON t(a);
    --   SELECT count(*) FROM t;
    """
    assert split_statements(sql) == ["SELECT 1"]


def test_comment_only_input_yields_nothing() -> None:
    assert split_statements("-- just a note\n/* and a block */") == []


def test_comments_between_statements_attach_to_the_next_one() -> None:
    stmts = split_statements("SELECT 1;\n-- about the second\nSELECT 2;")
    assert len(stmts) == 2
    assert stmts[1].endswith("SELECT 2")
