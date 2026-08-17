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
from _rhiza_common import SyncError, has_drive_letter  # noqa: E402
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
        # The Windows spellings are part of that set, not an afterthought: without them
        # `C:/Users/dev/template` matched none of these prefixes and was pasted onto the
        # GitHub base, so the sync tried to clone `https://github.com/C:/Users/... .git`.
        if (
            "://" in self.repository
            or self.repository.startswith(("/", "./", "../", "\\", ".\\", "..\\"))
            or has_drive_letter(self.repository)
        ):
            return self.repository
        if self.host == "github":
            return f"https://github.com/{self.repository}.git"
        if self.host == "gitlab":
            return f"https://gitlab.com/{self.repository}.git"
        raise SyncError(f"Unsupported template-host: {self.host}. Must be 'github' or 'gitlab'.")


# Never delivered, whatever the config says: this is the consumer's own pointer at the
# template, and a template that ships a copy of one would otherwise overwrite it and
# retarget the repo. The deletion side of the same rule is `_PROTECTED` in `_rhiza_lock`.
_ALWAYS_EXCLUDED = ".rhiza/template.yml"


def normalise_excludes(entries: list[str]) -> set[str]:
    """Normalise configured ``exclude:`` entries into comparable **destination** paths.

    `exclude:` is written in destination paths, because that is the only form a consumer
    knows — it is where the file lands in their repo. So the entries are taken as given
    and merely tidied: separators forward-slashed, a leading ``./`` and a trailing ``/``
    dropped, blanks discarded.

    Nothing here consults the template clone. Resolving these against the clone is what
    made bundle-sourced exclusions vanish: a destination path need not exist at the clone
    root at all — under a sparse checkout of ``bundles/…`` it usually does not — and an
    entry that failed to resolve was dropped silently rather than honoured.

    The repo's own pointer at the template is always in the set, whatever the config says:

    >>> sorted(normalise_excludes(["docs/", "./Makefile", "   "]))
    ['.rhiza/template.yml', 'Makefile', 'docs']
    """
    result = {
        cleaned
        for cleaned in (
            entry.strip().replace("\\", "/").removeprefix("./").rstrip("/") for entry in entries
        )
        if cleaned
    }
    result.add(_ALWAYS_EXCLUDED)
    return result


def is_excluded(dest: str, excludes: set[str]) -> bool:
    """Whether the destination path *dest* is excluded outright or sits under an excluded dir.

    The directory case has to be matched by prefix rather than by expanding the directory
    into its files, which is what :func:`normalise_excludes` used to do against the clone.
    Once matching moves to destination paths there is no directory on disk to expand.

    The prefix carries the separator, so a directory covers what is under it without a
    sibling whose name merely starts the same way being swept in:

    >>> excludes = normalise_excludes(["docs"])
    >>> is_excluded("docs", excludes), is_excluded("docs/index.md", excludes)
    (True, True)
    >>> is_excluded("docsite/index.md", excludes)
    False
    """
    return dest in excludes or any(dest.startswith(f"{entry}/") for entry in excludes)


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
