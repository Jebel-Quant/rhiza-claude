"""Shared test fixtures for the rhiza-config plugin scripts.

The scripts under `plugin/scripts/` are standalone (run as
`uv run --python 3.12 --no-project python plugin/scripts/<x>.py`), not an installed
package, so put that directory on `sys.path` to import them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

# The one definition of the repo root. `conftest.py` sits at the top of `tests/`, so it is
# the only file whose depth is fixed regardless of how the mirrored tree beneath it is
# arranged — the modules under `tests/scripts/` each used to derive this themselves, and
# every one of them broke when the suite moved down a level to mirror `plugin/`.
#
# These two stay module-level because the `sys.path` insert has to happen at *collection*
# time: the test modules do `import status` at their own module level, long before any
# fixture runs. Tests reach them through the `repo_root` / `plugin_scripts` fixtures below.
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugin" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repo root — this checkout, not a temporary fixture repo."""
    return ROOT


@pytest.fixture(scope="session")
def plugin_scripts() -> Path:
    """The bundled `plugin/scripts/` directory the tests exercise."""
    return SCRIPTS


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo skeleton: a `.git` dir and a `pyproject.toml`."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def write_template(repo: Path, body: str) -> Path:
    """Write `.rhiza/template.yml` under `repo` and return its path."""
    rhiza = repo / ".rhiza"
    rhiza.mkdir(exist_ok=True)
    tmpl = rhiza / "template.yml"
    tmpl.write_text(body, encoding="utf-8")
    return tmpl


# ---------------------------------------------------------------------------
# Real-git fixtures for the sync port (test_sync*.py)
# ---------------------------------------------------------------------------

_HERMETIC_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00 +0000",
}


@pytest.fixture(autouse=True, scope="session")
def _drop_inherited_uv_constraint() -> Iterator[None]:
    """Keep this repo's dev-toolchain pins out of the repos the e2e tests build.

    The Makefile exports ``UV_CONSTRAINT`` so every ``uvx`` call it makes runs the pinned
    tools. That export reaches every subprocess — including the synced fixture repos,
    which run *their own* ``make fmt`` against *their own* ``.pre-commit-config.yaml``.
    prek then resolves their hooks under our constraints and fails outright::

        No solution found when resolving dependencies:
        Because there is no version of bandit==1.9.4 and you require bandit==1.9.4

    Scrubbing it here rather than narrowing the export is the honest fix: an end-to-end
    test exists to behave like a fresh user's repo, and a user's repo does not inherit
    this one's pins. A test that passed only because it did would be testing the wrong
    thing.

    ``UV_PYTHON`` is deliberately *kept*. The interpreter is a property of the machine
    running the suite, and letting a fixture resolve a different one would make these
    runs less reproducible, not more.
    """
    saved = os.environ.pop("UV_CONSTRAINT", None)
    yield
    if saved is not None:  # pragma: no cover - restores a var pytest is about to discard
        os.environ["UV_CONSTRAINT"] = saved


@pytest.fixture
def hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a hermetic git environment (no user/global config, fixed identity)."""
    for key, value in _HERMETIC_ENV.items():
        monkeypatch.setenv(key, value)


class Repo:
    """A tiny helper around a real git working tree used to build sync scenarios."""

    def __init__(self, path: Path) -> None:
        """Wrap the working tree rooted at *path*."""
        self.path = path

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command in this repo, returning the completed process."""
        return subprocess.run(  # noqa: S603
            ["git", *args], cwd=str(self.path), check=check, capture_output=True, text=True
        )

    def write(self, rel: str, content: str) -> Path:
        """Write *content* to *rel* (creating parents) and return the path."""
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read(self, rel: str) -> str:
        """Return the text of *rel*."""
        return (self.path / rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        """Return whether *rel* exists in the working tree."""
        return (self.path / rel).exists()

    def commit(self, message: str = "commit") -> str:
        """Stage everything and commit; return the new HEAD SHA."""
        self.git("add", "-A")
        self.git("commit", "-q", "--no-gpg-sign", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()


# The template the end-to-end tests sync from. Pinned for determinism — CI must not
# turn red merely because upstream released.
#
# `RHIZA_TEMPLATE_REF=latest` resolves the newest release instead, which is how the
# scheduled drift job asks "does the current template still agree with us?". That
# question needs its own signal: `make validate` was removed upstream between v1.1.3
# and v1.2.1, /quality scored the missing gate FAIL, and it surfaced only because
# somebody bumped the pin by hand. Nothing was watching.
TEMPLATE_REPO = "jebel-quant/rhiza"
# v1.3.0 was the first release carrying the language layers (`python-core`, `rust-core`,
# `go-core`) and the `rust-local`/`go-local` profiles. Pinning at or above it is what lets
# the Rust and Go end-to-end syncs run on every PR instead of skipping for want of a
# released profile. v1.3.2 carries the two patches these fixtures exercise most directly:
# `go-core` ships `internal/version/version_test.go` and `python-core` ships
# `tests/test_rhiza_packaging.py`, so a fresh repo's test gate is vacuous in no language
# now — which is what retired the strict `xfail` in `test_check_make_targets.py`.
PINNED_TEMPLATE_REF = "v1.3.2"


def resolve_template_ref() -> str:
    """Return the template ref to sync: the pin, an override, or the latest release.

    Reuses `status.py`'s tag helpers rather than adding a second resolver — they are
    already tested, and `/rhiza:status --check` answers the same question for users.
    """
    requested = os.environ.get("RHIZA_TEMPLATE_REF", PINNED_TEMPLATE_REF)
    if requested != "latest":
        return requested

    import status

    releases = [t for t in status._remote_tags("github", TEMPLATE_REPO) if status._parse_semver(t)]
    if not releases:
        # Skip rather than fall back to the pin: a silent fallback would make the
        # drift job pass while asking nothing, which is the blind spot it exists for.
        pytest.skip(f"could not list releases for {TEMPLATE_REPO}")
    return max(releases, key=lambda t: status._parse_semver(t))  # type: ignore[arg-type]


_RESOLVED_REF: str | None = None


def template_ref_value() -> str:
    """Resolve the template ref once per session, on first use rather than at import.

    This used to be a module-level `TEMPLATE_REF = resolve_template_ref()`, which was
    wrong in two ways under `RHIZA_TEMPLATE_REF=latest` (the drift job's path, and so the
    one least exercised locally): it listed remote tags during *collection*, making even a
    single unit-test run hit the network, and its `pytest.skip` fired at conftest import —
    where pytest raises `Failed` ("use allow_module_level=True") instead of skipping. Now
    the skip happens inside whichever test asked for the ref, which is what it meant.
    """
    global _RESOLVED_REF
    if _RESOLVED_REF is None:
        _RESOLVED_REF = resolve_template_ref()
    return _RESOLVED_REF


@pytest.fixture(scope="session")
def template_ref() -> str:
    """The template ref the end-to-end tests sync from."""
    return template_ref_value()


# ---------------------------------------------------------------------------
# Fixture repos for the command-outcome tests (test_check_make_targets.py)
#
# The commands are prose a model executes, so their *outcomes* can only be tested
# against a realistic tree. These build the three states a rhiza command actually
# meets, which is what the contract tests can't reach: they verify a command refers
# to things that exist, not that running it does the right thing.
# ---------------------------------------------------------------------------

# A stand-in for the make API the template sync delivers as .rhiza/rhiza.mk. Only the
# target names matter for probing — the recipes are never run (`make -n`).
SYNCED_MAKEFILE = """\
.PHONY: fmt typecheck docs-coverage deptry security rhiza-test test help
help: ; @echo help
fmt: ; @echo fmt
typecheck: ; @echo typecheck
docs-coverage: ; @echo docs-coverage
deptry: ; @echo deptry
security: ; @echo security
rhiza-test: ; @echo rhiza-test
test: ; @echo test
"""

# A reduced profile: `core` only, so the tests-bundle gates are legitimately absent.
PARTIAL_MAKEFILE = """\
.PHONY: fmt deptry help
help: ; @echo help
fmt: ; @echo fmt
deptry: ; @echo deptry
"""


# Template v1.4 retired the make layer: `Makefile` became a shim generated by
# `uvx rhiza-task shim`, whose `%:` rule forwards any target it cannot resolve to the
# pinned CLI. Every line here is load-bearing for the probe — `.DEFAULT_GOAL` is the
# near-miss the catch-all regex must not match, `help` is explicit in the real shim, and
# `e2e` is a repo-owned target that still carries the `##` convention.
SHIM_MAKEFILE = """\
RHIZA_TASK ?= rhiza-task@0.3.1
.DEFAULT_GOAL := help

help: ; @echo help

%: ; @echo would run $@ via $(RHIZA_TASK)

e2e:  ## Run the end-to-end suite
	@echo e2e
"""


@pytest.fixture
def unmanaged_repo(tmp_path: Path) -> Path:
    """A repo that was never rhiza-managed: no `.rhiza/` at all.

    `/quality` and `/update` must refuse this rather than score or sync it.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def managed_unsynced_repo(unmanaged_repo: Path, template_ref: str) -> Path:
    """Rhiza-managed but never synced — the state `/init` deliberately leaves behind.

    There is a `template.yml` but no `template.lock` and no makefile, so every gate is
    unavailable. Scoring this repo as broken was the bug the probe exists to prevent.
    The lock is the discriminator: see `makeless_synced_repo`, which differs only in
    having one and needs the opposite advice.
    """
    write_template(unmanaged_repo, f'repository: "{TEMPLATE_REPO}"\nref: "{template_ref}"\n')
    return unmanaged_repo


@pytest.fixture
def managed_synced_repo(managed_unsynced_repo: Path) -> Path:
    """Rhiza-managed *and* synced: the makefile and lock the sync delivers are present."""
    rhiza = managed_unsynced_repo / ".rhiza"
    (rhiza / "rhiza.mk").write_text(SYNCED_MAKEFILE, encoding="utf-8")
    (rhiza / "template.lock").write_text(
        'sha: "abc123"\nstrategy: merge\nfiles:\n  - ruff.toml\n  - Makefile\n', encoding="utf-8"
    )
    (managed_unsynced_repo / "Makefile").write_text("include .rhiza/rhiza.mk\n", encoding="utf-8")
    (managed_unsynced_repo / "ruff.toml").write_text('target-version = "py311"\n', encoding="utf-8")
    return managed_unsynced_repo


@pytest.fixture
def partial_profile_repo(managed_unsynced_repo: Path) -> Path:
    """A synced repo on a reduced profile, missing the tests-bundle gates."""
    (managed_unsynced_repo / ".rhiza" / "rhiza.mk").write_text(PARTIAL_MAKEFILE, encoding="utf-8")
    (managed_unsynced_repo / "Makefile").write_text("include .rhiza/rhiza.mk\n", encoding="utf-8")
    return managed_unsynced_repo


@pytest.fixture
def makeless_synced_repo(managed_unsynced_repo: Path) -> Path:
    """A repo synced to template v1.4 that kept no `Makefile` at all.

    The shim is a *repo-owned* file at v1.4, so restoring it is optional and a migrated
    repo may legitimately have none. What it does have is `.rhiza/template.lock`, which
    every sync writes at every version — the only thing separating this repo from
    `managed_unsynced_repo`, which needs the opposite advice.
    """
    (managed_unsynced_repo / ".rhiza" / "template.lock").write_text(
        'sha: "abc123"\nstrategy: merge\nfiles:\n  - ruff.toml\n', encoding="utf-8"
    )
    return managed_unsynced_repo


@pytest.fixture
def shim_repo(managed_unsynced_repo: Path) -> Path:
    """A repo on template v1.4: no `.rhiza/rhiza.mk`, a shim that answers everything.

    There is no `make.d/` to discover and nothing on disk that lists the tasks — they
    live in the pinned `rhiza-task` release — so this is the state in which probing can
    say nothing, rather than the state in which it says no.
    """
    (managed_unsynced_repo / "Makefile").write_text(SHIM_MAKEFILE, encoding="utf-8")
    return managed_unsynced_repo


# ---------------------------------------------------------------------------
# End-to-end: one genuinely synced repo, built once and shared
#
# The commands are prose a model executes, so the only way to test their outcomes is
# to run their script chains against a real repo synced from the real template. That
# setup is expensive, so it is session-scoped and every command's e2e test reuses it.
#
# These are NOT opt-in. The failures they catch are the ones that reached users:
# /quality unable to run at all, /update staging repo-owned files, /release skipping
# a version location. A test that only runs when someone remembers to set an env var
# would not have caught any of them.
# ---------------------------------------------------------------------------

# Run the bundled scripts the way the commands do — under a pinned interpreter via uv,
# never the system python3 (macOS ships 3.9, where sync.py's datetime.UTC crashes).
PY = ["uv", "run", "--python", "3.12", "--no-project", "python"]

E2E_TOOLS = ("git", "make", "uv", "uvx")


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    """Run a command in *cwd*, capturing output."""
    return subprocess.run(  # noqa: S603
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False
    )


def assert_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    """Assert a command exited 0, surfacing its output on failure."""
    assert result.returncode == 0, (
        f"{label} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
    )


@pytest.fixture(scope="session")
def synced_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real repo built by the /init chain and synced from the real template.

    Follows the documented path exactly — `uv init --lib`, the skeleton finisher, a
    first module, the `.rhiza/template.yml` pointer, python-version, license — then
    `scripts/sync.py`, which is what `/update` runs. Session-scoped: built once.

    Tests that mutate it must work on a copy (see `synced_repo_copy`), so ordering
    between tests can never matter.

    **The first module is seeded here, not by `/init`.** That makes this the wrong fixture
    for asking what a fresh repo lacks — `python_synced_repo` is the unseeded counterpart.
    """
    missing = [t for t in E2E_TOOLS if shutil.which(t) is None]
    if missing:
        pytest.skip(f"end-to-end tests need {', '.join(missing)}")

    scripts = SCRIPTS
    repo = tmp_path_factory.mktemp("e2e") / "widget"
    repo.mkdir()

    assert_ok(
        run_cmd(["uv", "init", "--lib", "--name", "widget", "--python", "3.12"], repo), "uv init"
    )
    for key, value in (("user.email", "e2e@example.com"), ("user.name", "E2E")):
        assert_ok(run_cmd(["git", "config", key, value], repo), f"git config {key}")

    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_skeleton.py"), str(repo), "--owner", "jebel-quant",
             "--repo", "widget", "--description", "End-to-end fixture for the rhiza plugin."],
            repo,
        ),
        "init_skeleton",
    )  # fmt: skip

    # A module and its mirrored test — the user's first module, which /init does not
    # scaffold. Trivial and fully covered so the template's coverage gate has something
    # real to measure.
    (repo / "src" / "widget" / "main.py").write_text(
        '"""Entry point for widget."""\n\n\ndef greeting() -> str:\n'
        '    """Return the greeting."""\n    return "hello"\n',
        encoding="utf-8",
    )
    (repo / "tests" / "widget").mkdir(parents=True)
    (repo / "tests" / "widget" / "test_main.py").write_text(
        '"""Tests for widget.main."""\n\nfrom widget.main import greeting\n\n\n'
        'def test_greeting() -> None:\n    """The greeting is returned."""\n'
        '    assert greeting() == "hello"\n',
        encoding="utf-8",
    )

    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_scaffold.py"), str(repo), "--host", "github",
             "--language", "python", "--template-repo", TEMPLATE_REPO,
             "--ref", template_ref_value()],
            repo,
        ),
        "init_scaffold",
    )  # fmt: skip
    assert_ok(
        run_cmd([*PY, str(scripts / "set_python_version.py"), str(repo),
                 "--python-version", "3.12"], repo),
        "set_python_version",
    )  # fmt: skip
    assert_ok(
        run_cmd([*PY, str(scripts / "set_license.py"), str(repo), "--license", "MIT",
                 "--owner", "jebel-quant"], repo),
        "set_license",
    )  # fmt: skip

    assert_ok(run_cmd(["git", "add", "-A"], repo), "git add")
    assert_ok(run_cmd(["git", "commit", "-qm", "feat: initial"], repo), "git commit")

    # The first sync: what /update runs, and what delivers the Makefile and rhiza.mk.
    sync = run_cmd([*PY, str(scripts / "sync.py"), "."], repo)
    assert sync.returncode in (0, 1), f"sync failed hard:\n{sync.stdout}\n{sync.stderr}"
    assert (repo / ".rhiza" / "template.lock").is_file(), "sync wrote no lock"
    return repo


@pytest.fixture(scope="session")
def gitlab_synced_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repo synced on the **gitlab-project** profile, from the same template.

    GitLab coverage was previously zero at the command level, which is how /update
    shipped with no `glab mr create` path at all. Most of that surface is testable
    without a GitLab account: `gitlab-project` is a *bundle selection* inside a
    template hosted on GitHub, so the platform-specific materialisation — `.gitlab-ci.yml`
    in, `.github/` out — can be verified here.

    What still cannot be covered this way is any `glab` invocation: those live only in
    command prose, never in a bundled script, so there is nothing for a test to drive.
    """
    missing = [t for t in E2E_TOOLS if shutil.which(t) is None]
    if missing:
        pytest.skip(f"end-to-end tests need {', '.join(missing)}")

    scripts = SCRIPTS
    repo = tmp_path_factory.mktemp("e2e-gitlab") / "widget"
    repo.mkdir()

    assert_ok(
        run_cmd(["uv", "init", "--lib", "--name", "widget", "--python", "3.12"], repo), "uv init"
    )
    for key, value in (("user.email", "e2e@example.com"), ("user.name", "E2E")):
        assert_ok(run_cmd(["git", "config", key, value], repo), f"git config {key}")
    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_skeleton.py"), str(repo), "--owner", "jebel-quant",
             "--repo", "widget", "--host", "gitlab", "--description", "GitLab e2e fixture."],
            repo,
        ),
        "init_skeleton",
    )  # fmt: skip
    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_scaffold.py"), str(repo), "--host", "gitlab",
             "--language", "python", "--template-repo", TEMPLATE_REPO,
             "--ref", template_ref_value()],
            repo,
        ),
        "init_scaffold --host gitlab",
    )  # fmt: skip
    assert_ok(run_cmd(["git", "add", "-A"], repo), "git add")
    assert_ok(run_cmd(["git", "commit", "-qm", "feat: initial"], repo), "git commit")

    sync = run_cmd([*PY, str(scripts / "sync.py"), "."], repo)
    assert sync.returncode in (0, 1), f"sync failed hard:\n{sync.stdout}\n{sync.stderr}"
    return repo


@pytest.fixture
def synced_repo_copy(synced_repo: Path, tmp_path: Path) -> Path:
    """A throwaway copy of the synced repo, for tests that mutate it."""
    target = tmp_path / "widget"
    shutil.copytree(synced_repo, target)
    return target


# ---------------------------------------------------------------------------
# End-to-end: the non-Python language axes
#
# #86 taught the plugin three languages — a language registry, per-language complexity
# tooling, gate discovery, language-aware badges — and none of it had ever run against a
# real crate or module. What was tested was the registry's internal coherence and
# discovery against fixtures written by hand, which cannot catch the things that actually
# broke: a pointer naming a profile no template defines, discovery reading one makefile
# where make reads a dozen, and a version location nothing writes.
#
# **Parameterised by language, not by assertion.** One `init` command, one template
# profile, one set of tools per language; the assertions live in the test file mirroring
# whichever script they cover and read their expectations from `language_profile.py` and
# from the synced tree. GitHub's runners ship both toolchains, so this needs no extra CI
# provisioning.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguageFixture:
    """What building a real repo in one language takes."""

    name: str
    tools: tuple[str, ...]
    """Binaries the scaffolding needs; absent ones skip rather than fail."""
    init: tuple[str, ...]
    """The language's own initialiser, run before the plugin's scripts."""
    after_skeleton: tuple[tuple[str, ...], ...] = ()
    """Extra `scripts/<name>.py` invocations `/init` makes for this language, after the
    skeleton and before the pointer. Each entry is the script name followed by its flags;
    the target is passed in. Only Python has one — `/skeleton` applies the Python version
    through its own procedure, so leaving `uv`'s `requires-python` as the sole record of it
    would build a repo `/init` never produces."""


_LANGUAGE_FIXTURES = {
    "python": LanguageFixture(
        name="python",
        tools=("uv", "git", "make"),
        init=("uv", "init", "--lib", "--name", "widget", "--python", "3.12"),
        after_skeleton=(("set_python_version.py", "--python-version", "3.12"),),
    ),
    "rust": LanguageFixture(
        name="rust",
        tools=("cargo", "git", "make", "uv"),
        init=("cargo", "init", "--lib", "--name", "widget"),
    ),
    "go": LanguageFixture(
        name="go",
        tools=("go", "git", "make", "uv"),
        # A Go module is identified by the path people `go get`, not by a bare name.
        init=("go", "mod", "init", "github.com/jebel-quant/widget"),
    ),
}


def language_profile_name(language: str, host: str = "github") -> str:
    """Return the profile `/init` writes for *language* on *host*.

    Read from the code that writes the pointer rather than repeated here: a test that
    hardcodes `rust-local` stops testing the mapping and starts testing itself.
    """
    import init_scaffold

    return init_scaffold.profile_for_host(host, language)


def language_template_ref(language: str) -> str:
    """Return the template ref *language*'s fixtures sync from.

    The same ref as everything else, unless `RHIZA_<LANG>_TEMPLATE_REF` overrides it. The
    override is left in place for exercising an unreleased language layer against a
    branch — it was how the Rust sync ran at all before v1.3.0 shipped `rust-local` — and
    is set by nothing now.
    """
    return os.environ.get(f"RHIZA_{language.upper()}_TEMPLATE_REF", template_ref_value())


def require_language_profile(language: str, ref: str) -> None:
    """Fail unless the template at *ref* defines the profile *language*'s pointer names.

    A **failure**, not a skip, since v1.3.0: the pinned ref defines `rust-local` and
    `go-local`, so an absence means either the pin names a ref that cannot serve such a
    repo (ours to fix) or upstream withdrew the profile (news the drift job exists to
    deliver, and files an issue about). Skipping either of those is how a language axis
    stops being covered while the suite still reads green — which is precisely what these
    fixtures were added to prevent.

    Only an unreadable template still skips: nothing was learned, so there is nothing to
    report.
    """
    import check_template_profile as ctp

    profile = language_profile_name(language)
    summary = ctp.check(TEMPLATE_REPO, ref, [profile])
    if summary["exit_code"] == ctp.EXIT_UNREADABLE:
        pytest.skip(f"could not read {TEMPLATE_REPO}@{ref}: {summary['error']}")
    assert not summary["missing"], (
        f"{TEMPLATE_REPO}@{ref} defines no {profile} profile "
        f"(it defines: {', '.join(summary['available'])}). Every {language} pointer /init "
        f"writes names that profile, so this ref cannot serve a {language} repo: either "
        "the pin is wrong or the template withdrew the profile."
    )


def _scaffold(repo: Path, language: str, *, description: str) -> None:
    """Run the /init chain for *language* in *repo*: init, skeleton, pointer, licence."""
    fixture = _LANGUAGE_FIXTURES[language]
    scripts = SCRIPTS
    # `git init` first: cargo initialises a repo itself, but only when it decides the
    # directory needs one, and the skeleton's author metadata comes from git identity.
    assert_ok(run_cmd(["git", "init", "-q", "-b", "main", "."], repo), "git init")
    assert_ok(run_cmd(list(fixture.init), repo), " ".join(fixture.init[:2]))
    for key, value in (("user.email", "e2e@example.com"), ("user.name", "E2E")):
        assert_ok(run_cmd(["git", "config", key, value], repo), f"git config {key}")
    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_skeleton.py"), str(repo), "--language", language,
             "--owner", "jebel-quant", "--repo", "widget", "--description", description],
            repo,
        ),
        f"init_skeleton --language {language}",
    )  # fmt: skip
    for script, *flags in fixture.after_skeleton:
        assert_ok(
            run_cmd([*PY, str(scripts / script), str(repo), *flags], repo),
            f"{script} {' '.join(flags)}",
        )
    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_scaffold.py"), str(repo), "--host", "github",
             "--language", language, "--template-repo", TEMPLATE_REPO,
             "--ref", language_template_ref(language)],
            repo,
        ),
        f"init_scaffold --language {language}",
    )  # fmt: skip
    assert_ok(
        run_cmd([*PY, str(scripts / "set_license.py"), str(repo), "--license", "MIT",
                 "--owner", "jebel-quant"], repo),
        "set_license",
    )  # fmt: skip


def _build_scaffolded(factory: pytest.TempPathFactory, language: str) -> Path:
    """Build an unsynced repo in *language* by the documented /init chain."""
    missing = [t for t in _LANGUAGE_FIXTURES[language].tools if shutil.which(t) is None]
    if missing:
        pytest.skip(f"the {language} end-to-end tests need {', '.join(missing)}")
    repo = factory.mktemp(f"e2e-{language}") / "widget"
    repo.mkdir()
    _scaffold(repo, language, description=f"End-to-end {language} fixture for the rhiza plugin.")
    return repo


def _build_synced(factory: pytest.TempPathFactory, language: str) -> Path:
    """Build a repo in *language* and sync it from the template's profile for it."""
    missing = [t for t in _LANGUAGE_FIXTURES[language].tools if shutil.which(t) is None]
    if missing:
        pytest.skip(f"the {language} end-to-end tests need {', '.join(missing)}")
    ref = language_template_ref(language)
    require_language_profile(language, ref)

    scripts = SCRIPTS
    repo = factory.mktemp(f"e2e-{language}-synced") / "widget"
    repo.mkdir()
    _scaffold(repo, language, description=f"Synced {language} fixture for the rhiza plugin.")
    assert_ok(run_cmd(["git", "add", "-A"], repo), "git add")
    assert_ok(run_cmd(["git", "commit", "-qm", "feat: initial"], repo), "git commit")

    sync = run_cmd([*PY, str(scripts / "sync.py"), "."], repo)
    assert sync.returncode in (0, 1), f"sync failed hard:\n{sync.stdout}\n{sync.stderr}"
    assert (repo / ".rhiza" / "template.lock").is_file(), "sync wrote no lock"
    return repo


@pytest.fixture(scope="session")
def python_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real package built by the /init chain — `uv init --lib` and the scripts after it.

    The Python member of the same family as `rust_crate` and `go_module`, and the one that
    was missing: every other Python end-to-end fixture (`synced_repo`, `gitlab_synced_repo`)
    **hand-writes a module and a mirrored test** so the template's coverage gate has
    something real to measure. That is a fair fixture for what those tests ask, and it is
    also why nothing here had ever seen what a bare `/init` actually leaves behind — which
    is a package with no test at all.
    """
    return _build_scaffolded(tmp_path_factory, "python")


@pytest.fixture(scope="session")
def python_synced_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Python repo synced from `github-project`, with **nothing seeded by hand**.

    The unseeded counterpart of `synced_repo`: same profile, same ref, but built by
    `_build_synced` like the Rust and Go fixtures, so its tree is exactly what a user gets
    from `/init` then `/update` and no more. Prefer `synced_repo` for anything that needs a
    module to measure; use this one to ask what a fresh repo *lacks*.
    """
    return _build_synced(tmp_path_factory, "python")


@pytest.fixture(scope="session")
def rust_crate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real crate built by the /init chain — `cargo init --lib` and the scripts after it.

    No sync, so nothing here depends on the template at all: the scaffolding, the pointer,
    language detection, structure validation, the licence and the badges are all decided
    before `/rhiza:update` ever runs, and this is where they are asserted.
    """
    return _build_scaffolded(tmp_path_factory, "rust")


@pytest.fixture(scope="session")
def rust_synced_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Rust crate genuinely synced from the template's Rust profile.

    Built fresh rather than copied from `rust_crate` so the pointer records the ref the
    sync actually used. Fails rather than skips when the ref defines no Rust profile — see
    :func:`require_language_profile`.
    """
    return _build_synced(tmp_path_factory, "rust")


@pytest.fixture(scope="session")
def go_module(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real Go module built by the /init chain — `go mod init` and the scripts after it.

    The counterpart of `rust_crate`, and the leaner one: `go mod init` writes a single
    file and `go.mod` has no metadata to fill in, so what the skeleton adds is a package
    doc and a README.
    """
    return _build_scaffolded(tmp_path_factory, "go")


@pytest.fixture(scope="session")
def go_synced_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Go module genuinely synced from the template's `go-local` profile."""
    return _build_synced(tmp_path_factory, "go")


@pytest.fixture
def make_repo(tmp_path: Path, hermetic_git: None) -> Iterator[Callable[[str], Repo]]:
    """Return a factory that creates initialised git repos under the temp dir."""
    counter = {"n": 0}

    def _make(name: str = "repo") -> Repo:
        counter["n"] += 1
        path = tmp_path / f"{name}{counter['n']}"
        path.mkdir()
        repo = Repo(path)
        repo.git("init", "-q", "-b", "main", ".")
        return repo

    yield _make


# --------------------------------------------------------------------------- #
# Fake forge CLIs, cross-platform
# --------------------------------------------------------------------------- #
#
# `test_platform_cli.py` and `test_pr_status.py` both need a fake `gh`/`glab` that
# records its argv, so the assertion is "the CLI really was invoked, with these
# arguments" rather than "our own code agrees with itself". Both used to write a
# bash-shebang script named `gh` and put it on PATH — which works on POSIX and cannot
# work on Windows, for two independent reasons:
#
#   * `CreateProcess` given a bare name only appends `.exe`, so an extensionless
#     script is unreachable however PATH is set; and
#   * a `.cmd` shim, the usual answer, re-expands its arguments through `cmd.exe`,
#     which cannot carry an argument containing a newline — and the GitLab `pr-create`
#     path passes exactly that, an inline multi-line `--description`.
#
# So the delivery mechanism differs by platform while the stub itself does not. POSIX
# gets a real shebang script and a real `execve`. Windows routes the module's own
# `shutil.which`/`subprocess.run` to the same stub through the interpreter: argv, exit
# code and stdout are observed identically, one layer in rather than one process out.
# What Windows does *not* prove is that PATH lookup works there — which is the shipped
# code's `shutil.which` call, and is not what these tests are about.


@pytest.fixture
def stub_cli_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str, str], Path]:
    """Return ``install(name, body)`` putting a fake CLI named *name* on PATH.

    *body* is the Python source of the stub, minus the shebang. It runs with the real
    argv the code under test passed, so it can log `sys.argv[1:]`, print canned stdout
    and choose an exit code.

    A fixture rather than a plain helper so `tests/scripts/` can reach it: pytest injects
    conftest fixtures by name, while importing a function from `conftest` would need
    `tests/` on `sys.path`.
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    stubs: dict[str, Path] = {}

    def install(name: str, body: str) -> Path:
        impl = bin_dir / f"{name}_stub.py"
        impl.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        stubs[name] = impl
        if os.name != "nt":
            launcher = bin_dir / name
            launcher.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
            launcher.chmod(0o755)
        return impl

    if os.name == "nt":
        real_which, real_run = shutil.which, subprocess.run

        def fake_which(cmd: str, *args: object, **kwargs: object) -> str | None:
            """Resolve a stubbed name to its implementation; defer to the real one."""
            if cmd in stubs:
                return str(stubs[cmd])
            return real_which(cmd, *args, **kwargs)  # type: ignore[arg-type]

        def fake_run(command: object, *args: object, **kwargs: object) -> object:
            """Run a stub through the interpreter; pass everything else straight on."""
            if isinstance(command, list) and command:
                first = str(command[0])
                if first.endswith("_stub.py"):
                    command = [sys.executable, *[str(c) for c in command]]
            return real_run(command, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(shutil, "which", fake_which)
        monkeypatch.setattr(subprocess, "run", fake_run)
    else:
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    return install
