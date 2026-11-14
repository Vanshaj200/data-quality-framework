"""Database engines, loaded from .env (never hardcoded).

One engine (`get_app_engine`) connects as `dq_app` with no default schema,
so the same connection can run fully-qualified queries against
`retail_banking` (read-only, source data), `data_quality` (this project's
own rule results), and `dq_defect_copy` (the labelled defect-injection
copy) - all three are distinct MySQL schemas on the same server, and
`dq_app` has exactly the per-schema grants described in SECURITY.md.
A second, separate engine (`get_dashboard_engine`) connects as the
read-only `dq_dashboard` user, scoped to `data_quality` only.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill in your "
            f"MySQL credentials (see SECURITY.md)."
        )
    return value


def get_app_engine() -> Engine:
    """dq_app, no default database - callers fully-qualify every table
    reference with its schema name (see SCHEMA_* constants in engine.py)."""
    url = URL.create(
        drivername="mysql+mysqlconnector",
        username=_require_env("DQ_MYSQL_USER"),
        password=_require_env("DQ_MYSQL_PASSWORD"),
        host=os.environ.get("SOURCE_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("SOURCE_MYSQL_PORT", "3306")),
    )
    return create_engine(url)


def get_dashboard_engine() -> Engine:
    """dq_dashboard, read-only, scoped to the data_quality schema only.
    Used for local development; the deployed dashboard builds its engine
    from Streamlit secrets instead (see dashboard.py), which may point at
    a different host/database (e.g. a cloud MySQL instance with a
    provider-assigned database name) - callers should use unqualified
    table names so the same queries work against either."""
    return build_engine(
        user=_require_env("DASHBOARD_MYSQL_USER"),
        password=_require_env("DASHBOARD_MYSQL_PASSWORD"),
        host=os.environ.get("SOURCE_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("SOURCE_MYSQL_PORT", "3306")),
        database=_require_env("DQ_MYSQL_DB"),
    )


def build_engine(*, user: str, password: str, host: str, port: int, database: str) -> Engine:
    """Pure engine builder with no environment/.env dependency, so the same
    code path works whether the connection details came from .env (local)
    or st.secrets (deployed)."""
    url = URL.create(
        drivername="mysql+mysqlconnector",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )
    return create_engine(url)


SOURCE_SCHEMA = os.environ.get("SOURCE_MYSQL_DB", "retail_banking")
DQ_SCHEMA = os.environ.get("DQ_MYSQL_DB", "data_quality")
DEFECT_COPY_SCHEMA = os.environ.get("DEFECT_COPY_MYSQL_DB", "dq_defect_copy")
