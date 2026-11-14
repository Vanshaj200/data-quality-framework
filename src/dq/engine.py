"""Orchestrates a full rules.yaml run: load config, run every rule against
the chosen schema, write results to data_quality.dq_runs/dq_results/
dq_exceptions, return a summary for the CLI to print.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, text

from dq.checks import run_check
from dq.config import RulesConfig, load_rules_config
from dq.db import DEFECT_COPY_SCHEMA, DQ_SCHEMA, SOURCE_SCHEMA, get_app_engine

logger = logging.getLogger("dq")

Source = str  # "original" | "defect_copy"


@dataclass
class RuleOutcome:
    rule_id: str
    table: str
    check_type: str
    severity: str
    total_rows: int
    failed_rows: int
    fail_rate: float
    threshold: float
    passed: bool


def _schema_for(source: Source) -> str:
    if source == "original":
        return SOURCE_SCHEMA
    if source == "defect_copy":
        return DEFECT_COPY_SCHEMA
    raise ValueError(f"source must be 'original' or 'defect_copy', got {source!r}")


def run_rules(config_path: str, source: Source = "original") -> list[RuleOutcome]:
    config: RulesConfig = load_rules_config(config_path)
    app_engine: Engine = get_app_engine()
    schema = _schema_for(source)

    run_id = _start_run(app_engine, source, config_path)
    outcomes: list[RuleOutcome] = []

    for rule in config.rules:
        result = run_check(app_engine, schema, rule)
        passed = result.fail_rate <= rule.threshold
        outcomes.append(
            RuleOutcome(
                rule_id=rule.id,
                table=rule.table,
                check_type=rule.check_type,
                severity=rule.severity,
                total_rows=result.total_rows,
                failed_rows=result.failed_rows,
                fail_rate=result.fail_rate,
                threshold=rule.threshold,
                passed=passed,
            )
        )
        _record_result(app_engine, run_id, rule, result, passed)
        logger.info(
            "%-8s %-22s %-20s total=%-9d failed=%-7d rate=%.4f threshold=%.4f %s",
            rule.id,
            rule.check_type,
            rule.table,
            result.total_rows,
            result.failed_rows,
            result.fail_rate,
            rule.threshold,
            "PASS" if passed else "FAIL",
        )

    return outcomes


def _start_run(engine: Engine, source: Source, config_path: str) -> int:
    # DQ_SCHEMA is a fixed internal constant (db.py), never user input;
    # every value is bound. nosec: B608
    query = text(
        f"INSERT INTO {DQ_SCHEMA}.dq_runs (run_timestamp, source, rules_file) "  # nosec B608
        f"VALUES (:ts, :source, :rules_file)"
    )
    with engine.begin() as conn:
        result = conn.execute(
            query, {"ts": datetime.now(), "source": source, "rules_file": config_path}
        )
        return result.lastrowid


def _record_result(engine: Engine, run_id: int, rule, result, passed: bool) -> None:
    # DQ_SCHEMA is a fixed internal constant; every value is bound. nosec: B608 (x2)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {DQ_SCHEMA}.dq_results "  # nosec B608
                f"(run_id, rule_id, table_name, check_type, severity, description, "
                f" total_rows, failed_rows, fail_rate, threshold, passed) "
                f"VALUES (:run_id, :rule_id, :table_name, :check_type, :severity, :description, "
                f" :total_rows, :failed_rows, :fail_rate, :threshold, :passed)"
            ),
            {
                "run_id": run_id,
                "rule_id": rule.id,
                "table_name": rule.table,
                "check_type": rule.check_type,
                "severity": rule.severity,
                "description": rule.description,
                "total_rows": result.total_rows,
                "failed_rows": result.failed_rows,
                "fail_rate": result.fail_rate,
                "threshold": rule.threshold,
                "passed": passed,
            },
        )
        if result.exceptions:
            conn.execute(
                text(
                    f"INSERT INTO {DQ_SCHEMA}.dq_exceptions "  # nosec B608
                    f"(run_id, rule_id, record_key, detail) "
                    f"VALUES (:run_id, :rule_id, :record_key, :detail)"
                ),
                [
                    {"run_id": run_id, "rule_id": rule.id, "record_key": key, "detail": detail}
                    for key, detail in result.exceptions
                ],
            )
