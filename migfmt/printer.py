"""Canonical formatting for the AST produced by migfmt.parser.

The output style is fixed on purpose (no config options yet): one column or
constraint per line, four-space indent, uppercase keywords, identifiers quoted
only when they need it. The point is a stable, diffable output, not matching
any one team's existing style.
"""

import re

from .parser import (
    ColumnDef,
    CreateTable,
    DefaultConstraint,
    NotNullConstraint,
    NullConstraint,
    PrimaryKeyConstraint,
    ReferencesConstraint,
    TableForeignKey,
    TablePrimaryKey,
    TableUnique,
    UniqueConstraint,
)

_BARE_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def format_identifier(name: str) -> str:
    if _BARE_IDENT_RE.match(name):
        return name
    return '"{}"'.format(name.replace('"', '""'))


def _format_type(col: ColumnDef) -> str:
    base = col.type_name.upper()
    if col.type_args:
        return f"{base}({', '.join(col.type_args)})"
    return base


def _format_column_constraint(constraint) -> str:
    if isinstance(constraint, NotNullConstraint):
        return "NOT NULL"
    if isinstance(constraint, NullConstraint):
        return "NULL"
    if isinstance(constraint, PrimaryKeyConstraint):
        return "PRIMARY KEY"
    if isinstance(constraint, UniqueConstraint):
        return "UNIQUE"
    if isinstance(constraint, DefaultConstraint):
        return f"DEFAULT {constraint.expression}"
    if isinstance(constraint, ReferencesConstraint):
        if constraint.column:
            return f"REFERENCES {format_identifier(constraint.table)} ({format_identifier(constraint.column)})"
        return f"REFERENCES {format_identifier(constraint.table)}"
    raise TypeError(f"unknown column constraint: {constraint!r}")


def _format_column_def(col: ColumnDef) -> str:
    parts = [format_identifier(col.name), _format_type(col)]
    parts.extend(_format_column_constraint(c) for c in col.constraints)
    return " ".join(parts)


def _constraint_prefix(name: str | None) -> str:
    return f"CONSTRAINT {format_identifier(name)} " if name else ""


def _format_table_constraint(constraint) -> str:
    if isinstance(constraint, TablePrimaryKey):
        cols = ", ".join(format_identifier(c) for c in constraint.columns)
        return f"{_constraint_prefix(constraint.name)}PRIMARY KEY ({cols})"
    if isinstance(constraint, TableUnique):
        cols = ", ".join(format_identifier(c) for c in constraint.columns)
        return f"{_constraint_prefix(constraint.name)}UNIQUE ({cols})"
    if isinstance(constraint, TableForeignKey):
        cols = ", ".join(format_identifier(c) for c in constraint.columns)
        ref_cols = ""
        if constraint.ref_columns:
            ref_cols = " ({})".format(", ".join(format_identifier(c) for c in constraint.ref_columns))
        return (
            f"{_constraint_prefix(constraint.name)}FOREIGN KEY ({cols}) "
            f"REFERENCES {format_identifier(constraint.ref_table)}{ref_cols}"
        )
    raise TypeError(f"unknown table constraint: {constraint!r}")


def pretty_print(stmt: CreateTable) -> str:
    header = "CREATE TABLE "
    if stmt.if_not_exists:
        header += "IF NOT EXISTS "
    header += f"{format_identifier(stmt.name)} ("

    lines = [_format_column_def(c) for c in stmt.columns]
    lines.extend(_format_table_constraint(tc) for tc in stmt.table_constraints)
    body = ",\n".join(f"    {line}" for line in lines)
    return f"{header}\n{body}\n);"


def pretty_print_all(statements) -> str:
    return "\n\n".join(pretty_print(stmt) for stmt in statements)
