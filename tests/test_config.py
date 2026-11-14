"""pydantic schema validation: the real rules.yaml loads clean, and bad
config is rejected with a clear error rather than a stack trace."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dq.config import RulesConfig, load_rules_config


def test_real_rules_yaml_loads_and_has_23_rules():
    config = load_rules_config("rules.yaml")
    assert len(config.rules) == 23
    assert {r.id for r in config.rules} == {f"DQ-{i:03d}" for i in range(1, 24)}


def test_duplicate_rule_ids_are_rejected():
    with pytest.raises(ValidationError, match="Duplicate rule id"):
        RulesConfig.model_validate(
            {
                "rules": [
                    {
                        "id": "DQ-001",
                        "description": "a",
                        "table": "t",
                        "check_type": "completeness",
                        "column": "c",
                        "severity": "low",
                        "threshold": 0.0,
                    },
                    {
                        "id": "DQ-001",
                        "description": "b",
                        "table": "t",
                        "check_type": "completeness",
                        "column": "c2",
                        "severity": "low",
                        "threshold": 0.0,
                    },
                ]
            }
        )


def test_threshold_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        RulesConfig.model_validate(
            {
                "rules": [
                    {
                        "id": "DQ-001",
                        "description": "a",
                        "table": "t",
                        "check_type": "completeness",
                        "column": "c",
                        "severity": "low",
                        "threshold": 1.5,
                    }
                ]
            }
        )


def test_validity_allowed_values_required_when_check_is_allowed_values():
    with pytest.raises(ValidationError, match="requires a non-empty allowed_values"):
        RulesConfig.model_validate(
            {
                "rules": [
                    {
                        "id": "DQ-001",
                        "description": "a",
                        "table": "t",
                        "check_type": "validity",
                        "column": "c",
                        "validity_check": "allowed_values",
                        "severity": "low",
                        "threshold": 0.0,
                    }
                ]
            }
        )


def test_unknown_check_type_is_rejected():
    with pytest.raises(ValidationError):
        RulesConfig.model_validate(
            {
                "rules": [
                    {
                        "id": "DQ-001",
                        "description": "a",
                        "table": "t",
                        "check_type": "not_a_real_check_type",
                        "severity": "low",
                        "threshold": 0.0,
                    }
                ]
            }
        )
