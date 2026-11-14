"""One test per check type, against the live retail_banking data. Numbers
here match the ones already verified by hand in rules.yaml's commit and
docs/traceability_matrix.md - these tests exist so a future change to
checks.py that breaks the logic is caught automatically, not just numbers
re-confirmed once and never checked again."""

from __future__ import annotations

from sqlalchemy import Engine

from dq.checks import (
    check_completeness,
    check_consistency,
    check_reconciliation,
    check_referential_integrity,
    check_uniqueness,
    check_validity,
)
from dq.config import (
    CompletenessRule,
    ConsistencyRule,
    ReconciliationRule,
    ReferentialIntegrityRule,
    UniquenessRule,
    ValidityRule,
)


def _base(**kwargs):
    defaults = {"id": "TEST", "description": "test", "severity": "low", "threshold": 0.0}
    defaults.update(kwargs)
    return defaults


def test_completeness_finds_the_known_district_gap(engine: Engine, schema: str):
    rule = CompletenessRule(
        **_base(table="district", check_type="completeness", column="unemployment_rate_95")
    )
    result = check_completeness(engine, schema, rule)
    assert result.total_rows == 77
    assert result.failed_rows == 1
    assert result.exceptions == [("69", "unemployment_rate_95 is NULL")]


def test_completeness_passes_on_a_not_null_column(engine: Engine, schema: str):
    rule = CompletenessRule(
        **_base(table="account", check_type="completeness", column="account_id")
    )
    result = check_completeness(engine, schema, rule)
    assert result.failed_rows == 0


def test_uniqueness_passes_on_a_real_primary_key(engine: Engine, schema: str):
    rule = UniquenessRule(**_base(table="account", check_type="uniqueness", columns=["account_id"]))
    result = check_uniqueness(engine, schema, rule)
    assert result.total_rows == 4500
    assert result.failed_rows == 0


def test_referential_integrity_passes_on_a_real_fk(engine: Engine, schema: str):
    rule = ReferentialIntegrityRule(
        **_base(
            table="account",
            check_type="referential_integrity",
            column="district_id",
            ref_table="district",
            ref_column="district_id",
        )
    )
    result = check_referential_integrity(engine, schema, rule)
    assert result.total_rows == 4500
    assert result.failed_rows == 0


def test_validity_allowed_values_catches_the_known_vyber_anomaly(engine: Engine, schema: str):
    rule = ValidityRule(
        **_base(
            table="transactions",
            check_type="validity",
            column="type",
            validity_check="allowed_values",
            allowed_values=["PRIJEM", "VYDAJ"],
        )
    )
    result = check_validity(engine, schema, rule)
    assert result.total_rows == 1056320
    assert result.failed_rows == 16666


def test_validity_range_passes_on_a_real_percentage_column(engine: Engine, schema: str):
    rule = ValidityRule(
        **_base(
            table="district",
            check_type="validity",
            column="urban_ratio_pct",
            validity_check="range",
            min_value=0,
            max_value=100,
        )
    )
    result = check_validity(engine, schema, rule)
    assert result.failed_rows == 0


def test_consistency_loan_amount_formula(engine: Engine, schema: str):
    rule = ConsistencyRule(
        **_base(
            table="loan",
            check_type="consistency",
            formula="loan_amount_equals_payments_times_duration",
        )
    )
    result = check_consistency(engine, schema, rule)
    assert result.total_rows == 682
    assert result.failed_rows == 0


def test_reconciliation_account_balance_formula(engine: Engine, schema: str):
    rule = ReconciliationRule(
        **_base(
            table="transactions",
            check_type="reconciliation",
            formula="account_balance_reconciliation",
            tolerance=1.00,
        )
    )
    result = check_reconciliation(engine, schema, rule)
    assert result.total_rows == 4500
    assert result.failed_rows == 64
