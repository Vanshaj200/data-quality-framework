"""Validates every table/column name a rule names in rules.yaml against
information_schema before any check builds SQL with it. This is the one
place a name from YAML is allowed to end up inside a query string - every
other module calls through here first, never trusts a config-supplied
name directly.
"""

from __future__ import annotations

from sqlalchemy import Engine, text


class UnknownIdentifierError(ValueError):
    """Raised when rules.yaml names a table/column that doesn't exist."""


def _existing_tables(engine: Engine, schema: str) -> set[str]:
    query = text(
        "SELECT DISTINCT table_name FROM information_schema.tables WHERE table_schema = :schema"
    )
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(query, {"schema": schema})}


def _existing_columns(engine: Engine, schema: str, table: str) -> set[str]:
    query = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = :table"
    )
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(query, {"schema": schema, "table": table})}


def validate_table(engine: Engine, schema: str, table: str) -> None:
    if table not in _existing_tables(engine, schema):
        raise UnknownIdentifierError(
            f"rules.yaml names table '{table}', which doesn't exist in {schema}"
        )


def validate_column(engine: Engine, schema: str, table: str, column: str) -> None:
    validate_table(engine, schema, table)
    if column not in _existing_columns(engine, schema, table):
        raise UnknownIdentifierError(
            f"rules.yaml names column '{table}.{column}', which doesn't exist in {schema}"
        )


def primary_key_column(engine: Engine, schema: str, table: str) -> str:
    """Every table in this project has a single-column PK - used only to
    label sample exception rows, never as part of a WHERE clause's logic."""
    query = text(
        "SELECT column_name FROM information_schema.key_column_usage "
        "WHERE table_schema = :schema AND table_name = :table "
        "AND constraint_name = 'PRIMARY'"
    )
    with engine.connect() as conn:
        row = conn.execute(query, {"schema": schema, "table": table}).first()
    if row is None:
        raise UnknownIdentifierError(f"{schema}.{table} has no primary key")
    return row[0]
