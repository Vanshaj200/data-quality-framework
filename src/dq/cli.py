"""CLI entry point:
python -m dq run --config rules.yaml [--source original|defect_copy] [--report]
python -m dq report [--run-id N]
python -m dq inject-defects
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dq.config import RulesConfigError
from dq.db import get_app_engine
from dq.defect_injection import clone_source_into_defect_copy, inject_defects
from dq.engine import run_rules
from dq.logging_config import configure_logging
from dq.reports import generate_exceptions_report, generate_scorecard
from dq.validation import UnknownIdentifierError


def _write_reports(logger, run_id: int | None = None) -> None:
    engine = get_app_engine()
    exceptions_path = generate_exceptions_report(engine, Path("exceptions_reports"), run_id)
    scorecard_path = generate_scorecard(engine, Path("exports"), run_id)
    logger.info("Exceptions report: %s", exceptions_path)
    logger.info("Scorecard: %s", scorecard_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dq")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run every rule in a rules.yaml file")
    run_parser.add_argument("--config", required=True, help="Path to rules.yaml")
    run_parser.add_argument(
        "--source",
        choices=["original", "defect_copy"],
        default="original",
        help="Which schema to check: the real data, or the labelled defect-injection copy",
    )
    run_parser.add_argument(
        "--report", action="store_true", help="Also write the exceptions report and scorecard"
    )

    report_parser = subparsers.add_parser(
        "report", help="Write the exceptions report and scorecard for a past run"
    )
    report_parser.add_argument(
        "--run-id", type=int, default=None, help="Defaults to the most recent run"
    )

    subparsers.add_parser(
        "inject-defects",
        help="Clone retail_banking into dq_defect_copy and plant known, documented errors",
    )

    args = parser.parse_args(argv)
    logger = configure_logging()

    if args.command == "report":
        _write_reports(logger, args.run_id)
        return 0

    if args.command == "inject-defects":
        engine = get_app_engine()
        clone_source_into_defect_copy(engine)
        for label, targets_rule, rows_affected in inject_defects(engine):
            logger.info("%-9s %4d rows - %s", targets_rule, rows_affected, label)
        return 0

    try:
        outcomes = run_rules(args.config, source=args.source)
    except RulesConfigError as exc:
        logger.error(str(exc))
        return 1
    except UnknownIdentifierError as exc:
        logger.error(str(exc))
        return 1

    n_failed = sum(1 for o in outcomes if not o.passed)
    logger.info("%d/%d rules passed.", len(outcomes) - n_failed, len(outcomes))

    if args.report:
        _write_reports(logger)

    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
