"""Tests for the subprocess-discipline gate (`scripts/check_subprocess_discipline.py`).

The property under test is narrow and worth stating plainly: **launching a process
correctly is not the same as noticing it failed.** Ruff's `S` rules cover the first; this
covers the second, which is the failure mode that would let a broken sync report success.

Every fixture below is a synthetic `plugin/scripts/` tree, so the checker is exercised
through the same path it takes over the real one — including the layout constant it uses
to find the scripts directory.
"""

from __future__ import annotations

import check_subprocess_discipline as csd
import pytest


@pytest.fixture
def repo(tmp_path):
    """A repo root with an empty `plugin/scripts/`, ready for a module to be written in."""
    (tmp_path / "plugin" / "scripts").mkdir(parents=True)
    return tmp_path


def write(repo, body: str, name: str = "mod.py"):
    """Write *body* as a module under the repo's `plugin/scripts/`."""
    path = repo / "plugin" / "scripts" / name
    path.write_text(body, encoding="utf-8")
    return path


# --- rule 1: `check=` must be explicit ---------------------------------------


def test_an_omitted_check_is_a_violation(repo):
    """`subprocess.run` defaults to check=False — silently ignoring failure."""
    write(repo, "import subprocess\n\n\ndef go():\n    subprocess.run(['git'])\n")
    (violation,) = csd.check(repo)
    assert "omits `check=`" in violation
    assert "plugin/scripts/mod.py:5" in violation


def test_check_true_is_always_fine(repo):
    write(
        repo,
        "import subprocess\n\n\ndef go():\n    subprocess.run(['git'], check=True)\n",
    )
    assert csd.check(repo) == []


def test_check_call_and_check_output_need_no_check_keyword(repo):
    """They raise on a non-zero exit by definition, so `check=` does not apply."""
    write(
        repo,
        "import subprocess\n\n\ndef go():\n"
        "    subprocess.check_call(['git'])\n"
        "    subprocess.check_output(['git'])\n",
    )
    assert csd.check(repo) == []


# --- rule 2: a check=False call must account for the returncode ---------------


def test_check_false_without_any_accounting_is_a_violation(repo):
    write(
        repo,
        "import subprocess\n\n\ndef go():\n"
        "    result = subprocess.run(['git'], check=False)\n"
        "    return result.stdout\n",
    )
    (violation,) = csd.check(repo)
    assert "never accounts for the returncode" in violation


def test_inspecting_the_returncode_satisfies_the_rule(repo):
    write(
        repo,
        "import subprocess\n\n\ndef go():\n"
        "    result = subprocess.run(['git'], check=False)\n"
        "    return result.returncode == 0\n",
    )
    assert csd.check(repo) == []


def test_returning_the_completed_process_satisfies_the_rule(repo):
    """Handing the process back delegates the decision — the caller is then held to it."""
    write(
        repo,
        "import subprocess\n\n\n"
        "def go() -> subprocess.CompletedProcess[str]:\n"
        "    return subprocess.run(['git'], check=False)\n",
    )
    assert csd.check(repo) == []


def test_an_unannotated_function_does_not_get_the_completed_process_arm(repo):
    """The arm is granted by the *declared* contract, not by guessing at the return."""
    write(
        repo,
        "import subprocess\n\n\ndef go():\n    return subprocess.run(['git'], check=False)\n",
    )
    assert len(csd.check(repo)) == 1


def test_the_innermost_function_is_the_one_judged(repo):
    """A nested helper's own handling is the question, not its enclosing function's.

    `_skeleton_common.git_identity` has exactly this shape: the outer function mentions no
    returncode, and the nested `read` is where the decision lives.
    """
    write(
        repo,
        "import subprocess\n\n\ndef outer():\n"
        "    def read():\n"
        "        result = subprocess.run(['git'], check=False)\n"
        "        return result.returncode\n"
        "    return read()\n",
    )
    assert csd.check(repo) == []


def test_a_module_level_call_has_no_enclosing_function(repo):
    """Nothing to inspect the code, so it must be justified explicitly."""
    write(repo, "import subprocess\n\nsubprocess.run(['git'], check=False)\n")
    (violation,) = csd.check(repo)
    assert "never accounts for the returncode" in violation


# --- rule 3: an rc-ignored marker needs a reason -----------------------------


def test_a_justified_marker_above_the_call_satisfies_the_rule(repo):
    write(
        repo,
        "import subprocess\n\n\ndef go():\n"
        "    # rc-ignored: exits 1 when the key is unset, which is the answer\n"
        "    result = subprocess.run(['git'], check=False)\n"
        "    return result.stdout\n",
    )
    assert csd.check(repo) == []


def test_a_marker_on_the_call_line_also_counts(repo):
    write(
        repo,
        "import subprocess\n\n\ndef go():\n"
        "    subprocess.run(['git'], check=False)  # rc-ignored: best effort\n",
    )
    assert csd.check(repo) == []


def test_a_bare_marker_is_rejected(repo):
    """A marker with no reason silences the checker without thinking — the thing to stop."""
    write(
        repo,
        "import subprocess\n\n\ndef go():\n"
        "    # rc-ignored:\n"
        "    subprocess.run(['git'], check=False)\n",
    )
    (violation,) = csd.check(repo)
    assert "needs a reason after the colon" in violation


def test_a_marker_on_the_very_first_line_does_not_underflow(repo):
    """`lineno - 2` must not wrap around to the end of the file."""
    write(repo, "import subprocess\nsubprocess.run(['git'], check=False)  # rc-ignored: fine\n")
    assert csd.check(repo) == []


# --- what is and isn't a subprocess launch -----------------------------------


def test_an_unrelated_run_method_is_ignored(repo):
    """Only `subprocess.<launcher>` counts — a `runner.run(...)` is somebody else's."""
    write(repo, "def go(runner):\n    return runner.run(['git'])\n")
    assert csd.check(repo) == []


def test_a_bare_run_import_is_ignored(repo):
    """`from subprocess import run` is not the attribute form this checker matches."""
    write(repo, "from subprocess import run\n\n\ndef go():\n    run(['git'])\n")
    assert csd.check(repo) == []


def test_a_plain_function_call_is_ignored(repo):
    write(repo, "def go():\n    return len([1])\n")
    assert csd.check(repo) == []


# --- the real tree, and the CLI ----------------------------------------------


def test_the_bundled_scripts_are_disciplined(repo_root):
    """The gate applied to this repo — the assertion that keeps the ten sites honest."""
    assert csd.check(repo_root) == []


def test_main_returns_zero_on_the_real_repo(repo_root):
    assert csd.main(["--root", str(repo_root)]) == 0


def test_main_reports_each_violation_and_returns_one(repo, capsys):
    write(repo, "import subprocess\n\n\ndef go():\n    subprocess.run(['git'])\n")
    assert csd.main(["--root", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "omits `check=`" in err
    assert "1 subprocess call(s) do not account for failure" in err


def test_main_defaults_to_the_current_directory(repo, monkeypatch):
    monkeypatch.chdir(repo)
    write(repo, "import subprocess\n\n\ndef go():\n    subprocess.run(['git'], check=True)\n")
    assert csd.main([]) == 0


def test_a_path_outside_the_root_is_reported_absolutely(repo, tmp_path):
    """`relative_to` would raise; the checker falls back to the full path."""
    outside = tmp_path.parent / "outside.py"
    outside.write_text(
        "import subprocess\n\n\ndef go():\n    subprocess.run(['git'])\n", encoding="utf-8"
    )
    (violation,) = csd.check_module(outside, repo)
    assert str(outside) in violation
