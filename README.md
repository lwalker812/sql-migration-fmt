# sql-migration-fmt

A validating parser and pretty printer for `CREATE TABLE` statements, aimed
at SQL migration files.

## The problem

Migration files get written by hand, one at a time, over years, often by
different people with different habits: some quote identifiers, some don't;
some put a trailing comma on the last column, some don't; keyword casing
drifts. None of that is wrong, but it makes diffs noisy and makes it easy to
miss real mistakes in review — a duplicate column name, two primary keys on
the same table, a `UNIQUE` constraint that references a column which was
renamed and no longer exists.

This project parses `CREATE TABLE` statements into a small AST, checks the
result for that second class of mistake, and can re-emit the statement in one
fixed canonical style so migrations stop varying for reasons that have
nothing to do with the schema.

## Usage

```python
from migfmt import parse_sql, pretty_print, ParseError, ValidationError

sql = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id)
);
"""

try:
    statements = parse_sql(sql)
except ParseError as exc:
    print(f"syntax error: {exc}")
except ValidationError as exc:
    print(f"invalid schema: {exc}")
else:
    for stmt in statements:
        print(pretty_print(stmt))
```

Output is normalized regardless of how the input was written — keyword case,
identifier quoting style, and whitespace all collapse to one form:

```sql
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id)
);
```

## What's checked

The parser accepts standard `CREATE TABLE` syntax: column definitions with
typed arguments (`VARCHAR(255)`, `NUMERIC(10, 2)`), `NOT NULL` / `NULL` /
`PRIMARY KEY` / `UNIQUE` / `DEFAULT <expr>` / `REFERENCES` on columns, and
table-level `PRIMARY KEY (...)`, `UNIQUE (...)`, and `FOREIGN KEY (...)
REFERENCES ...`, optionally named with `CONSTRAINT`. It understands both
`"double quoted"` and `` `backtick quoted` `` identifiers, `--` and `/* */`
comments, and `''`-escaped string literals.

On top of syntax, `parse_sql` validates:

- no two columns share a name (case-insensitively)
- no table ends up with more than one primary key, whether declared on a
  column or as a separate table constraint
- table-level constraints only reference columns that actually exist

`ALTER TABLE` is also understood, for `ADD [COLUMN]`, `DROP [COLUMN] [IF
EXISTS]`, `RENAME [COLUMN] ... TO ...`, and `RENAME TO ...`, including
several comma-separated actions in one statement. It's checked for the same
class of mistake: a column added twice in one statement, a column targeted
by more than one action, and a rename to the name it already has.

`CREATE [UNIQUE] INDEX [IF NOT EXISTS] ... ON ... (...)` and `DROP TABLE [IF
EXISTS] ...` are understood too. An index is checked for the same kind of
mistake as everything else: the same column listed twice.

Anything else — `CREATE VIEW`, `TRUNCATE`, and so on — is rejected with a
clear "unsupported statement" error rather than silently mis-parsed.

## Running the tests

```
python -m unittest discover
```

The suite in `tests/test_parser.py` is table-driven: a list of valid inputs
that must parse and round-trip through the printer to a fixed point, and a
list of invalid inputs paired with the error type they should raise.

## Status

Early. `CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`, and `DROP TABLE` are
supported so far.
