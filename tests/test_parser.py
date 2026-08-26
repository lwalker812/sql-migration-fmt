import unittest

from migfmt import ParseError, ValidationError, parse_sql, pretty_print, pretty_print_all

# Each entry is (name, sql). The check is: it parses without error, and
# formatting it is a fixed point (format(parse(format(parse(sql)))) is
# stable). That catches printer bugs without hand-writing an expected
# string for every case.
VALID_CASES = [
    (
        "simple table",
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);",
    ),
    (
        "if not exists plus a quoted identifier with a space",
        'CREATE TABLE IF NOT EXISTS "user table" (id INTEGER PRIMARY KEY);',
    ),
    (
        "keywords in lowercase",
        "create table t (id integer not null);",
    ),
    (
        "default wrapped in parens",
        "CREATE TABLE events (created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP));",
    ),
    (
        "default before not null",
        "CREATE TABLE events (created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL);",
    ),
    (
        "string default containing an escaped quote",
        "CREATE TABLE t (status TEXT NOT NULL DEFAULT 'it''s active');",
    ),
    (
        "numeric default",
        "CREATE TABLE t (retries INTEGER NOT NULL DEFAULT 0);",
    ),
    (
        "composite table-level primary key",
        "CREATE TABLE line_items (order_id INTEGER, sku TEXT, PRIMARY KEY (order_id, sku));",
    ),
    (
        "named foreign key constraint",
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, "
        "CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id));",
    ),
    (
        "backtick quoted identifiers",
        "CREATE TABLE `orders` (`id` INTEGER PRIMARY KEY);",
    ),
    (
        "varchar with a length argument",
        "CREATE TABLE t (name VARCHAR(255) NOT NULL);",
    ),
    (
        "a line comment inside the column list",
        "CREATE TABLE t (\n  id INTEGER PRIMARY KEY, -- surrogate key\n  name TEXT\n);",
    ),
    (
        "a block comment between statements",
        "CREATE TABLE t (id INTEGER PRIMARY KEY); /* done */",
    ),
    (
        "alter table add column",
        "ALTER TABLE t ADD COLUMN nickname TEXT;",
    ),
    (
        "alter table add without the COLUMN keyword",
        "ALTER TABLE t ADD nickname TEXT;",
    ),
    (
        "alter table drop column if exists",
        "ALTER TABLE t DROP COLUMN IF EXISTS nickname;",
    ),
    (
        "alter table rename column",
        "ALTER TABLE t RENAME COLUMN old_name TO new_name;",
    ),
    (
        "alter table rename without the COLUMN keyword",
        "ALTER TABLE t RENAME old_name TO new_name;",
    ),
    (
        "alter table rename to",
        "ALTER TABLE t RENAME TO renamed_t;",
    ),
    (
        "alter table with more than one action",
        "ALTER TABLE t ADD COLUMN a TEXT, DROP COLUMN b, RENAME COLUMN c TO d;",
    ),
]

# (name, sql, exception type)
INVALID_CASES = [
    (
        "duplicate column name",
        "CREATE TABLE t (id INTEGER, id TEXT);",
        ValidationError,
    ),
    (
        "two primary keys",
        "CREATE TABLE t (id INTEGER PRIMARY KEY, other INTEGER PRIMARY KEY);",
        ValidationError,
    ),
    (
        "primary key split between a column and a table constraint",
        "CREATE TABLE t (id INTEGER PRIMARY KEY, other INTEGER, PRIMARY KEY (other));",
        ValidationError,
    ),
    (
        "unique constraint on a column that doesn't exist",
        "CREATE TABLE t (id INTEGER, UNIQUE (missing_col));",
        ValidationError,
    ),
    (
        "empty column list",
        "CREATE TABLE t ();",
        ParseError,
    ),
    (
        "trailing comma before the closing paren",
        "CREATE TABLE t (id INTEGER, );",
        ParseError,
    ),
    (
        "missing semicolon",
        "CREATE TABLE t (id INTEGER)",
        ParseError,
    ),
    (
        "unterminated string literal",
        "CREATE TABLE t (name TEXT DEFAULT 'oops);",
        ParseError,
    ),
    (
        "unterminated quoted identifier",
        'CREATE TABLE t ("id INTEGER);',
        ParseError,
    ),
    (
        "unsupported statement kind",
        "DROP TABLE t;",
        ParseError,
    ),
    (
        "unsupported create statement",
        "CREATE INDEX idx ON t (id);",
        ParseError,
    ),
    (
        "alter table renames a column to itself",
        "ALTER TABLE t RENAME COLUMN a TO a;",
        ValidationError,
    ),
    (
        "alter table renames itself",
        "ALTER TABLE t RENAME TO t;",
        ValidationError,
    ),
    (
        "alter table adds the same column twice",
        "ALTER TABLE t ADD COLUMN a TEXT, ADD COLUMN a INTEGER;",
        ValidationError,
    ),
    (
        "alter table drops the same column twice",
        "ALTER TABLE t DROP COLUMN a, DROP COLUMN a;",
        ValidationError,
    ),
    (
        "alter table missing an action",
        "ALTER TABLE t;",
        ParseError,
    ),
]


class ValidCaseTests(unittest.TestCase):
    def test_parses_and_formatting_reaches_a_fixed_point(self):
        for name, sql in VALID_CASES:
            with self.subTest(name=name):
                statements = parse_sql(sql)
                self.assertEqual(len(statements), 1)

                first_pass = pretty_print_all(statements)
                reparsed = parse_sql(first_pass)
                second_pass = pretty_print_all(reparsed)

                self.assertEqual(first_pass, second_pass)

    def test_exact_output_for_the_simple_case(self):
        sql = "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);"
        expected = (
            "CREATE TABLE users (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    email TEXT NOT NULL\n"
            ");"
        )
        self.assertEqual(pretty_print(parse_sql(sql)[0]), expected)

    def test_unquoted_identifiers_are_not_quoted_unnecessarily(self):
        sql = "CREATE TABLE `orders` (`id` INTEGER PRIMARY KEY);"
        out = pretty_print(parse_sql(sql)[0])
        self.assertIn("CREATE TABLE orders (", out)
        self.assertIn("id INTEGER PRIMARY KEY", out)

    def test_mixed_case_identifier_is_quoted_on_output(self):
        sql = 'CREATE TABLE "UserAccounts" (id INTEGER PRIMARY KEY);'
        out = pretty_print(parse_sql(sql)[0])
        self.assertIn('"UserAccounts"', out)

    def test_exact_output_for_a_single_alter_action(self):
        sql = "alter table t add nickname text;"
        expected = "ALTER TABLE t ADD COLUMN nickname TEXT;"
        self.assertEqual(pretty_print(parse_sql(sql)[0]), expected)

    def test_exact_output_for_multiple_alter_actions(self):
        sql = "ALTER TABLE t ADD COLUMN a TEXT, DROP COLUMN b;"
        expected = "ALTER TABLE t\n    ADD COLUMN a TEXT,\n    DROP COLUMN b;"
        self.assertEqual(pretty_print(parse_sql(sql)[0]), expected)


class InvalidCaseTests(unittest.TestCase):
    def test_rejected_with_the_right_error_type(self):
        for name, sql, expected_error in INVALID_CASES:
            with self.subTest(name=name):
                with self.assertRaises(expected_error):
                    parse_sql(sql)

    def test_duplicate_column_message_names_the_column(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_sql("CREATE TABLE t (id INTEGER, id TEXT);")
        self.assertIn("id", str(ctx.exception))

    def test_unsupported_statement_message_is_informative(self):
        with self.assertRaises(ParseError) as ctx:
            parse_sql("DROP TABLE t;")
        self.assertIn("unsupported statement", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
