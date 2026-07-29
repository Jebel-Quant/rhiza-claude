"""Parse and validate `.rhiza/template.yml` — the sync's input contract.

Answers one question: which template repository, at which ref, with which
profiles/bundles/includes. Nothing here touches git or the filesystem beyond reading
that one file, so the whole module is testable with a string.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_common import SyncError, log  # noqa: E402
from _rhiza_yaml import as_list, load_yaml  # noqa: E402

_DEFAULT_BUNDLES_PATH = ".rhiza/template-bundles.yml"

@dataclass(frozen=True)
class Template:
    """The parsed `.rhiza/template.yml` fields sync needs."""

    repository: str
    ref: str
    host: str = "github"
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    bundles_path: str = _DEFAULT_BUNDLES_PATH

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Template:
        """Build a :class:`Template` from a parsed template.yml dict, honouring key aliases."""
        repository = config.get("repository") or config.get("template-repository") or ""
        ref = config.get("ref") or config.get("template-branch") or ""
        return cls(
            repository=str(repository),
            ref=str(ref),
            host=str(config.get("template-host", "github")),
            include=as_list(config.get("include")),
            exclude=as_list(config.get("exclude")),
            templates=as_list(config.get("templates")),
            profiles=as_list(config.get("profiles")),
            bundles_path=str(config.get("template-bundles-path", _DEFAULT_BUNDLES_PATH)),
        )

    @property
    def git_url(self) -> str:
        """Return the HTTPS clone URL for the configured repository and host.

        Raises:
            SyncError: If the repository is unset or the host is unsupported.
        """
        if not self.repository:
            raise SyncError("template-repository is not configured in template.yml")
        # A full URL or local/file path (self-hosted or under test) is used verbatim.
        if "://" in self.repository or self.repository.startswith(("/", "./", "../")):
            return self.repository
        if self.host == "github":
            return f"https://github.com/{self.repository}.git"
        if self.host == "gitlab":
            return f"https://gitlab.com/{self.repository}.git"
        raise SyncError(f"Unsupported template-host: {self.host}. Must be 'github' or 'gitlab'.")


def load_template(target: Path, template_file: Path) -> Template:
    """Load and validate the template config, raising :class:`SyncError` on any problem."""
    if not template_file.exists():
        raise SyncError(f"No template.yml found at {template_file}")
    try:
        config = load_yaml(template_file)
    except (OSError, ValueError) as exc:
        raise SyncError(f"Could not read {template_file}: {exc}") from exc

    template = Template.from_config(config)
    if not template.repository:
        raise SyncError("template-repository is required in template.yml")
    if not template.templates and not template.include and not template.profiles:
        raise SyncError("template.yml must set at least one of: templates, profiles, include")
    return template


# ---------------------------------------------------------------------------
# Bundle resolution (profiles/templates -> file paths)
# ---------------------------------------------------------------------------
