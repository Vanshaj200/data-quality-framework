"""Streamlit dashboard: scorecard, drill-down to failed records, and the
pass-rate trend across runs. Connects as dq_dashboard (SELECT-only on
data_quality - verified in SECURITY.md) via a read-only engine, so this
page cannot write to the database even if something in it tried to.

Run with: streamlit run src/dq/dashboard.py
(binds to 127.0.0.1 only - see .streamlit/config.toml)
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text

from dq.db import build_engine, get_dashboard_engine

st.set_page_config(page_title="Data Quality Dashboard", layout="wide")


@st.cache_resource
def _engine():
    """Deployed (Streamlit Cloud): build from st.secrets, which point at a
    separate, scoped read-only user on a cloud MySQL instance - never the
    local dq_app/root credentials. Local dev: no secrets.toml exists, so
    this falls back to .env via get_dashboard_engine()."""
    try:
        s = st.secrets
        return build_engine(
            user=s["DASHBOARD_MYSQL_USER"],
            password=s["DASHBOARD_MYSQL_PASSWORD"],
            host=s["DASHBOARD_MYSQL_HOST"],
            port=int(s.get("DASHBOARD_MYSQL_PORT", 3306)),
            database=s["DASHBOARD_MYSQL_DB"],
        )
    except (FileNotFoundError, KeyError):
        return get_dashboard_engine()


# Table names below are unqualified (no schema prefix) deliberately: the
# engine's connection URL always specifies the right default database
# (data_quality locally, a provider-assigned name when deployed), so the
# same queries work against either without hardcoding a schema name.
# nosec: B608 (x4 below) - see checks.py's module docstring for the general
# rationale this project follows throughout; every value here is bound.
def _load_runs() -> pd.DataFrame:
    query = text(
        "SELECT run_id, run_timestamp, source, rules_file "  # nosec B608
        "FROM dq_runs ORDER BY run_id DESC"
    )
    return pd.read_sql(query, _engine())


def _load_results(run_id: int) -> pd.DataFrame:
    query = text(
        "SELECT * FROM dq_results WHERE run_id = :run_id ORDER BY rule_id"  # nosec B608
    )
    return pd.read_sql(query, _engine(), params={"run_id": run_id})


def _load_exceptions(run_id: int, rule_id: str) -> pd.DataFrame:
    query = text(
        "SELECT record_key, detail FROM dq_exceptions "  # nosec B608
        "WHERE run_id = :run_id AND rule_id = :rule_id ORDER BY record_key"
    )
    return pd.read_sql(query, _engine(), params={"run_id": run_id, "rule_id": rule_id})


def _load_trend() -> pd.DataFrame:
    query = text(
        "SELECT ru.run_id, ru.run_timestamp, ru.source, "  # nosec B608
        "       SUM(re.passed) AS n_passed, COUNT(*) AS n_rules "
        "FROM dq_runs ru "
        "JOIN dq_results re ON re.run_id = ru.run_id "
        "GROUP BY ru.run_id, ru.run_timestamp, ru.source "
        "ORDER BY ru.run_id"
    )
    df = pd.read_sql(query, _engine())
    df["pass_rate_pct"] = 100 * df["n_passed"] / df["n_rules"]
    return df


st.title("Data Quality Framework")

runs = _load_runs()
if runs.empty:
    st.warning("No runs yet. Run `python -m dq run --config rules.yaml` first.")
    st.stop()

run_labels = {
    row.run_id: f"#{row.run_id} - {row.run_timestamp} ({row.source})" for row in runs.itertuples()
}
selected_run_id = st.selectbox(
    "Run", options=list(run_labels.keys()), format_func=lambda rid: run_labels[rid]
)

results = _load_results(selected_run_id)

st.header("Scorecard")
col1, col2, col3 = st.columns(3)
n_rules = len(results)
n_passed = int(results["passed"].sum())
col1.metric("Rules run", n_rules)
col2.metric("Passed", n_passed)
col3.metric("Pass rate", f"{100 * n_passed / n_rules:.1f}%" if n_rules else "-")

by_table = (
    results.groupby("table_name")
    .agg(n_rules=("rule_id", "count"), n_passed=("passed", "sum"))
    .assign(pass_rate_pct=lambda d: (100 * d.n_passed / d.n_rules).round(2))
    .reset_index()
)
by_check_type = (
    results.groupby("check_type")
    .agg(n_rules=("rule_id", "count"), n_passed=("passed", "sum"))
    .assign(pass_rate_pct=lambda d: (100 * d.n_passed / d.n_rules).round(2))
    .reset_index()
)
sc_col1, sc_col2 = st.columns(2)
sc_col1.subheader("By table")
sc_col1.dataframe(by_table, hide_index=True, width="stretch")
sc_col2.subheader("By check type")
sc_col2.dataframe(by_check_type, hide_index=True, width="stretch")

st.header("Rule results")
st.dataframe(
    results[
        [
            "rule_id",
            "table_name",
            "check_type",
            "severity",
            "total_rows",
            "failed_rows",
            "fail_rate",
            "threshold",
            "passed",
        ]
    ],
    hide_index=True,
    width="stretch",
)

st.header("Drill down to failed records")
failed_rules = results[results["passed"] == 0]["rule_id"].tolist()
if not failed_rules:
    st.success("No failed rules in this run - nothing to drill into.")
else:
    chosen_rule = st.selectbox("Failed rule", failed_rules)
    exceptions = _load_exceptions(selected_run_id, chosen_rule)
    st.caption(f"Showing up to {len(exceptions)} sample failing records for {chosen_rule}")
    st.dataframe(exceptions, hide_index=True, width="stretch")

st.header("Trend across runs")
trend = _load_trend()
st.line_chart(trend, x="run_id", y="pass_rate_pct")
st.dataframe(
    trend[["run_id", "run_timestamp", "source", "n_passed", "n_rules", "pass_rate_pct"]],
    hide_index=True,
    width="stretch",
)
