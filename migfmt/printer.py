"""Canonical formatting for the AST produced by migfmt.parser.

The output style is fixed on purpose (no config options yet): one column or
constraint per line, four-space indent, uppercase keywords, identifiers quoted
only when they need it. The point is a stable, diffable output, not matching
any one team's existing style.
"""

import re

from .parser import (
    AddColumn,
    AlterTable,
    ColumnDef,
    CreateIndex,
    CreateTable,
    DefaultConstraint,
    DropColumn,
    DropTable,
    NotNullConstraint,
    NullConstraint,
    PrimaryKeyConstraint,
    ReferencesConstraint,
    RenameColumn,
    RenameTable,
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


def _pretty_print_create_table(stmt: CreateTable) -> str:
    header = "CREATE TABLE "
    if stmt.if_not_exists:
        header += "IF NOT EXISTS "
    header += f"{format_identifier(stmt.name)} ("

    lines = [_format_column_def(c) for c in stmt.columns]
    lines.extend(_format_table_constraint(tc) for tc in stmt.table_constraints)
    body = ",\n".join(f"    {line}" for line in lines)
    return f"{header}\n{body}\n);"


def _format_alter_action(action) -> str:
    if isinstance(action, AddColumn):
        return f"ADD COLUMN {_format_column_def(action.column)}"
    if isinstance(action, DropColumn):
        if_exists = "IF EXISTS " if action.if_exists else ""
        return f"DROP COLUMN {if_exists}{format_identifier(action.name)}"
    if isinstance(action, RenameColumn):
        return (
            f"RENAME COLUMN {format_identifier(action.old_name)} "
            f"TO {format_identifier(action.new_name)}"
        )
    if isinstance(action, RenameTable):
        return f"RENAME TO {format_identifier(action.new_name)}"
    raise TypeError(f"unknown alter action: {action!r}")


def _pretty_print_alter_table(stmt: AlterTable) -> str:
    header = f"ALTER TABLE {format_identifier(stmt.name)}"
    actions = [_format_alter_action(a) for a in stmt.actions]
    if len(actions) == 1:
        return f"{header} {actions[0]};"
    body = ",\n".join(f"    {action}" for action in actions)
    return f"{header}\n{body};"


def _pretty_print_create_index(stmt: CreateIndex) -> str:
    header = "CREATE "
    if stmt.unique:
        header += "UNIQUE "
    header += "INDEX "
    if stmt.if_not_exists:
        header += "IF NOT EXISTS "
    cols = ", ".join(format_identifier(c) for c in stmt.columns)
    header += (
        f"{format_identifier(stmt.name)} ON {format_identifier(stmt.table)} ({cols})"
    )
    return f"{header};"


def _pretty_print_drop_table(stmt: DropTable) -> str:
    if_exists = "IF EXISTS " if stmt.if_exists else ""
    return f"DROP TABLE {if_exists}{format_identifier(stmt.name)};"


def pretty_print(stmt) -> str:
    if isinstance(stmt, CreateTable):
        return _pretty_print_create_table(stmt)
    if isinstance(stmt, AlterTable):
        return _pretty_print_alter_table(stmt)
    if isinstance(stmt, CreateIndex):
        return _pretty_print_create_index(stmt)
    if isinstance(stmt, DropTable):
        return _pretty_print_drop_table(stmt)
    raise TypeError(f"unknown statement type: {stmt!r}")


def pretty_print_all(statements) -> str:
    return "\n\n".join(pretty_print(stmt) for stmt in statements)
