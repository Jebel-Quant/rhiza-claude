#!/usr/bin/env python3
"""Validate `.rhiza/template.yml` configuration.

A stdlib-only port of the `rhiza validate` command, bundled with this plugin so
`/rhiza:status` can report config validity without the `rhiza` CLI (or PyYAML)
installed. It is also a **gate**: it exits non-zero on an invalid configuration, so
it works in CI independently of the command. It checks
that the target is a git repo, that the template file exists and parses, that
the project has the expected language-specific structure, and that the
configuration's required/optional fields are present and well-typed.

Usage:
  uv run --python 3.12 --no-project python \
    scripts/validate.py [TARGET] [--path-to-template DIR] [--json]

  TARGET              repository root to validate (default: current directory)
  --path-to-template  directory containing template.yml (default: <TARGET>/.rhiza;
                      use '.' to keep the file in the project root)
  --json              emit {"valid", "errors", "warnings"} as JSON on stdout;
                      human-readable progress still goes to stderr

Exit code is 0 when validation passes, 1 when it fails — same contract as
`rhiza validate`, so it drops into CI unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_yaml import load_yaml  # noqa: E402
from _validate_fields import (  # noqa: E402
    validate_configuration_mode,
    validate_optional_fields,
    validate_repository_format,
    validate_required_fields,
    validate_string_list,
)
from _validate_log import Log  # noqa: E402
from _validate_structure import check_project_structure  # noqa: E402

__all__ = ["Log", "main", "validate"]


# --------------------------------------------------------------------------- #
# preconditions
# --------------------------------------------------------------------------- #
def _check_git_repository(log: Log, target: Path) -> bool:
    """Require *target* to be a git repository."""
    if not (target / ".git").is_dir():
        log.error(f"Target directory is not a git repository: {target}")
        log.error("Initialize a git repository with 'git init' first")
        return False
    return True


def _check_template_file_exists(
    log: Log, target: Path, template_file: Path | None
) -> tuple[bool, Path]:
    """Locate template.yml and confirm it exists."""
    if template_file is None:
        template_file = target / ".rhiza" / "template.yml"
    try:
        display = template_file.relative_to(target)
    except ValueError:
        display = template_file
    if not template_file.exists():
        log.error(f"No template file found at: {display}")
        log.error("The template configuration must be in the .rhiza folder.")
        log.info("To fix this:")
        log.info("  • If you're starting fresh, run: /rhiza:init")
        log.info("  • It writes .rhiza/template.yml, the only file the sync needs")
        return False, template_file
    log.success(f"Template file exists: {display}")
    return True, template_file


def _parse_template_file(log: Log, template_file: Path) -> tuple[bool, dict[str, Any] | None]:
    """Load and parse template.yml into a config dict."""
    log.debug(f"Parsing template file: {template_file}")
    try:
        config = load_yaml(template_file)
    except ValueError as exc:
        log.error(f"Invalid YAML in template.yml: {exc}")
        log.error("Fix the YAML syntax errors and try again")
        return False, None
    except OSError as exc:
        log.error(f"Could not read template.yml: {exc}")
        return False, None

    if not config:
        log.error("template.yml is empty")
        log.error("Add configuration to template.yml, or run /rhiza:init to generate it")
        return False, None

    log.success("YAML syntax is valid")
    return True, config


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def _load_valid_config(log: Log, target: Path, template_file: Path | None) -> dict[str, Any] | None:
    """Run the hard-stop preconditions and return the parsed config, else None."""
    if not _check_git_repository(log, target):
        return None
    exists, template_file = _check_template_file_exists(log, target, template_file)
    if not exists:
        return None
    ok, config = _parse_template_file(log, template_file)
    if not ok or config is None:
        return None

    language = config.get("language", "python")
    log.info(f"Project language: {language}")
    if not check_project_structure(log, target, str(language)):
        return None
    if not validate_configuration_mode(log, config):
        return None
    return config


def _validate_config_fields(log: Log, config: dict[str, Any]) -> bool:
    """Field-level checks; these do NOT short-circuit so all errors surface at once."""
    passed = validate_required_fields(log, config)
    if not validate_repository_format(log, config):
        passed = False
    if config.get("templates") and not validate_string_list(
        log, config, "templates", "templates: [core, tests, github]"
    ):
        passed = False
    if config.get("include") and not validate_string_list(
        log, config, "include", "include: ['.github', '.gitignore']"
    ):
        passed = False
    validate_optional_fields(log, config)
    return passed


def validate(log: Log, target: Path, template_file: Path | None = None) -> bool:
    """Validate template.yml; return True on success, False on failure."""
    target = target.resolve()
    log.info(f"Validating template configuration in: {target}")

    config = _load_valid_config(log, target, template_file)
    if config is None:
        return False

    passed = _validate_config_fields(log, config)
    log.debug("Validation complete, determining final result")
    if passed:
        log.success("Validation passed: template.yml is valid")
        return True
    log.error("Validation failed: template.yml has errors")
    log.error("Fix the errors above and run validate again")
    return False


def main(argv: list[str] | None = None) -> int:
    """Entry point: validate, optionally emit JSON, and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Validate .rhiza/template.yml configuration.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Repository root to validate (default: current directory).",
    )
    parser.add_argument(
        "--path-to-template",
        dest="path_to_template",
        default=None,
        help="Directory holding template.yml (default: <TARGET>/.rhiza; '.' for the project root).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit {valid, errors, warnings} as a JSON object on stdout.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also print debug-level progress lines.",
    )
    args = parser.parse_args(argv)

    template_file = None
    if args.path_to_template is not None:
        template_file = Path(args.path_to_template) / "template.yml"

    log = Log(verbose=args.verbose)
    valid = validate(log, Path(args.target), template_file=template_file)

    if args.json_output:
        print(
            json.dumps({"valid": valid, "errors": log.errors, "warnings": log.warnings}, indent=2)
        )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
