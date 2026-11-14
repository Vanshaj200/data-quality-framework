"""The information_schema gate every table/column name from rules.yaml has
to pass through before any check builds SQL with it."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from dq.validation import (
    UnknownIdentifierError,
    primary_key_column,
    validate_column,
    validate_table,
)


def test_validate_table_passes_for_a_real_table(engine: Engine, schema: str):
    validate_table(engine, schema, "account")  # should not raise


def test_validate_table_rejects_an_unknown_table(engine: Engine, schema: str):
    with pytest.raises(UnknownIdentifierError, match="doesn't exist"):
        validate_table(engine, schema, "accounts_dropped_table; DROP TABLE account")


def test_validate_column_passes_for_a_real_column(engine: Engine, schema: str):
    validate_column(engine, schema, "account", "district_id")  # should not raise


def test_validate_column_rejects_an_unknown_column(engine: Engine, schema: str):
    with pytest.raises(UnknownIdentifierError, match="doesn't exist"):
        validate_column(engine, schema, "account", "not_a_real_column")


def test_primary_key_column_returns_the_real_pk(engine: Engine, schema: str):
    assert primary_key_column(engine, schema, "account") == "account_id"
    assert primary_key_column(engine, schema, "transactions") == "trans_id"
