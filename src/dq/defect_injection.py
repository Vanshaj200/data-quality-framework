"""Clones retail_banking into the clearly-labelled dq_defect_copy schema,
then plants known, documented errors into that copy - never into the
original data (verified: this module only ever writes to DEFECT_COPY_SCHEMA,
never SOURCE_SCHEMA). Each defect targets exactly one rule in rules.yaml,
so running `python -m dq run --source defect_copy` afterwards should make
exactly those rules fail while every other rule still passes - proving the
checks catch what's planted, not just rubber-stamping clean data.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from dq.db import DEFECT_COPY_SCHEMA, SOURCE_SCHEMA

logger = logging.getLogger("dq")

# Order matters: parents before children, so FK constraints on the copy
# (created via CREATE TABLE ... LIKE, which copies them) are satisfiable.
_TABLES_IN_FK_ORDER = [
    "district",
    "client",
    "account",
    "disposition",
    "loan",
    "card",
    "permanent_order",
    "transactions",
]


def clone_source_into_defect_copy(engine: Engine) -> None:
    # table is always one of the 8 hardcoded names in _TABLES_IN_FK_ORDER,
    # never external input; DEFECT_COPY_SCHEMA/SOURCE_SCHEMA are fixed
    # internal constants. nosec: B608 (x3 below)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(_TABLES_IN_FK_ORDER):
            conn.execute(text(f"DROP TABLE IF EXISTS {DEFECT_COPY_SCHEMA}.{table}"))  # nosec B608
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        for table in _TABLES_IN_FK_ORDER:
            conn.execute(
                text(  # nosec B608
                    f"CREATE TABLE {DEFECT_COPY_SCHEMA}.{table} LIKE {SOURCE_SCHEMA}.{table}"
                )
            )
            conn.execute(
                text(
                    f"INSERT INTO {DEFECT_COPY_SCHEMA}.{table} "  # nosec B608
                    f"SELECT * FROM {SOURCE_SCHEMA}.{table}"
                )
            )
            # A bulk INSERT leaves InnoDB's statistics stale, which made the
            # optimizer pick a catastrophically slow plan for the
            # reconciliation check's correlated subqueries (observed: still
            # running after 170+ seconds vs ~4s on the up-to-date original).
            conn.execute(text(f"ANALYZE TABLE {DEFECT_COPY_SCHEMA}.{table}"))
    logger.info("Cloned all 8 tables from %s into %s", SOURCE_SCHEMA, DEFECT_COPY_SCHEMA)
    _relax_constraints_for_defect_demo(engine)


def _relax_constraints_for_defect_demo(engine: Engine) -> None:
    """Two of the planted defects would be rejected by MySQL's own
    constraints before the DQ rule ever saw them - CREATE TABLE ... LIKE
    copies indexes (though not foreign keys - verified directly: the copy
    has zero FK constraints, so DQ-009's planted orphan district_id needs no
    relaxation at all). Relaxing exactly these two, on DEFECT_COPY_SCHEMA
    only, demonstrates each DQ rule catching something the database's own
    constraints don't (e.g. if a migration ever dropped one by accident):
    - loan.account_id UNIQUE -> would block DQ-006's planted duplicate loan.
    - loan.status ENUM in strict SQL mode -> would reject DQ-016's planted
      invalid code outright rather than let it land as bad data.
    Never done on SOURCE_SCHEMA.
    """
    # DEFECT_COPY_SCHEMA is a fixed internal constant. nosec: B608 (x2)
    with engine.begin() as conn:
        conn.execute(
            text(f"ALTER TABLE {DEFECT_COPY_SCHEMA}.loan DROP INDEX account_id")  # nosec B608
        )
        conn.execute(
            text(  # nosec B608
                f"ALTER TABLE {DEFECT_COPY_SCHEMA}.loan MODIFY status VARCHAR(5) NOT NULL"
            )
        )
    logger.info("Relaxed 3 constraints on %s only, for the defect demo", DEFECT_COPY_SCHEMA)


class Defect:
    def __init__(self, label: str, targets_rule: str, sql: str, params: dict | None = None):
        self.label = label
        self.targets_rule = targets_rule
        self.sql = sql
        self.params = params or {}


def _defects() -> list[Defect]:
    # Every statement below is 100% hand-written and fixed in this file -
    # no rule config, YAML, or any external input ever reaches this
    # function - and "s" (DEFECT_COPY_SCHEMA) is a fixed internal constant.
    # nosec: B608 (x6 below)
    s = DEFECT_COPY_SCHEMA
    return [
        Defect(
            "Point 5 accounts at a non-existent district_id (breaks referential integrity)",
            "DQ-009",
            f"UPDATE {s}.account SET district_id = 99999 "  # nosec B608
            f"WHERE account_id IN (SELECT * FROM (SELECT account_id FROM {s}.account LIMIT 5) x)",
        ),
        Defect(
            "Duplicate 3 loans onto accounts that already have one (breaks uniqueness)",
            "DQ-006",
            f"INSERT INTO {s}.loan "  # nosec B608
            f"(loan_id, account_id, loan_date, amount, duration, payments, status) "
            f"SELECT loan_id + 900000, account_id, loan_date, amount, duration, payments, status "
            f"FROM {s}.loan LIMIT 3",
        ),
        Defect(
            "Set an invalid loan.status code on 4 loans (breaks validity)",
            "DQ-016",
            f"UPDATE {s}.loan SET status = 'X' "  # nosec B608
            f"WHERE loan_id IN (SELECT * FROM (SELECT loan_id FROM {s}.loan LIMIT 4) x)",
        ),
        Defect(
            "Break amount = payments x duration on 6 loans (breaks consistency)",
            "DQ-022",
            f"UPDATE {s}.loan SET amount = amount + 5000 "  # nosec B608
            f"WHERE loan_id IN (SELECT * FROM (SELECT loan_id FROM {s}.loan LIMIT 6 OFFSET 10) x)",
        ),
        Defect(
            "Corrupt the balance on 8 accounts' LAST transaction "
            "(breaks reconciliation - DQ-023 only checks each account's final day)",
            "DQ-023",
            f"UPDATE {s}.transactions t "  # nosec B608
            f"JOIN ("
            f"    SELECT trans_id FROM {s}.transactions t2 "
            f"    WHERE t2.trans_date = ("
            f"        SELECT MAX(trans_date) FROM {s}.transactions t3 "
            f"        WHERE t3.account_id = t2.account_id"
            f"    ) "
            f"    ORDER BY t2.account_id LIMIT 8"
            f") AS last_day ON t.trans_id = last_day.trans_id "
            f"SET t.balance = t.balance + 777",
        ),
        Defect(
            "Duplicate a disposition row onto an existing (client_id, account_id) pair "
            "(breaks uniqueness)",
            "DQ-007",
            f"INSERT INTO {s}.disposition (disp_id, client_id, account_id, type) "  # nosec B608
            f"SELECT disp_id + 900000, client_id, account_id, type "
            f"FROM {s}.disposition LIMIT 2",
        ),
    ]


def inject_defects(engine: Engine) -> list[tuple[str, str, int]]:
    """Returns (label, targets_rule, rows_affected) for each planted defect."""
    results = []
    for defect in _defects():
        with engine.begin() as conn:
            result = conn.execute(text(defect.sql), defect.params)
            rows_affected = result.rowcount
        logger.info(
            "Injected: %s (%d rows, targets %s)", defect.label, rows_affected, defect.targets_rule
        )
        results.append((defect.label, defect.targets_rule, rows_affected))
    return results
