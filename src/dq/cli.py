"""CLI entry point: python -m dq run --config rules.yaml [--source original|defect_copy]"""

from __future__ import annotations

import argparse
import sys

from dq.config import RulesConfigError
from dq.engine import run_rules
from dq.logging_config import configure_logging
from dq.validation import UnknownIdentifierError


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

    args = parser.parse_args(argv)
    logger = configure_logging()

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
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
