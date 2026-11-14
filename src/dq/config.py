"""Pydantic schema for rules.yaml. Every rule's table/column names are
plain strings here - config.py never builds or runs SQL. The engine
(engine.py) is responsible for validating every such name against
information_schema before using it in a query, and for mapping a rule's
fixed, named `formula` to hardcoded SQL/pandas logic rather than ever
evaluating a user-supplied expression.
"""

from __future__ import annotations

from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

Severity = Literal["low", "medium", "high", "critical"]


class _RuleBase(BaseModel):
    id: str
    description: str
    table: str
    severity: Severity
    threshold: float = Field(
        ge=0.0,
        le=1.0,
        description="Maximum tolerated failure rate (0.0 = zero tolerance) before the rule fails.",
    )


class CompletenessRule(_RuleBase):
    check_type: Literal["completeness"]
    column: str


class UniquenessRule(_RuleBase):
    check_type: Literal["uniqueness"]
    columns: list[str] = Field(min_length=1)


class ReferentialIntegrityRule(_RuleBase):
    check_type: Literal["referential_integrity"]
    column: str
    ref_table: str
    ref_column: str


class ValidityRule(_RuleBase):
    check_type: Literal["validity"]
    column: str
    validity_check: Literal["allowed_values", "range", "date_range"]
    # validate_default=True: without it, pydantic v2 skips this field's
    # validator entirely when the field is left at its default (i.e. the
    # common case of omitting allowed_values altogether) - found by a test
    # expecting this exact rejection to fire and it silently not doing so.
    allowed_values: list[str] | None = Field(default=None, validate_default=True)
    min_value: float | None = None
    max_value: float | None = None
    min_date: str | None = None
    max_date: str | None = None

    @field_validator("allowed_values")
    @classmethod
    def _allowed_values_required(cls, v, info):
        if info.data.get("validity_check") == "allowed_values" and not v:
            raise ValueError(
                "validity_check='allowed_values' requires a non-empty allowed_values list"
            )
        return v


# Fixed registry of known formulas - adding a new one requires adding both
# the literal here AND the matching implementation in checks.py, never a
# YAML-supplied expression string.
ConsistencyFormula = Literal["loan_amount_equals_payments_times_duration"]
ReconciliationFormula = Literal["account_balance_reconciliation"]


class ConsistencyRule(_RuleBase):
    check_type: Literal["consistency"]
    formula: ConsistencyFormula


class ReconciliationRule(_RuleBase):
    check_type: Literal["reconciliation"]
    formula: ReconciliationFormula
    tolerance: float = Field(default=0.01, ge=0.0)


Rule = Annotated[
    CompletenessRule
    | UniquenessRule
    | ReferentialIntegrityRule
    | ValidityRule
    | ConsistencyRule
    | ReconciliationRule,
    Field(discriminator="check_type"),
]


class RulesConfig(BaseModel):
    rules: list[Rule] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, rules: list) -> list:
        ids = [r.id for r in rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate rule id(s) in rules.yaml: {sorted(dupes)}")
        return rules


class RulesConfigError(Exception):
    """Raised with a human-readable message when rules.yaml fails validation."""


def load_rules_config(path: str) -> RulesConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    try:
        return RulesConfig.model_validate(raw)
    except ValidationError as exc:
        raise RulesConfigError(f"Invalid {path}:\n{exc}") from exc
