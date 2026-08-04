#!/usr/bin/env python3
"""Is `template.yml` well-formed? — `validate.py`'s configuration half.

Split from the structure checks because the two answer different questions and fail
differently. Structure asks about the repo on disk; this asks about the config the user
wrote, where the division that matters is **fatal versus advisory**:

- :func:`validate_configuration_mode`, :func:`validate_required_fields`,
  :func:`validate_repository_format` and :func:`validate_string_list` return a verdict.
  Without a selection mode or a `repository`, the sync has nothing to do.
- :func:`validate_optional_fields` returns nothing at all. A malformed `template-host` is
  worth saying out loud, but it must not stop a sync that would otherwise work.

Every message pairs the fault with the fix. These are read by someone whose sync just
refused to run, so "must be in format 'owner/repo'" is followed by an example rather than
left as a specification.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _validate_log import Log  # noqa: E402
from _validate_structure import VALIDATORS  # noqa: E402

# Hosts the template may target; mirrors rhiza.models.template.GitHost.
GIT_HOSTS = ("github", "gitlab")


def _repo_field(config: dict[str, Any]) -> str | None:
    """Return whichever repository key *config* uses, or None when it has neither."""
    for field in ("template-repository", "repository"):
        if field in config:
            return field
    return None


def validate_profiles_field(log: Log, config: dict[str, Any]) -> bool | None:
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


def _report_mode(log: Log, config: dict[str, Any], *, profiles: bool, templates: bool) -> None:
    """Announce which selection mode the config resolved to."""
    if profiles:
        log.success(f"Using profile mode (profiles: {config['profiles']})")
    elif templates and bool(config.get("include")):
        log.success("Using hybrid mode (templates + include)")
    elif templates:
        log.success("Using template-based mode")
    else:
        log.success("Using path-based mode")


def validate_configuration_mode(log: Log, config: dict[str, Any]) -> bool:
    """Validate the profiles/templates/include selection mode."""
    log.debug("Validating configuration mode")
    has_templates = bool(config.get("templates"))
    has_include = bool(config.get("include"))

    profiles_valid = validate_profiles_field(log, config)
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

    _report_mode(log, config, profiles=has_profiles, templates=has_templates)
    return True


def validate_required_fields(log: Log, config: dict[str, Any]) -> bool:
    """Require a 'template-repository' or 'repository' string field."""
    log.debug("Validating required fields")
    repo_field = _repo_field(config)
    if repo_field is None:
        log.error("Missing required field: 'template-repository' or 'repository'")
        log.error("Add 'template-repository' or 'repository' to your template.yml")
        return False

    repo_value = config[repo_field]
    if not isinstance(repo_value, str):
        log.error(f"Field '{repo_field}' must be of type str, got {type(repo_value).__name__}")
        log.error(f"Fix the type of '{repo_field}' in template.yml")
        return False
    log.success(f"Field '{repo_field}' is present and valid")
    return True


def validate_repository_format(log: Log, config: dict[str, Any]) -> bool:
    """Check the repository field is in 'owner/repo' form."""
    log.debug("Validating repository format")
    repo_field = _repo_field(config)
    if repo_field is None:
        return True  # caught by validate_required_fields
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


def validate_string_list(log: Log, config: dict[str, Any], field: str, example: str) -> bool:
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
    _log_entries(log, field, value)
    return True


def _log_entries(log: Log, field: str, values: list[Any]) -> None:
    """Echo each entry of a list field, warning on any that is not a string."""
    for item in values:
        if not isinstance(item, str):
            log.warning(f"{field} entry should be a string, got {type(item).__name__}: {item}")
        else:
            log.info(f"  - {item}")


def _validate_branch_field(log: Log, config: dict[str, Any]) -> None:
    """Warn if the branch/ref field is present but not a string."""
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
    """Warn if template-host is non-string or an unsupported host."""
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
    """Warn if the language field is non-string or unrecognized."""
    if "language" not in config:
        return
    language = config["language"]
    if not isinstance(language, str):
        log.warning(f"language should be a string, got {type(language).__name__}: {language}")
        log.warning("Example: 'python', 'go', 'rust'")
    elif language.lower() not in VALIDATORS:
        log.warning(f"language '{language}' is not recognized")
        log.warning(f"Supported languages: {', '.join(VALIDATORS)}")
    else:
        log.success(f"language is valid: {language}")


def _validate_exclude_field(log: Log, config: dict[str, Any]) -> None:
    """Warn if the exclude field is malformed."""
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


def validate_optional_fields(log: Log, config: dict[str, Any]) -> None:
    """Run the non-fatal optional-field checks.

    Returns nothing on purpose: none of these can fail a validation. A malformed
    `template-host` deserves a warning, not a refusal to sync.
    """
    log.debug("Validating optional fields")
    _validate_branch_field(log, config)
    _validate_host_field(log, config)
    _validate_language_field(log, config)
    _validate_exclude_field(log, config)
