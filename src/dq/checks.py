"""The six check types. Every function takes a validated rule (table/column
names already checked against information_schema by validation.py before
any of this runs) and returns a CheckResult. SQL here is built only from:
(a) names already validated against information_schema, or (b) a fixed
formula name dispatched through FORMULA_SQL below - never a raw string
from rules.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine, bindparam, text

from dq.config import ConsistencyRule, Rule, ValidityRule
from dq.validation import primary_key_column, validate_column, validate_table


@dataclass
class CheckResult:
    total_rows: int
    failed_rows: int
    exceptions: list[tuple[str, str]] = field(default_factory=list)  # (record_key, detail)

    @property
    def fail_rate(self) -> float:
        return self.failed_rows / self.total_rows if self.total_rows else 0.0


_MAX_SAMPLE_EXCEPTIONS = 50


def check_completeness(engine: Engine, schema: str, rule) -> CheckResult:
    # Every {schema}/{rule.table}/{rule.column}/{pk} below is either a fixed
    # internal constant or has just been checked against information_schema
    # by validate_column/primary_key_column - never a raw value from
    # rules.yaml used as-is. See the module docstring. nosec: B608 (x3 below)
    validate_column(engine, schema, rule.table, rule.column)
    pk = primary_key_column(engine, schema, rule.table)
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{rule.table}")).scalar()  # nosec B608
        failed = conn.execute(
            text(f"SELECT COUNT(*) FROM {schema}.{rule.table} WHERE {rule.column} IS NULL")  # nosec B608
        ).scalar()
        rows = conn.execute(
            text(
                f"SELECT {pk} FROM {schema}.{rule.table} WHERE {rule.column} IS NULL "  # nosec B608
                f"LIMIT {_MAX_SAMPLE_EXCEPTIONS}"
            )
        ).all()
    exceptions = [(str(r[0]), f"{rule.column} is NULL") for r in rows]
    return CheckResult(total, failed, exceptions)


def check_uniqueness(engine: Engine, schema: str, rule) -> CheckResult:
    for col in rule.columns:
        validate_column(engine, schema, rule.table, col)
    pk = primary_key_column(engine, schema, rule.table)
    cols_csv = ", ".join(rule.columns)
    # schema/rule.table/cols_csv/pk are all pre-validated or fixed constants
    # (see check_completeness above). nosec: B608 (x3 below)
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{rule.table}")).scalar()  # nosec B608
        failed = conn.execute(
            text(
                f"SELECT COALESCE(SUM(cnt), 0) FROM ("  # nosec B608
                f"  SELECT COUNT(*) AS cnt FROM {schema}.{rule.table} "
                f"  GROUP BY {cols_csv} HAVING COUNT(*) > 1"
                f") dup_groups"
            )
        ).scalar()
        rows = conn.execute(
            text(
                f"SELECT t.{pk}, {', '.join(f't.{c}' for c in rule.columns)} "  # nosec B608
                f"FROM {schema}.{rule.table} t "
                f"JOIN (SELECT {cols_csv} FROM {schema}.{rule.table} "
                f"      GROUP BY {cols_csv} HAVING COUNT(*) > 1) dup "
                f"  ON {' AND '.join(f't.{c} = dup.{c}' for c in rule.columns)} "
                f"LIMIT {_MAX_SAMPLE_EXCEPTIONS}"
            )
        ).all()
    exceptions = [(str(r[0]), f"duplicate on ({cols_csv}) = {tuple(r[1:])}") for r in rows]
    return CheckResult(total, failed, exceptions)


def check_referential_integrity(engine: Engine, schema: str, rule) -> CheckResult:
    validate_column(engine, schema, rule.table, rule.column)
    validate_column(engine, schema, rule.ref_table, rule.ref_column)
    pk = primary_key_column(engine, schema, rule.table)
    # All identifiers below are pre-validated or fixed constants. nosec: B608 (x3)
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{rule.table}")).scalar()  # nosec B608
        join_clause = (
            f"FROM {schema}.{rule.table} c "
            f"LEFT JOIN {schema}.{rule.ref_table} p ON c.{rule.column} = p.{rule.ref_column} "
            f"WHERE p.{rule.ref_column} IS NULL"
        )
        failed = conn.execute(text(f"SELECT COUNT(*) {join_clause}")).scalar()  # nosec B608
        rows = conn.execute(
            text(f"SELECT c.{pk}, c.{rule.column} {join_clause} LIMIT {_MAX_SAMPLE_EXCEPTIONS}")  # nosec B608
        ).all()
    exceptions = [
        (str(r[0]), f"{rule.column}={r[1]} has no matching {rule.ref_table}.{rule.ref_column}")
        for r in rows
    ]
    return CheckResult(total, failed, exceptions)


def check_validity(engine: Engine, schema: str, rule: ValidityRule) -> CheckResult:
    validate_column(engine, schema, rule.table, rule.column)
    pk = primary_key_column(engine, schema, rule.table)

    # Identifiers (table/column) are validated above and safe to interpolate;
    # every VALUE from rules.yaml (allowed_values, min/max) is bound, not
    # interpolated, even though pydantic already constrains their types.
    params: dict[str, object] = {}
    if rule.validity_check == "allowed_values":
        where_failed = f"{rule.column} IS NOT NULL AND {rule.column} NOT IN :allowed_values"
        params["allowed_values"] = tuple(rule.allowed_values)
        bind = bindparam("allowed_values", expanding=True)
    elif rule.validity_check == "range":
        where_failed = (
            f"{rule.column} IS NOT NULL "
            f"AND ({rule.column} < :min_value OR {rule.column} > :max_value)"
        )
        params = {"min_value": rule.min_value, "max_value": rule.max_value}
        bind = None
    else:  # date_range
        where_failed = (
            f"{rule.column} IS NOT NULL "
            f"AND ({rule.column} < :min_date OR {rule.column} > :max_date)"
        )
        params = {"min_date": rule.min_date, "max_date": rule.max_date}
        bind = None

    # schema/rule.table/pk/rule.column are pre-validated or fixed constants;
    # where_failed is built only from those plus bound :placeholders, never a
    # raw value. nosec: B608 (x3 below)
    count_query = text(f"SELECT COUNT(*) FROM {schema}.{rule.table} WHERE {where_failed}")  # nosec B608
    sample_query = text(
        f"SELECT {pk}, {rule.column} FROM {schema}.{rule.table} "  # nosec B608
        f"WHERE {where_failed} LIMIT {_MAX_SAMPLE_EXCEPTIONS}"
    )
    if bind is not None:
        count_query = count_query.bindparams(bind)
        sample_query = sample_query.bindparams(bind)

    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{rule.table}")).scalar()  # nosec B608
        failed = conn.execute(count_query, params).scalar()
        rows = conn.execute(sample_query, params).all()
    exceptions = [(str(r[0]), f"{rule.column}={r[1]} fails {rule.validity_check}") for r in rows]
    return CheckResult(total, failed, exceptions)


# --- consistency: fixed formula registry, never a YAML expression ---


def _consistency_loan_amount(engine: Engine, schema: str) -> CheckResult:
    # The formula (amount vs payments*duration) is fixed Python code, not a
    # YAML-supplied expression; "schema" is a fixed internal constant, never
    # user input. nosec: B608 (x3 below)
    validate_table(engine, schema, "loan")
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.loan")).scalar()  # nosec B608
        failed = conn.execute(
            text(f"SELECT COUNT(*) FROM {schema}.loan WHERE ABS(amount - payments * duration) > 1")  # nosec B608
        ).scalar()
        rows = conn.execute(
            text(
                f"SELECT loan_id, amount, payments, duration FROM {schema}.loan "  # nosec B608
                f"WHERE ABS(amount - payments * duration) > 1 LIMIT {_MAX_SAMPLE_EXCEPTIONS}"
            )
        ).all()
    exceptions = [
        (str(r[0]), f"amount={r[1]} != payments({r[2]}) x duration({r[3]})") for r in rows
    ]
    return CheckResult(total, failed, exceptions)


_CONSISTENCY_FORMULAS = {
    "loan_amount_equals_payments_times_duration": _consistency_loan_amount,
}


def check_consistency(engine: Engine, schema: str, rule: ConsistencyRule) -> CheckResult:
    return _CONSISTENCY_FORMULAS[rule.formula](engine, schema)


# --- reconciliation: fixed formula registry ---


def _reconciliation_account_balance(engine: Engine, schema: str, tolerance: float) -> CheckResult:
    # Fixed formula (not YAML-supplied); "schema" is a fixed internal
    # constant, never user input. nosec: B608
    validate_table(engine, schema, "transactions")
    query = text(
        "WITH account_totals AS ("  # nosec B608
        "    SELECT account_id,"
        "        SUM(CASE WHEN type = 'PRIJEM' THEN amount ELSE -amount END)"
        "            AS expected_final_balance"
        f"    FROM {schema}.transactions"
        "    GROUP BY account_id"
        ") "
        "SELECT at.account_id, at.expected_final_balance, "
        "    EXISTS ("
        f"        SELECT 1 FROM {schema}.transactions t"
        "        WHERE t.account_id = at.account_id"
        "          AND t.trans_date = ("
        f"              SELECT MAX(trans_date) FROM {schema}.transactions t2"
        "              WHERE t2.account_id = at.account_id"
        "          )"
        "          AND ABS(t.balance - at.expected_final_balance) <= :tolerance"
        "    ) AS matches "
        "FROM account_totals at"
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"tolerance": tolerance}).all()
    total = len(rows)
    failures = [r for r in rows if not r.matches]
    exceptions = [
        (
            str(r.account_id),
            f"expected_final_balance={r.expected_final_balance} not found on last day",
        )
        for r in failures[:_MAX_SAMPLE_EXCEPTIONS]
    ]
    return CheckResult(total, len(failures), exceptions)


_RECONCILIATION_FORMULAS = {
    "account_balance_reconciliation": _reconciliation_account_balance,
}


def check_reconciliation(engine: Engine, schema: str, rule) -> CheckResult:
    return _RECONCILIATION_FORMULAS[rule.formula](engine, schema, rule.tolerance)


CHECKERS = {
    "completeness": check_completeness,
    "uniqueness": check_uniqueness,
    "referential_integrity": check_referential_integrity,
    "validity": check_validity,
    "consistency": check_consistency,
    "reconciliation": check_reconciliation,
}


def run_check(engine: Engine, schema: str, rule: Rule) -> CheckResult:
    return CHECKERS[rule.check_type](engine, schema, rule)
