"""What the migrations create: tables (CREATE TABLE minus DROP TABLE, renames followed) and APR
keys (config_schema inserts minus deletes), derived by parsing production/migrations/ in order.

Shared by the 185-44 guards (test_table_and_apr_key_readers.py, test_single_writer_registry.py
and test_temporary_allow_list_expiry.py). Filesystem only, no database: the parse is the
CI-clean stand-in for the live catalog. It reads statements, not intent, so a key built by SQL
string concatenation inside a migration (`'a.b.' || tf`) is invisible to it; such keys are
also invisible to the reader guard, which errs toward passing, never toward a false failure.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "production" / "migrations"

_IDENT = r'(?:"?(?:public)"?\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?'
_CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _IDENT, re.IGNORECASE
)
_DROP_TABLE = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([^;]+)", re.IGNORECASE)
_RENAME_TABLE = re.compile(
    r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?"
    + _IDENT
    + r"\s+RENAME\s+TO\s+"
    + r'"?([A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)
_SCHEMA_INSERT = re.compile(r"\bINSERT\s+INTO\s+config_schema\b", re.IGNORECASE)
_SCHEMA_DELETE = re.compile(r"\bDELETE\s+FROM\s+config_schema\b", re.IGNORECASE)
_SCHEMA_RENAME = re.compile(r"\bUPDATE\s+config_schema\s+SET\s+config_key\b", re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'((?:[^']|'')*)'")
_LIKE_LITERAL = re.compile(r"\bLIKE\s+'((?:[^']|'')*)'(?:\s+ESCAPE\s+'(.)')?", re.IGNORECASE)
# APR key shape: <namespace>.<concept>[.<param>...], lower snake segments (tf suffixes allowed).
_APR_KEY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_\-]+)+$")


def migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Every *.sql migration in numeric order (the leading number, then the name)."""

    def order(path: Path) -> tuple[int, str]:
        match = re.match(r"(\d+)", path.name)
        return (int(match.group(1)) if match else 10**9, path.name)

    return sorted(migrations_dir.glob("*.sql"), key=order)


def strip_sql_comments(sql: str) -> str:
    """Drop `--` line comments and `/* */` block comments, leaving string literals intact."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            end = i + 1
            while end < n:
                if sql[end] == "'" and end + 1 < n and sql[end + 1] == "'":
                    end += 2
                    continue
                if sql[end] == "'":
                    break
                end += 1
            out.append(sql[i : end + 1])
            i = end + 1
        elif sql.startswith("--", i):
            newline = sql.find("\n", i)
            i = n if newline == -1 else newline
        elif sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            i = n if close == -1 else close + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _statement_at(sql: str, start: int) -> str:
    """The text from `start` to the first `;` outside a string literal."""
    i, n = start, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                if sql[i] == "'":
                    break
                i += 1
        elif ch == ";":
            return sql[start:i]
        i += 1
    return sql[start:]


def _like_to_regex(pattern: str, escape: str | None) -> re.Pattern[str]:
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if escape and ch == escape and i + 1 < len(pattern):
            parts.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        parts.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.compile("^" + "".join(parts) + "$")


def _literals(statement: str) -> list[str]:
    return [m.group(1).replace("''", "'") for m in _STRING_LITERAL.finditer(statement)]


def _apr_literals(statement: str) -> list[str]:
    return [lit for lit in _literals(statement) if _APR_KEY.match(lit)]


def _events(sql: str) -> list[tuple[int, str, str]]:
    """(offset, kind, statement) for every table or APR event in one migration, in file order."""
    events: list[tuple[int, str, str]] = []
    for kind, pattern in (
        ("create", _CREATE_TABLE),
        ("drop", _DROP_TABLE),
        ("rename", _RENAME_TABLE),
        ("key_insert", _SCHEMA_INSERT),
        ("key_delete", _SCHEMA_DELETE),
        ("key_rename", _SCHEMA_RENAME),
    ):
        for match in pattern.finditer(sql):
            events.append((match.start(), kind, _statement_at(sql, match.start())))
    events.sort(key=lambda event: event[0])
    return events


def catalog(files: Iterable[Path]) -> tuple[set[str], set[str]]:
    """(tables, apr_keys) left standing after applying every migration in order."""
    tables: set[str] = set()
    keys: set[str] = set()
    for path in files:
        sql = strip_sql_comments(path.read_text(encoding="utf-8", errors="ignore"))
        for _, kind, statement in _events(sql):
            if kind == "create":
                match = _CREATE_TABLE.match(statement)
                if match:
                    tables.add(match.group(1).lower())
            elif kind == "drop":
                match = _DROP_TABLE.match(statement)
                if match:
                    names = re.sub(r"\b(CASCADE|RESTRICT)\b", "", match.group(1), flags=re.I)
                    for name in names.split(","):
                        tables.discard(name.strip().strip('"').split(".")[-1].strip('"').lower())
            elif kind == "rename":
                match = _RENAME_TABLE.match(statement)
                if match and match.group(1).lower() in tables:
                    tables.discard(match.group(1).lower())
                    tables.add(match.group(2).lower())
            elif kind == "key_insert":
                keys.update(_apr_literals(statement))
            elif kind == "key_delete":
                keys.difference_update(_apr_literals(statement))
                for like in _LIKE_LITERAL.finditer(statement):
                    regex = _like_to_regex(like.group(1), like.group(2))
                    keys.difference_update({key for key in keys if regex.match(key)})
            elif kind == "key_rename":
                found = _apr_literals(statement)
                if len(found) == 2 and found[1] in keys:
                    keys.discard(found[1])
                    keys.add(found[0])
    return tables, keys


def migration_catalog(migrations_dir: Path = MIGRATIONS_DIR) -> tuple[set[str], set[str]]:
    return catalog(migration_files(migrations_dir))
