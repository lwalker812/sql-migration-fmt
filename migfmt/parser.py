"""Tokenizer, AST, and recursive-descent parser for CREATE TABLE and
ALTER TABLE statements.

CREATE INDEX, DROP TABLE, and the rest of the DDL surface are still rejected
with an "unsupported statement" error rather than silently mis-parsed.
"""

from dataclasses import dataclass, field


class MigrationError(Exception):
    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col
        location = ""
        if line is not None:
            location = f" (line {line}" + (f", col {col})" if col is not None else ")")
        super().__init__(f"{message}{location}")


class ParseError(MigrationError):
    """The input is not syntactically valid SQL, or uses syntax we don't parse."""


class ValidationError(MigrationError):
    """The input parses, but the statement it describes doesn't make sense."""


# --- AST -------------------------------------------------------------------


@dataclass
class NotNullConstraint:
    pass


@dataclass
class NullConstraint:
    pass


@dataclass
class PrimaryKeyConstraint:
    pass


@dataclass
class UniqueConstraint:
    pass


@dataclass
class DefaultConstraint:
    expression: str


@dataclass
class ReferencesConstraint:
    table: str
    column: str | None = None


@dataclass
class TablePrimaryKey:
    columns: list[str]
    name: str | None = None


@dataclass
class TableUnique:
    columns: list[str]
    name: str | None = None


@dataclass
class TableForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str] = field(default_factory=list)
    name: str | None = None


@dataclass
class ColumnDef:
    name: str
    type_name: str
    type_args: list[str]
    constraints: list[object]
    line: int


@dataclass
class CreateTable:
    name: str
    if_not_exists: bool
    columns: list[ColumnDef]
    table_constraints: list[object]
    line: int


@dataclass
class AddColumn:
    column: ColumnDef


@dataclass
class DropColumn:
    name: str
    if_exists: bool = False


@dataclass
class RenameColumn:
    old_name: str
    new_name: str


@dataclass
class RenameTable:
    new_name: str


@dataclass
class AlterTable:
    name: str
    actions: list[object]
    line: int


# --- Tokenizer ---------------------------------------------------------------

_PUNCT = "(),;"


@dataclass
class Token:
    kind: str  # 'ident' | 'qident' | 'string' | 'number' | 'punct' | 'eof'
    text: str
    pos: int
    end: int
    line: int
    col: int


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    line = 1
    col = 1

    def step():
        nonlocal i, line, col
        ch = sql[i]
        i += 1
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1
        return ch

    while i < n:
        start_i, start_line, start_col = i, line, col
        ch = sql[i]

        if ch in " \t\r\n":
            step()
            continue

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                step()
            continue

        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            step()
            step()
            while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                step()
            if i >= n:
                raise ParseError("unterminated block comment", start_line, start_col)
            step()
            step()
            continue

        if ch == '"' or ch == "`":
            quote = ch
            step()
            buf = []
            closed = False
            while i < n:
                c = sql[i]
                if c == quote:
                    step()
                    if i < n and sql[i] == quote:
                        buf.append(quote)
                        step()
                        continue
                    closed = True
                    break
                buf.append(c)
                step()
            if not closed:
                raise ParseError("unterminated quoted identifier", start_line, start_col)
            tokens.append(Token("qident", "".join(buf), start_i, i, start_line, start_col))
            continue

        if ch == "'":
            step()
            buf = []
            closed = False
            while i < n:
                c = sql[i]
                if c == "'":
                    step()
                    if i < n and sql[i] == "'":
                        buf.append("'")
                        step()
                        continue
                    closed = True
                    break
                buf.append(c)
                step()
            if not closed:
                raise ParseError("unterminated string literal", start_line, start_col)
            tokens.append(Token("string", "".join(buf), start_i, i, start_line, start_col))
            continue

        if ch.isdigit():
            while i < n and (sql[i].isdigit() or sql[i] == "."):
                step()
            tokens.append(Token("number", sql[start_i:i], start_i, i, start_line, start_col))
            continue

        if ch.isalpha() or ch == "_":
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                step()
            tokens.append(Token("ident", sql[start_i:i], start_i, i, start_line, start_col))
            continue

        if ch in _PUNCT or ch == "-":
            step()
            tokens.append(Token("punct", ch, start_i, i, start_line, start_col))
            continue

        raise ParseError(f"unexpected character {ch!r}", start_line, start_col)

    tokens.append(Token("eof", "", i, i, line, col))
    return tokens


# --- Parser ------------------------------------------------------------------

_DEFAULT_STOP_KEYWORDS = {"NOT", "NULL", "PRIMARY", "UNIQUE", "REFERENCES", "DEFAULT"}


class Parser:
    def __init__(self, tokens: list[Token], sql: str):
        self.tokens = tokens
        self.sql = sql
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def check_kw(self, *words: str) -> bool:
        tok = self.peek()
        return tok.kind == "ident" and tok.text.upper() in words

    def expect_kw(self, word: str) -> Token:
        tok = self.peek()
        if tok.kind != "ident" or tok.text.upper() != word:
            raise ParseError(f"expected {word!r}, found {tok.text!r}", tok.line, tok.col)
        return self.advance()

    def expect_punct(self, punct: str) -> Token:
        tok = self.peek()
        if tok.kind != "punct" or tok.text != punct:
            raise ParseError(f"expected {punct!r}, found {tok.text!r}", tok.line, tok.col)
        return self.advance()

    def expect_ident(self) -> str:
        tok = self.peek()
        if tok.kind in ("ident", "qident"):
            self.advance()
            return tok.text
        raise ParseError(f"expected identifier, found {tok.text!r}", tok.line, tok.col)

    def parse_statements(self) -> list[object]:
        statements = []
        while self.peek().kind != "eof":
            if self.peek().kind == "punct" and self.peek().text == ";":
                self.advance()
                continue
            statements.append(self.parse_statement())
        return statements

    def parse_statement(self) -> object:
        tok = self.peek()
        if tok.kind == "ident" and tok.text.upper() == "CREATE":
            return self.parse_create_table()
        if tok.kind == "ident" and tok.text.upper() == "ALTER":
            return self.parse_alter_table()
        raise ParseError(
            f"unsupported statement: expected CREATE TABLE or ALTER TABLE, found {tok.text!r}",
            tok.line,
            tok.col,
        )

    def parse_create_table(self) -> CreateTable:
        tok = self.peek()
        self.advance()
        tok2 = self.peek()
        if not (tok2.kind == "ident" and tok2.text.upper() == "TABLE"):
            raise ParseError(
                f"unsupported statement: CREATE {tok2.text} (only CREATE TABLE is supported)",
                tok2.line,
                tok2.col,
            )
        self.advance()

        if_not_exists = False
        if self.check_kw("IF"):
            self.advance()
            self.expect_kw("NOT")
            self.expect_kw("EXISTS")
            if_not_exists = True

        name = self.expect_ident()
        self.expect_punct("(")

        columns: list[ColumnDef] = []
        table_constraints: list[object] = []
        while True:
            if self.is_table_constraint_start():
                table_constraints.append(self.parse_table_constraint())
            else:
                columns.append(self.parse_column_def())
            nxt = self.peek()
            if nxt.kind == "punct" and nxt.text == ",":
                self.advance()
                continue
            break

        self.expect_punct(")")
        self.expect_punct(";")
        return CreateTable(
            name=name,
            if_not_exists=if_not_exists,
            columns=columns,
            table_constraints=table_constraints,
            line=tok.line,
        )

    def parse_alter_table(self) -> AlterTable:
        tok = self.peek()
        self.advance()
        self.expect_kw("TABLE")
        name = self.expect_ident()

        actions: list[object] = []
        while True:
            actions.append(self.parse_alter_action())
            nxt = self.peek()
            if nxt.kind == "punct" and nxt.text == ",":
                self.advance()
                continue
            break

        self.expect_punct(";")
        return AlterTable(name=name, actions=actions, line=tok.line)

    def parse_alter_action(self):
        if self.check_kw("ADD"):
            self.advance()
            if self.check_kw("COLUMN"):
                self.advance()
            return AddColumn(column=self.parse_column_def())

        if self.check_kw("DROP"):
            self.advance()
            if self.check_kw("COLUMN"):
                self.advance()
            if_exists = False
            if self.check_kw("IF"):
                self.advance()
                self.expect_kw("EXISTS")
                if_exists = True
            return DropColumn(name=self.expect_ident(), if_exists=if_exists)

        if self.check_kw("RENAME"):
            self.advance()
            if self.check_kw("TO"):
                self.advance()
                return RenameTable(new_name=self.expect_ident())
            if self.check_kw("COLUMN"):
                self.advance()
            old_name = self.expect_ident()
            self.expect_kw("TO")
            return RenameColumn(old_name=old_name, new_name=self.expect_ident())

        tok = self.peek()
        raise ParseError(
            f"unsupported ALTER TABLE action, found {tok.text!r}", tok.line, tok.col
        )

    def is_table_constraint_start(self) -> bool:
        return self.check_kw("PRIMARY", "UNIQUE", "FOREIGN", "CONSTRAINT")

    def parse_table_constraint(self):
        name = None
        if self.check_kw("CONSTRAINT"):
            self.advance()
            name = self.expect_ident()

        if self.check_kw("PRIMARY"):
            self.advance()
            self.expect_kw("KEY")
            return TablePrimaryKey(columns=self.parse_column_list(), name=name)

        if self.check_kw("UNIQUE"):
            self.advance()
            return TableUnique(columns=self.parse_column_list(), name=name)

        if self.check_kw("FOREIGN"):
            self.advance()
            self.expect_kw("KEY")
            columns = self.parse_column_list()
            self.expect_kw("REFERENCES")
            ref_table = self.expect_ident()
            ref_columns = []
            if self.peek().kind == "punct" and self.peek().text == "(":
                ref_columns = self.parse_column_list()
            return TableForeignKey(
                columns=columns, ref_table=ref_table, ref_columns=ref_columns, name=name
            )

        tok = self.peek()
        raise ParseError(f"expected a table constraint, found {tok.text!r}", tok.line, tok.col)

    def parse_column_list(self) -> list[str]:
        self.expect_punct("(")
        cols = [self.expect_ident()]
        while self.peek().kind == "punct" and self.peek().text == ",":
            self.advance()
            cols.append(self.expect_ident())
        self.expect_punct(")")
        return cols

    def parse_column_def(self) -> ColumnDef:
        tok = self.peek()
        name = self.expect_ident()
        type_name, type_args = self.parse_type()

        constraints: list[object] = []
        while True:
            if self.check_kw("NOT"):
                self.advance()
                self.expect_kw("NULL")
                constraints.append(NotNullConstraint())
            elif self.check_kw("NULL"):
                self.advance()
                constraints.append(NullConstraint())
            elif self.check_kw("PRIMARY"):
                self.advance()
                self.expect_kw("KEY")
                constraints.append(PrimaryKeyConstraint())
            elif self.check_kw("UNIQUE"):
                self.advance()
                constraints.append(UniqueConstraint())
            elif self.check_kw("DEFAULT"):
                self.advance()
                constraints.append(DefaultConstraint(expression=self.parse_default_expression()))
            elif self.check_kw("REFERENCES"):
                self.advance()
                ref_table = self.expect_ident()
                ref_column = None
                if self.peek().kind == "punct" and self.peek().text == "(":
                    self.advance()
                    ref_column = self.expect_ident()
                    self.expect_punct(")")
                constraints.append(ReferencesConstraint(table=ref_table, column=ref_column))
            else:
                break

        return ColumnDef(
            name=name, type_name=type_name, type_args=type_args, constraints=constraints, line=tok.line
        )

    def parse_type(self) -> tuple[str, list[str]]:
        tok = self.peek()
        if tok.kind != "ident":
            raise ParseError(f"expected a type name, found {tok.text!r}", tok.line, tok.col)
        self.advance()
        args: list[str] = []
        if self.peek().kind == "punct" and self.peek().text == "(":
            self.advance()
            while True:
                arg_tok = self.peek()
                if arg_tok.kind not in ("number", "ident"):
                    raise ParseError(
                        f"expected a type argument, found {arg_tok.text!r}", arg_tok.line, arg_tok.col
                    )
                self.advance()
                args.append(arg_tok.text)
                if self.peek().kind == "punct" and self.peek().text == ",":
                    self.advance()
                    continue
                break
            self.expect_punct(")")
        return tok.text, args

    def parse_default_expression(self) -> str:
        start_tok = self.peek()
        if start_tok.kind == "eof":
            raise ParseError("expected a default value", start_tok.line, start_tok.col)

        depth = 0
        end_pos = start_tok.pos
        consumed_any = False
        while True:
            tok = self.peek()
            if tok.kind == "eof":
                raise ParseError("unterminated default expression", tok.line, tok.col)
            if depth == 0:
                if tok.kind == "punct" and tok.text in (",", ")"):
                    break
                if tok.kind == "ident" and tok.text.upper() in _DEFAULT_STOP_KEYWORDS:
                    break
            if tok.kind == "punct" and tok.text == "(":
                depth += 1
            elif tok.kind == "punct" and tok.text == ")":
                depth -= 1
            consumed = self.advance()
            end_pos = consumed.end
            consumed_any = True

        if not consumed_any:
            raise ParseError("expected a default value", start_tok.line, start_tok.col)
        return self.sql[start_tok.pos:end_pos].strip()


def validate_create_table(stmt: CreateTable) -> None:
    seen: dict[str, ColumnDef] = {}
    for col in stmt.columns:
        key = col.name.lower()
        if key in seen:
            raise ValidationError(
                f"duplicate column {col.name!r} in table {stmt.name!r}", col.line
            )
        seen[key] = col

    primary_keys = sum(
        1 for c in stmt.columns if any(isinstance(cc, PrimaryKeyConstraint) for cc in c.constraints)
    )
    primary_keys += sum(1 for tc in stmt.table_constraints if isinstance(tc, TablePrimaryKey))
    if primary_keys > 1:
        raise ValidationError(
            f"table {stmt.name!r} defines more than one primary key", stmt.line
        )

    for tc in stmt.table_constraints:
        for column in getattr(tc, "columns", ()):
            if column.lower() not in seen:
                raise ValidationError(
                    f"constraint on unknown column {column!r} in table {stmt.name!r}", stmt.line
                )


def validate_alter_table(stmt: AlterTable) -> None:
    added: dict[str, ColumnDef] = {}
    touched: dict[str, object] = {}
    for action in stmt.actions:
        if isinstance(action, AddColumn):
            key = action.column.name.lower()
            if key in added:
                raise ValidationError(
                    f"column {action.column.name!r} added twice in the same "
                    f"ALTER TABLE {stmt.name!r}",
                    action.column.line,
                )
            added[key] = action.column
        elif isinstance(action, DropColumn):
            key = action.name.lower()
            if key in touched:
                raise ValidationError(
                    f"column {action.name!r} is targeted by more than one "
                    f"action in ALTER TABLE {stmt.name!r}",
                    stmt.line,
                )
            touched[key] = action
        elif isinstance(action, RenameColumn):
            if action.old_name.lower() == action.new_name.lower():
                raise ValidationError(
                    f"column {action.old_name!r} renamed to itself in "
                    f"ALTER TABLE {stmt.name!r}",
                    stmt.line,
                )
            key = action.old_name.lower()
            if key in touched:
                raise ValidationError(
                    f"column {action.old_name!r} is targeted by more than one "
                    f"action in ALTER TABLE {stmt.name!r}",
                    stmt.line,
                )
            touched[key] = action
        elif isinstance(action, RenameTable):
            if action.new_name.lower() == stmt.name.lower():
                raise ValidationError(f"table {stmt.name!r} renamed to itself", stmt.line)


def parse_sql(sql: str) -> list[object]:
    tokens = tokenize(sql)
    statements = Parser(tokens, sql).parse_statements()
    for stmt in statements:
        if isinstance(stmt, CreateTable):
            validate_create_table(stmt)
        elif isinstance(stmt, AlterTable):
            validate_alter_table(stmt)
    return statements
