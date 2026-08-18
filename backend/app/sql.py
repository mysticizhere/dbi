"""Lexical handling of user-submitted SQL.

A lab run is usually a small script -- some setup DDL, then the query under
test -- so we have to split it on statement boundaries without being fooled by
semicolons inside strings, comments or dollar-quoted bodies. Postgres has
exactly five such lexical forms, and this module handles all five rather than
pulling in a general SQL parser we would only use for `split`.
"""

from __future__ import annotations

import re

_IDENT_CHAR = re.compile(r"[A-Za-z0-9_]")
_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")

_EXPLAINABLE_VERBS = frozenset(
    {"select", "insert", "update", "delete", "merge", "values", "table", "with",
     "execute", "declare"}
)

# Statements Postgres refuses to run inside a transaction block. In sandbox mode
# the whole run is wrapped in BEGIN..ROLLBACK, so these have to be rejected with
# an explanation rather than a raw 25001 from the server.
_NON_TRANSACTIONAL = [
    (re.compile(r"^\s*create\s+index\s+concurrently\b", re.I), "CREATE INDEX CONCURRENTLY"),
    (re.compile(r"^\s*drop\s+index\s+concurrently\b", re.I), "DROP INDEX CONCURRENTLY"),
    (re.compile(r"^\s*reindex\b.*\bconcurrently\b", re.I | re.S), "REINDEX CONCURRENTLY"),
    (re.compile(r"^\s*vacuum\b", re.I), "VACUUM"),
    (re.compile(r"^\s*create\s+database\b", re.I), "CREATE DATABASE"),
    (re.compile(r"^\s*drop\s+database\b", re.I), "DROP DATABASE"),
    (re.compile(r"^\s*alter\s+system\b", re.I), "ALTER SYSTEM"),
    (re.compile(r"^\s*create\s+tablespace\b", re.I), "CREATE TABLESPACE"),
]


def _skip_quoted(sql: str, i: int, quote: str, backslash_escapes: bool) -> int:
    """Return the index just past a '...' or "..." literal starting at `i`."""
    j = i + 1
    n = len(sql)
    while j < n:
        c = sql[j]
        if backslash_escapes and c == "\\" and j + 1 < n:
            j += 2
            continue
        if c == quote:
            # A doubled quote is an escaped quote, not the end.
            if j + 1 < n and sql[j + 1] == quote:
                j += 2
                continue
            return j + 1
        j += 1
    return n  # unterminated; let the server produce the error


def _skip_block_comment(sql: str, i: int) -> int:
    """Return the index just past a /* ... */ comment. Postgres nests these."""
    depth = 0
    j = i
    n = len(sql)
    while j < n - 1:
        pair = sql[j : j + 2]
        if pair == "/*":
            depth += 1
            j += 2
        elif pair == "*/":
            depth -= 1
            j += 2
            if depth == 0:
                return j
        else:
            j += 1
    return n


def _is_e_string(sql: str, i: int) -> bool:
    """True if the quote at `i` opens an E'...' escape string."""
    if i == 0 or sql[i - 1] not in "eE":
        return False
    return i - 1 == 0 or not _IDENT_CHAR.match(sql[i - 2])


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into statements, dropping empties.

    Semicolons inside strings, identifiers, comments and dollar-quoted bodies do
    not terminate a statement.
    """
    out: list[str] = []
    start = 0
    i = 0
    n = len(sql)

    while i < n:
        c = sql[i]

        if c == "'":
            i = _skip_quoted(sql, i, "'", backslash_escapes=_is_e_string(sql, i))
        elif c == '"':
            i = _skip_quoted(sql, i, '"', backslash_escapes=False)
        elif c == "-" and sql.startswith("--", i):
            nl = sql.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif c == "/" and sql.startswith("/*", i):
            i = _skip_block_comment(sql, i)
        elif c == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                close = sql.find(m.group(0), m.end())
                i = n if close == -1 else close + len(m.group(0))
            else:
                i += 1
        elif c == ";":
            _append(out, sql[start:i])
            i += 1
            start = i
        else:
            i += 1

    _append(out, sql[start:])
    return out


def _append(out: list[str], raw: str) -> None:
    """Keep a fragment only if it contains actual SQL.

    A trailing block of commented-out examples is not a statement. Emitting one
    would make it the *target* -- the thing that gets EXPLAINed -- and the run
    would fail with a baffling "EXPLAIN only accepts SELECT..." on text the user
    had deliberately commented out.
    """
    stmt = raw.strip()
    if stmt and strip_leading_comments(stmt):
        out.append(stmt)


def strip_leading_comments(stmt: str) -> str:
    """Drop leading comments and whitespace, so keyword matching sees the verb."""
    i = 0
    n = len(stmt)
    while i < n:
        if stmt[i].isspace():
            i += 1
        elif stmt.startswith("--", i):
            nl = stmt.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif stmt.startswith("/*", i):
            i = _skip_block_comment(stmt, i)
        else:
            break
    return stmt[i:]


def non_transactional_reason(stmt: str) -> str | None:
    """Name the construct that cannot run inside a transaction block, if any."""
    head = strip_leading_comments(stmt)
    for pattern, label in _NON_TRANSACTIONAL:
        if pattern.match(head):
            return label
    return None


def is_explainable(stmt: str) -> bool:
    """True if EXPLAIN accepts this statement.

    Postgres only EXPLAINs SELECT / INSERT / UPDATE / DELETE / MERGE / VALUES /
    DECLARE / CREATE TABLE AS / CREATE MATERIALIZED VIEW AS / EXECUTE.
    """
    head = strip_leading_comments(stmt).lstrip("(").lstrip()
    verb = re.match(r"[A-Za-z]+", head)
    if verb is None:
        return False
    first = verb.group(0).lower()
    if first in _EXPLAINABLE_VERBS:
        return True
    if first == "create":
        return bool(re.match(r"create\s+(table|materialized\s+view)\b.*\bas\b", head, re.I | re.S))
    return False
