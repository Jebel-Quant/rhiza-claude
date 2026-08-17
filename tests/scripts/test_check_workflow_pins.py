"""Tests for the workflow pin checker (`scripts/check_workflow_pins.py`).

Two jobs, as with the other checkers: drive each rule against synthetic workflows, and
assert this repo's real ones pass — the second is what makes the gate mean anything.

Both historical failures are pinned as tests rather than described: one `setup-uv` call
site kept a `# v7.1.1` comment through a bump to v10.0.0 (#183), and the same file passed
no `version:` input at all, floating uv in the job that decides whether a release tag is
created (#185).
"""

from __future__ import annotations

from pathlib import Path

import check_workflow_pins as cwp
import pytest

_SHA = "ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d"
_OTHER_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def _workflow(root: Path, name: str, body: str) -> Path:
    """Write a workflow file under *root*, creating the directory."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def _uv_step(sha: str = _SHA, comment: str = "v10.0.0", version: str | None = "0.12.1") -> str:
    """One `Install uv` step, optionally pinning the uv version."""
    pin = f"          version: '{version}'\n" if version is not None else ""
    return (
        "      - name: Install uv\n"
        f"        uses: astral-sh/setup-uv@{sha} # {comment}\n"
        "        with:\n"
        f"{pin}          python-version: '3.12'\n"
    )


def _job(steps: str) -> str:
    """A minimal single-job workflow wrapping *steps*."""
    return "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n" + steps


@pytest.fixture
def workflows(tmp_path: Path) -> Path:
    """A workflows directory whose two files agree about every pin."""
    root = tmp_path / ".github" / "workflows"
    _workflow(root, "ci.yml", _job(_uv_step()))
    _workflow(root, "book.yml", _job(_uv_step()))
    return root


def test_agreeing_pins_are_clean(workflows):
    assert cwp.check_workflows(workflows) == []


# --- rule 1: pinned to a SHA, annotated with a version ------------------------


def test_flags_an_action_pinned_to_a_tag(workflows):
    _workflow(workflows, "book.yml", _job(_uv_step(sha="v10.0.0", comment="v10.0.0")))
    violations = cwp.check_workflows(workflows)
    assert any("not a SHA" in v for v in violations)


def test_flags_a_sha_pin_with_no_version_comment(workflows):
    """The SHA binds; the comment is the half a reviewer can act on."""
    _workflow(
        workflows,
        "book.yml",
        _job(
            "      - name: Checkout\n"
            f"        uses: actions/checkout@{_OTHER_SHA}\n"
            "        with:\n          fetch-depth: 0\n"
        ),
    )
    violations = cwp.check_workflows(workflows)
    assert any("has no '# <version>' comment" in v for v in violations)


# --- rule 2: call sites of one action agree -----------------------------------


def test_flags_two_shas_for_one_action(workflows):
    _workflow(workflows, "book.yml", _job(_uv_step(sha=_OTHER_SHA)))
    violations = cwp.check_workflows(workflows)
    assert any("astral-sh/setup-uv SHA disagrees" in v for v in violations)


def test_flags_one_sha_with_two_version_comments(workflows):
    """#183 exactly: the SHA was bumped and one comment was not carried along."""
    _workflow(workflows, "book.yml", _job(_uv_step(comment="v7.1.1")))
    (violation,) = [v for v in cwp.check_workflows(workflows) if "version comment" in v]
    assert "book.yml:7='v7.1.1'" in violation
    assert "ci.yml:7='v10.0.0'" in violation


def test_a_subpath_action_is_held_to_its_parent(workflows):
    """`actions/cache/save` ships from `actions/cache`'s tree, so it shares its SHA."""
    _workflow(
        workflows,
        "cache.yml",
        _job(
            f"      - uses: actions/cache@{_SHA} # v6.1.0\n"
            f"      - uses: actions/cache/save@{_OTHER_SHA} # v6.1.0\n"
        ),
    )
    violations = cwp.check_workflows(workflows)
    assert any("actions/cache SHA disagrees" in v for v in violations)


def test_two_different_actions_may_hold_different_shas(workflows):
    _workflow(
        workflows,
        "book.yml",
        _job(_uv_step() + f"      - uses: actions/checkout@{_OTHER_SHA} # v7.0.1\n"),
    )
    assert cwp.check_workflows(workflows) == []


# --- rule 3: the uv version input ---------------------------------------------


def test_flags_a_setup_uv_step_that_pins_no_uv_version(workflows):
    """#185's first half: the job that guards a release tag floated its uv."""
    _workflow(workflows, "auto-tag.yml", _job(_uv_step(version=None)))
    violations = cwp.check_workflows(workflows)
    assert any("passes no 'version:' input" in v and "auto-tag.yml" in v for v in violations)


def test_flags_two_uv_versions(workflows):
    _workflow(workflows, "book.yml", _job(_uv_step(version="0.11.0")))
    violations = cwp.check_workflows(workflows)
    assert any("uv version input disagrees" in v for v in violations)


def test_the_version_input_is_found_after_a_comment(workflows):
    """A commented `with:` block is the usual shape here, so a comment cannot end a step."""
    _workflow(
        workflows,
        "book.yml",
        _job(
            "      - name: Install uv\n"
            f"        uses: astral-sh/setup-uv@{_SHA} # v10.0.0\n"
            "        # Pinned so a uv release cannot change what CI measures.\n"
            "        with:\n          version: '0.12.1'\n"
        ),
    )
    assert cwp.check_workflows(workflows) == []


def test_the_next_step_is_not_read_as_this_step(workflows):
    """A later step's `version:` must not be mistaken for this one's pin."""
    _workflow(
        workflows,
        "book.yml",
        _job(
            _uv_step(version=None) + f"      - uses: actions/setup-node@{_OTHER_SHA} # v7.0.0\n"
            "        with:\n          version: '0.12.1'\n"
        ),
    )
    violations = cwp.check_workflows(workflows)
    assert any("passes no 'version:' input" in v for v in violations)


def test_python_version_is_not_the_uv_version(workflows):
    """`python-version:` is a different input, and legitimately differs per job."""
    _workflow(
        workflows,
        "book.yml",
        _job(
            "      - name: Install uv\n"
            f"        uses: astral-sh/setup-uv@{_SHA} # v10.0.0\n"
            "        with:\n          python-version: '3.13'\n          version: '0.12.1'\n"
        ),
    )
    assert cwp.check_workflows(workflows) == []


# --- what gets scanned ---------------------------------------------------------


def test_a_composite_action_beside_the_workflows_is_scanned(workflows):
    """Moving a pin into a composite action must not be a way to leave the gate.

    The forward slash in the expected path is the assertion, not an accident: this is the
    only violation that carries a nested path, and `str(Path)` spelled it
    `shared\\action.yaml` on Windows until the reporter switched to `as_posix`.
    """
    nested = workflows / "shared"
    _workflow(
        nested,
        "action.yaml",
        "runs:\n  using: composite\n  steps:\n"
        f"    - uses: astral-sh/setup-uv@{_OTHER_SHA} # v10.0.0\n"
        "      with:\n        version: '0.12.1'\n",
    )
    violations = cwp.check_workflows(workflows)
    assert any("shared/action.yaml" in v for v in violations)


def test_a_line_that_is_not_a_pin_is_ignored(workflows):
    """Local actions (`uses: ./x`) and reusable workflows are not SHA-pinned actions."""
    _workflow(
        workflows,
        "book.yml",
        _job("      - uses: ./.github/actions/setup\n") + "# uses: not-a-step\n",
    )
    assert cwp.check_workflows(workflows) == []


def test_an_empty_directory_is_vacuously_clean(tmp_path):
    assert cwp.check_workflows(tmp_path) == []


class TestPin:
    @pytest.mark.parametrize(
        ("action", "repository"),
        [
            ("actions/cache/save", "actions/cache"),
            ("github/codeql-action/init", "github/codeql-action"),
            ("astral-sh/setup-uv", "astral-sh/setup-uv"),
        ],
    )
    def test_repository_drops_any_subpath(self, action, repository):
        assert cwp.Pin(action, _SHA, "v1.0.0", "ci.yml:1").repository == repository

    def test_a_step_without_a_with_block_has_no_version_input(self, workflows):
        path = _workflow(
            workflows, "book.yml", _job(f"      - uses: actions/checkout@{_OTHER_SHA} # v7.0.1\n")
        )
        (pin,) = cwp.collect_pins(path, "book.yml")
        assert pin.version_input is None
        assert pin.where == "book.yml:6"


# --- main() / CLI --------------------------------------------------------------


def test_main_passes_on_agreeing_pins(workflows, capsys):
    assert cwp.main(["--workflows", str(workflows)]) == 0
    assert "workflow pins agree" in capsys.readouterr().out


def test_main_reports_each_problem(workflows, capsys):
    _workflow(workflows, "book.yml", _job(_uv_step(comment="v7.1.1")))
    assert cwp.main(["--workflows", str(workflows)]) == 1
    err = capsys.readouterr().err
    assert "version comment disagrees" in err
    assert "1 pin problem(s)" in err


def test_main_reports_a_missing_directory(tmp_path, capsys):
    assert cwp.main(["--workflows", str(tmp_path / "nope")]) == 1
    assert "No workflows directory" in capsys.readouterr().err


def test_main_defaults_to_the_repos_own_workflows(repo_root: Path, monkeypatch, capsys):
    """The hook passes no argument, so a broken default would gate nothing at all."""
    monkeypatch.chdir(repo_root)
    assert cwp.main([]) == 0
    assert "workflow pins agree" in capsys.readouterr().out


# --- the real repo -------------------------------------------------------------


def test_this_repos_workflow_pins_agree(repo_root: Path):
    """The assertion that matters: one SHA and one uv version, everywhere."""
    assert cwp.check_workflows(repo_root / cwp.WORKFLOWS_DIR) == []


def test_every_setup_uv_call_site_pins_uv(repo_root: Path):
    """Stated as a count, so a new job that forgets the input is visible here too."""
    pins = [
        pin
        for path in sorted((repo_root / cwp.WORKFLOWS_DIR).glob("*.yml"))
        for pin in cwp.collect_pins(path, path.name)
        if pin.repository == cwp.UV_ACTION
    ]
    assert len(pins) >= 6, "setup-uv call sites vanished — this test is measuring nothing"
    assert {pin.version_input for pin in pins} == {"0.12.1"}
