#!/usr/bin/env python3
"""Validate `.rhiza/template.yml` configuration.

A stdlib-only port of the `rhiza validate` command, bundled with this plugin so
`/rhiza:validate` works without the `rhiza` CLI (or PyYAML) installed. It checks
that the target is a git repo, that the template file exists and parses, that
the project has the expected language-specific structure, and that the
configuration's required/optional fields are present and well-typed.

Usage:
  python3 scripts/validate.py [TARGET] [--path-to-template DIR] [--json]

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

# Hosts the template may target; mirrors rhiza.models.template.GitHost.
GIT_HOSTS = ("github", "gitlab")


# --------------------------------------------------------------------------- #
# logging shim
# --------------------------------------------------------------------------- #
class Log:
    """Tiny stand-in for the CLI's loguru sink.

    Prints human-readable, symbol-prefixed lines to stderr and, so `--json`
    can report a structured verdict, accumulates the ERROR/WARNING messages.
    """

    _SYMBOLS = {"error": "✗", "warning": "!", "success": "✓", "info": " ", "debug": " "}

    def __init__(self, *, verbose: bool = False) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._verbose = verbose

    def _emit(self, level: str, message: str) -> None:
        if level == "debug" and not self._verbose:
            return
        print(f"{self._SYMBOLS[level]} {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self._emit("error", message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)
        self._emit("warning", message)

    def success(self, message: str) -> None:
        self._emit("success", message)

    def info(self, message: str) -> None:
        self._emit("info", message)

    def debug(self, message: str) -> None:
        self._emit("debug", message)


# --------------------------------------------------------------------------- #
# language-specific project structure
# --------------------------------------------------------------------------- #
def _validate_python_structure(log: Log, target: Path) -> bool:
    """Python needs pyproject.toml (required); src/ and tests/ are warnings."""
    passed = True
    if not (target / "pyproject.toml").exists():
        log.error(f"pyproject.toml not found: {target / 'pyproject.toml'}")
        log.error("pyproject.toml is required for Python projects")
        log.info("Run 'rhiza init' to create a default pyproject.toml")
        passed = False
    else:
        log.success(f"pyproject.toml exists: {target / 'pyproject.toml'}")

    for name in ("src", "tests"):
        d = target / name
        if not d.exists():
            log.warning(f"Standard '{name}' folder not found: {d}")
            log.warning(f"Consider creating a '{name}' directory")
        else:
            log.success(f"'{name}' folder exists: {d}")
    return passed


def _validate_go_structure(log: Log, target: Path) -> bool:
    """Go needs go.mod (required); cmd/ and pkg/|internal/ are warnings."""
    passed = True
    if not (target / "go.mod").exists():
        log.error(f"go.mod not found: {target / 'go.mod'}")
        log.error("go.mod is required for Go projects")
        log.info("Run 'go mod init <module-name>' to create go.mod")
        passed = False
    else:
        log.success(f"go.mod exists: {target / 'go.mod'}")

    cmd_dir, pkg_dir, internal_dir = target / "cmd", target / "pkg", target / "internal"
    if not cmd_dir.exists():
        log.warning(f"Standard 'cmd' folder not found: {cmd_dir}")
        log.warning("Consider creating a 'cmd' directory for main applications")
    else:
        log.success(f"'cmd' folder exists: {cmd_dir}")

    if not pkg_dir.exists() and not internal_dir.exists():
        log.warning("Neither 'pkg' nor 'internal' folder found")
        log.warning(
            "Consider creating 'pkg' for public libraries or 'internal' for private packages"
        )
    else:
        if pkg_dir.exists():
            log.success(f"'pkg' folder exists: {pkg_dir}")
        if internal_dir.exists():
            log.success(f"'internal' folder exists: {internal_dir}")
    return passed


# Registry of language -> structure validator; extend here to add a language.
_VALIDATORS = {"python": _validate_python_structure, "go": _validate_go_structure}


def _check_project_structure(log: Log, target: Path, language: str) -> bool:
    """Dispatch to the language validator; unsupported languages pass with a warning."""
    log.debug(f"Validating project structure for language: {language}")
    validator = _VALIDATORS.get(language.lower())
    if validator is None:
        log.warning(f"No validator found for language '{language}'")
        log.warning(f"Supported languages: {', '.join(_VALIDATORS)}")
        log.warning("Skipping project structure validation")
        return True
    return validator(log, target)


# --------------------------------------------------------------------------- #
# preconditions
# --------------------------------------------------------------------------- #
def _check_git_repository(log: Log, target: Path) -> bool:
    if not (target / ".git").is_dir():
        log.error(f"Target directory is not a git repository: {target}")
        log.error("Initialize a git repository with 'git init' first")
        return False
    return True


def _check_template_file_exists(
    log: Log, target: Path, template_file: Path | None
) -> tuple[bool, Path]:
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
        log.info("  • If you're starting fresh, run: rhiza init")
        log.info("  • If you have an existing configuration, run: rhiza migrate")
        return False, template_file
    log.success(f"Template file exists: {display}")
    return True, template_file


def _parse_template_file(log: Log, template_file: Path) -> tuple[bool, dict[str, Any] | None]:
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
        log.error("Add configuration to template.yml or run 'rhiza init' to generate defaults")
        return False, None

    log.success("YAML syntax is valid")
    return True, config


# --------------------------------------------------------------------------- #
# configuration-mode + field validators
# --------------------------------------------------------------------------- #
def _validate_profiles_field(log: Log, config: dict[str, Any]) -> bool | None:
    """None when absent, True/False when present and valid/invalid."""
    if "profiles" not in config:
        return None
    profiles = config["profiles"]
    if not isinstance(profiles, list):
        log.error(f"profiles must be a list, got {type(profiles).__name__}")
        log.error("Example: profiles: [github-project]")
        return False
    if not profiles:
        log.error("profiles list cannot be empty")
        log.error("Example: profiles: [github-project]")
        return False
    for p in profiles:
        if not isinstance(p, str) or not p.strip():
            log.error(f"Each entry in profiles must be a non-empty string, got: {p!r}")
            return False
    return True


def _validate_configuration_mode(log: Log, config: dict[str, Any]) -> bool:
    log.debug("Validating configuration mode")
    has_templates = bool(config.get("templates"))
    has_include = bool(config.get("include"))

    profiles_valid = _validate_profiles_field(log, config)
    if profiles_valid is False:
        return False
    has_profiles = profiles_valid is True

    if "bundles" in config:
        log.error("Field 'bundles' has been renamed to 'templates'")
        log.error("Update your .rhiza/template.yml:  bundles: [...]  →  templates: [...]")
        return False

    if not has_profiles and not has_templates and not has_include:
        log.error(
            "Must specify at least one of 'profiles', 'templates', or 'include' in template.yml"
        )
        log.error("  • Profile-based: profiles: [github-project]")
        log.error("  • Template-based: templates: [core, tests, github]")
        log.error("  • Path-based: include: [.rhiza, .github, ...]")
        log.error("  • Hybrid: specify both templates and include")
        return False

    if has_profiles:
        log.success(f"Using profile mode (profiles: {config['profiles']})")
    elif has_templates and has_include:
        log.success("Using hybrid mode (templates + include)")
    elif has_templates:
        log.success("Using template-based mode")
    else:
        log.success("Using path-based mode")
    return True


def _validate_required_fields(log: Log, config: dict[str, Any]) -> bool:
    log.debug("Validating required fields")
    has_template_repo = "template-repository" in config
    has_repo = "repository" in config
    if not has_template_repo and not has_repo:
        log.error("Missing required field: 'template-repository' or 'repository'")
        log.error("Add 'template-repository' or 'repository' to your template.yml")
        return False

    repo_field = "template-repository" if has_template_repo else "repository"
    repo_value = config[repo_field]
    if not isinstance(repo_value, str):
        log.error(f"Field '{repo_field}' must be of type str, got {type(repo_value).__name__}")
        log.error(f"Fix the type of '{repo_field}' in template.yml")
        return False
    log.success(f"Field '{repo_field}' is present and valid")
    return True


def _validate_repository_format(log: Log, config: dict[str, Any]) -> bool:
    log.debug("Validating repository format")
    repo_field = (
        "template-repository"
        if "template-repository" in config
        else "repository"
        if "repository" in config
        else None
    )
    if repo_field is None:
        return True  # caught by _validate_required_fields
    repo = config[repo_field]
    if not isinstance(repo, str):
        log.error(f"{repo_field} must be a string, got {type(repo).__name__}")
        log.error("Example: 'owner/repository'")
        return False
    if "/" not in repo:
        log.error(f"{repo_field} must be in format 'owner/repo', got: {repo}")
        log.error("Example: 'jebel-quant/rhiza'")
        return False
    log.success(f"{repo_field} format is valid: {repo}")
    return True


def _validate_string_list(log: Log, config: dict[str, Any], field: str, example: str) -> bool:
    """Shared check for the `templates` / `include` list fields."""
    log.debug(f"Validating {field} field")
    if field not in config:
        return True
    value = config[field]
    if not isinstance(value, list):
        log.error(f"{field} must be a list, got {type(value).__name__}")
        log.error(f"Example: {example}")
        return False
    if len(value) == 0:
        log.error(f"{field} list cannot be empty")
        log.error("Add at least one entry to materialize")
        return False
    log.success(f"{field} list has {len(value)} entr{'y' if len(value) == 1 else 'ies'}")
    for item in value:
        if not isinstance(item, str):
            log.warning(f"{field} entry should be a string, got {type(item).__name__}: {item}")
        else:
            log.info(f"  - {item}")
    return True


def _validate_branch_field(log: Log, config: dict[str, Any]) -> None:
    branch_field = (
        "template-branch" if "template-branch" in config else "ref" if "ref" in config else None
    )
    if branch_field is None:
        return
    branch = config[branch_field]
    if not isinstance(branch, str):
        log.warning(f"{branch_field} should be a string, got {type(branch).__name__}: {branch}")
        log.warning("Example: 'main' or 'develop'")
    else:
        log.success(f"{branch_field} is valid: {branch}")


def _validate_host_field(log: Log, config: dict[str, Any]) -> None:
    if "template-host" not in config:
        return
    host = config["template-host"]
    if not isinstance(host, str):
        log.warning(f"template-host should be a string, got {type(host).__name__}: {host}")
        log.warning("Must be 'github' or 'gitlab'")
    elif host not in GIT_HOSTS:
        log.warning(f"template-host should be 'github' or 'gitlab', got: {host}")
        log.warning("Other hosts are not currently supported")
    else:
        log.success(f"template-host is valid: {host}")


def _validate_language_field(log: Log, config: dict[str, Any]) -> None:
    if "language" not in config:
        return
    language = config["language"]
    if not isinstance(language, str):
        log.warning(f"language should be a string, got {type(language).__name__}: {language}")
        log.warning("Example: 'python', 'go'")
    elif language.lower() not in _VALIDATORS:
        log.warning(f"language '{language}' is not recognized")
        log.warning(f"Supported languages: {', '.join(_VALIDATORS)}")
    else:
        log.success(f"language is valid: {language}")


def _validate_exclude_field(log: Log, config: dict[str, Any]) -> None:
    if "exclude" not in config:
        return
    exclude = config["exclude"]
    if not isinstance(exclude, list):
        log.warning(f"exclude should be a list, got {type(exclude).__name__}")
        log.warning("Example: exclude: ['.github/workflows/ci.yml']")
        return
    log.success(f"exclude list has {len(exclude)} path(s)")
    for path in exclude:
        if not isinstance(path, str):
            log.warning(f"exclude path should be a string, got {type(path).__name__}: {path}")
        else:
            log.info(f"  - {path}")


def _validate_optional_fields(log: Log, config: dict[str, Any]) -> None:
    log.debug("Validating optional fields")
    _validate_branch_field(log, config)
    _validate_host_field(log, config)
    _validate_language_field(log, config)
    _validate_exclude_field(log, config)


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
    if not _check_project_structure(log, target, str(language)):
        return None
    if not _validate_configuration_mode(log, config):
        return None
    return config


def _validate_config_fields(log: Log, config: dict[str, Any]) -> bool:
    """Field-level checks; these do NOT short-circuit so all errors surface at once."""
    passed = _validate_required_fields(log, config)
    if not _validate_repository_format(log, config):
        passed = False
    if config.get("templates") and not _validate_string_list(
        log, config, "templates", "templates: [core, tests, github]"
    ):
        passed = False
    if config.get("include") and not _validate_string_list(
        log, config, "include", "include: ['.github', '.gitignore']"
    ):
        passed = False
    _validate_optional_fields(log, config)
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
