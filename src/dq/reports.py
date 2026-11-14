"""Builds the exceptions report (record-level, gitignored - per-rule
drill-down) and the scorecard (aggregate pass rates, committed) from the
latest run's dq_results/dq_exceptions.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

from dq.db import DQ_SCHEMA


def _latest_run_id(engine: Engine) -> int:
    # DQ_SCHEMA is a fixed internal constant, never user input. nosec: B608
    with engine.connect() as conn:
        run_id = conn.execute(
            text(f"SELECT MAX(run_id) FROM {DQ_SCHEMA}.dq_runs")  # nosec B608
        ).scalar()
    if run_id is None:
        raise RuntimeError("No runs found in dq_runs - run `python -m dq run` first.")
    return run_id


def generate_exceptions_report(engine: Engine, out_dir: Path, run_id: int | None = None) -> Path:
    run_id = run_id or _latest_run_id(engine)
    # DQ_SCHEMA is a fixed internal constant; every value is bound. nosec: B608
    query = text(
        f"SELECT r.rule_id, r.table_name, r.check_type, r.severity, "  # nosec B608
        f"       e.record_key, e.detail "
        f"FROM {DQ_SCHEMA}.dq_exceptions e "
        f"JOIN {DQ_SCHEMA}.dq_results r ON r.run_id = e.run_id AND r.rule_id = e.rule_id "
        f"WHERE e.run_id = :run_id "
        f"ORDER BY r.rule_id, e.record_key"
    )
    df = pd.read_sql(query, engine, params={"run_id": run_id})
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"run_{run_id}_exceptions.csv"
    df.to_csv(path, index=False)
    return path


def generate_scorecard(engine: Engine, out_dir: Path, run_id: int | None = None) -> Path:
    run_id = run_id or _latest_run_id(engine)
    # DQ_SCHEMA is a fixed internal constant; every value is bound. nosec: B608
    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"SELECT * FROM {DQ_SCHEMA}.dq_results WHERE run_id = :run_id"),  # nosec B608
            conn,
            params={"run_id": run_id},
        )

    def summarize(group_type: str, group_col: str) -> pd.DataFrame:
        g = df.groupby(group_col).agg(n_rules=("rule_id", "count"), n_passed=("passed", "sum"))
        g["n_failed"] = g["n_rules"] - g["n_passed"]
        g["pass_rate_pct"] = (100 * g["n_passed"] / g["n_rules"]).round(2)
        g = g.reset_index().rename(columns={group_col: "group_value"})
        g.insert(0, "group_type", group_type)
        return g

    n_rules = len(df)
    n_passed = int(df["passed"].sum())
    overall = pd.DataFrame(
        [
            {
                "group_type": "overall",
                "group_value": "all_rules",
                "n_rules": n_rules,
                "n_passed": n_passed,
                "n_failed": n_rules - n_passed,
                "pass_rate_pct": round(100 * n_passed / n_rules, 2) if n_rules else 0.0,
            }
        ]
    )

    scorecard = pd.concat(
        [overall, summarize("table", "table_name"), summarize("check_type", "check_type")],
        ignore_index=True,
    )
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "scorecard.csv"
    scorecard.to_csv(path, index=False)
    return path
