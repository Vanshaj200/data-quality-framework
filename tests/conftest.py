"""Shared fixtures. These tests run against the live retail_banking schema
(read-only) - they check what the checks actually compute, not mocks."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from dq.db import SOURCE_SCHEMA, get_app_engine


@pytest.fixture(scope="session")
def engine() -> Engine:
    return get_app_engine()


@pytest.fixture(scope="session")
def schema() -> str:
    return SOURCE_SCHEMA
