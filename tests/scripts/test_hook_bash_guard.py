"""Tests for `scripts/hook_bash_guard.py`.

Two properties matter more than the individual cases, and both are asserted directly:

- **It fails open.** Every malformed payload, missing binary and unreadable repo must
  produce *no* decision. A guard that blocks when confused cannot be argued with.
- **It does not over-block.** The bare `make` calls `/quality` is built on, and ordinary
  pushes to a work branch, must sail through untouched.
"""

from __future__ import annotations

import json
import subprocess

import hook_bash_guard as guard
import pytest


class TestDecision:
    """The decision record handed back to Claude Code."""

    def test_fields(self):
        decision = guard.Decision("deny", "because")
        assert decision.permission == "deny"
        assert decision.reason == "because"

    def test_guard_never_grants_permission(self):
        """`allow` would widen the session's surface; this hook only ever restricts."""
        commands = ["make test | tail", "git push --force", "git push origin main"]
        decisions = [guard.evaluate(command, ".") for command in commands]
        assert all(d is not None and d.permission in ("deny", "ask") for d in decisions)


# --------------------------------------------------------------------------- quoting


def test_strip_quoted_blanks_both_quote_styles():
    assert "make" not in guard.strip_quoted("git commit -m 'make it | better'")
    assert "make" not in guard.strip_quoted('git commit -m "make it | better"')


def test_strip_quoted_keeps_tokens_apart():
    assert guard.strip_quoted("a'x'b").split() == ["a b"] or guard.strip_quoted("a'x'b") == "a b"


# -------------------------------------------------------------------------- heredocs


@pytest.mark.parametrize(
    "command",
    [
        "git commit -F - <<EOF\nfixed at v1.2.1; make deptry is deprecated\nEOF",
        "git commit -F - <<'EOF'\nrun it (make test) first\nEOF",
        "git commit -F - <<-EOF\n\tsee; make lint\n\tEOF",
        "cat <<MSG\nmake test | tail -5\nMSG",
    ],
)
def test_strip_heredocs_blanks_the_body(command):
    stripped = guard.strip_heredocs(command)
    assert "make" not in stripped
    assert "<<" in stripped


def test_strip_heredocs_leaves_a_command_without_one_alone():
    assert guard.strip_heredocs("make test | tail") == "make test | tail"


def test_strip_data_blanks_a_quoted_delimiters_body():
    """`strip_quoted` alone would blank `'EOF'` and leave the prose it delimits."""
    command = "git commit -F - <<'EOF'\nnow; make deps replaces make deptry\nEOF"
    assert "make" in guard.strip_quoted(command)
    assert "make" not in guard.strip_data(command)


# ------------------------------------------------------------------------ make guard


@pytest.mark.parametrize(
    "command",
    [
        "make test",
        "make -C sub test",
        "make fmt ARGS=-x",
        "  make   book  ",
    ],
)
def test_bare_make_is_allowed(command):
    assert guard.compound_make(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "make test | tail -50",
        "make fmt && make typecheck",
        "make test 2>&1",
        "make book > out.txt",
        "cd sub && make test",
        "make test; echo done",
        "(cd sub && make test)",
        "make test &",
        "sudo make install | grep ok",
        "make test < input",
        "make lint || true",
    ],
)
def test_compound_make_is_denied(command):
    decision = guard.compound_make(command)
    assert decision is not None
    assert decision.permission == "deny"
    assert "bare" in decision.reason


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'make it better' && git push origin feature",
        "echo 'make | tail' > note.txt",
        "grep make Makefile | head",
        "./makefile-lint | tee log",
    ],
)
def test_make_inside_quotes_or_words_is_not_a_make_call(command):
    assert guard.compound_make(command) is None


@pytest.mark.parametrize(
    "command",
    [
        # The reproducer from #169: prose in a commit message, not a chained `make`.
        "git commit -F - <<EOF\nfixed at v1.2.1; make deptry is deprecated\nEOF",
        "git commit -F - <<EOF\nrun it (make test) first\nEOF",
        "git commit -F - <<'EOF'\nfixed at v1.2.1; make deptry is deprecated\nEOF",
        "git commit -F - <<-EOF\n\tfixed; make deptry is deprecated\n\tEOF",
        # A body line that *begins* with `make` — the false positive `re.MULTILINE`
        # would introduce were heredocs not blanked first.
        "cat <<EOF > note.txt\nmake test is the gate\nEOF",
    ],
)
def test_make_inside_a_heredoc_is_not_a_make_call(command):
    assert guard.compound_make(command) is None


@pytest.mark.parametrize(
    "command",
    [
        # `make` on a later line: `^` only sees it with `re.MULTILINE`.
        "echo hi\nmake test | tail",
        "git commit -F - <<EOF\nnotes about make\nEOF\nmake test | tail",
    ],
)
def test_compound_make_on_a_later_line_is_denied(command):
    decision = guard.compound_make(command)
    assert decision is not None
    assert decision.permission == "deny"


def test_bare_make_on_a_later_line_is_still_allowed():
    assert guard.compound_make("echo hi\nmake test") is None


# ---------------------------------------------------------------------- tokenisation


def test_segments_splits_on_operators_and_drops_blanks():
    assert guard.segments("a b && c | d ; ; e") == [["a", "b"], ["c"], ["d"], ["e"]]


def test_segments_of_blank_command():
    assert guard.segments("   ") == []


def test_segments_splits_on_newlines():
    assert guard.segments("echo hi\ngit push origin main") == [
        ["echo", "hi"],
        ["git", "push", "origin", "main"],
    ]


def test_segments_does_not_see_inside_a_heredoc():
    command = "git commit -F - <<EOF\ngit push --force is banned here\nEOF"
    assert guard.segments(command) == [["git", "commit", "-F", "-", "<<"]]


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["git", "push"], ("push", [])),
        (["sudo", "git", "push", "origin"], ("push", ["origin"])),
        (["git", "-C", "/repo", "push", "origin"], ("push", ["origin"])),
        (["git", "--no-pager", "log"], ("log", [])),
        (["git", "-c", "a=b", "-C", "/repo", "tag", "-f", "v1"], ("tag", ["-f", "v1"])),
    ],
)
def test_git_subcommand_parses(tokens, expected):
    assert guard.git_subcommand(tokens) == expected


@pytest.mark.parametrize(
    "tokens",
    [
        ["ls", "-la"],
        ["gitk"],
        ["git"],
        ["git", "-C", "/repo"],
        ["sudo"],
    ],
)
def test_git_subcommand_returns_none(tokens):
    assert guard.git_subcommand(tokens) is None


def test_push_positionals_skips_flags_and_their_values():
    args = ["-u", "--push-option", "ci.skip", "origin", "feature", "--quiet"]
    assert guard.push_positionals(args) == ["origin", "feature"]


# --------------------------------------------------------------------------- git i/o


def _fake_run(stdout="", returncode=0):
    def run(cmd, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return run


def test_git_returns_none_without_a_git_binary(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _: None)
    assert guard._git(".", "status") is None


def test_git_returns_none_on_oserror(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _: "/usr/bin/git")

    def boom(*args, **kwargs):
        raise OSError("no exec")

    monkeypatch.setattr(guard.subprocess, "run", boom)
    assert guard._git(".", "status") is None


def test_git_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _: "/usr/bin/git")

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 5)

    monkeypatch.setattr(guard.subprocess, "run", slow)
    assert guard._git(".", "status") is None


def test_git_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(guard.subprocess, "run", _fake_run("x", returncode=128))
    assert guard._git(".", "status") is None


def test_git_returns_none_on_empty_output(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(guard.subprocess, "run", _fake_run("   \n"))
    assert guard._git(".", "status") is None


def test_git_returns_stripped_stdout(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(guard.subprocess, "run", _fake_run(" main \n"))
    assert guard._git(".", "status") == "main"


@pytest.mark.parametrize(
    ("head", "expected"),
    [("origin/main", "main"), ("origin/trunk", "trunk"), ("main", "main"), (None, None)],
)
def test_default_branch(monkeypatch, head, expected):
    monkeypatch.setattr(guard, "_git", lambda *a: head)
    assert guard.default_branch(".") == expected


@pytest.mark.parametrize(
    ("output", "expected"),
    [("feature", "feature"), ("HEAD", None), (None, None)],
)
def test_current_branch(monkeypatch, output, expected):
    monkeypatch.setattr(guard, "_git", lambda *a: output)
    assert guard.current_branch(".") == expected


# ------------------------------------------------------------------------- targeting


@pytest.mark.parametrize(
    ("args", "branch", "expected"),
    [
        ([], "feature", ["feature"]),
        (["origin"], "feature", ["feature"]),
        ([], None, []),
        (["origin", "main"], "feature", ["main"]),
        (["origin", "HEAD:main"], "feature", ["main"]),
        (["origin", "+feature:main"], "feature", ["main"]),
        (["origin", "refs/heads/main"], "feature", ["main"]),
        (["origin", "HEAD"], "feature", ["feature"]),
        (["origin", "HEAD"], None, []),
        (["origin", "main:"], "feature", ["feature"]),
        (["origin", ":main"], "feature", ["main"]),
        (["origin", "a", "b"], "feature", ["a", "b"]),
    ],
)
def test_push_targets(monkeypatch, args, branch, expected):
    monkeypatch.setattr(guard, "current_branch", lambda _: branch)
    assert guard.push_targets(args, ".") == expected


@pytest.mark.parametrize(
    ("target", "default", "expected"),
    [
        ("main", "main", True),
        ("feature", "main", False),
        ("trunk", "trunk", True),
        ("main", None, True),
        ("master", None, True),
        ("feature", None, False),
    ],
)
def test_is_default(target, default, expected):
    assert guard.is_default(target, default) is expected


# ------------------------------------------------------------------------- git guard


@pytest.fixture
def on_feature(monkeypatch):
    """A repo whose default branch is `main` and whose checkout is `feature`."""
    monkeypatch.setattr(guard, "default_branch", lambda _: "main")
    monkeypatch.setattr(guard, "current_branch", lambda _: "feature")


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push -f",
        "git tag -f v1.0.0",
        "git tag --force v1.0.0",
    ],
)
def test_force_is_denied(on_feature, command):
    decision = guard.git_guard(command, ".")
    assert decision is not None
    assert decision.permission == "deny"
    assert "irreversible" in decision.reason


def test_force_with_lease_is_not_treated_as_force(on_feature):
    assert guard.git_guard("git push --force-with-lease origin feature", ".") is None


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push",
        "git push origin HEAD:main",
        "git -C /repo push origin main",
        "echo building && git push origin main",
    ],
)
def test_push_to_default_asks(monkeypatch, command):
    monkeypatch.setattr(guard, "default_branch", lambda _: "main")
    monkeypatch.setattr(guard, "current_branch", lambda _: "main")
    decision = guard.git_guard(command, ".")
    assert decision is not None
    assert decision.permission == "ask"
    assert "default branch" in decision.reason


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin feature",
        "git push origin feature",
        "git status",
        "git log --oneline",
        "ls -la",
        "git push origin HEAD",
    ],
)
def test_ordinary_git_is_untouched(on_feature, command):
    assert guard.git_guard(command, ".") is None


def test_guard_skips_non_git_segments(on_feature):
    assert guard.git_guard("ls && echo hi && cat file", ".") is None


def test_a_force_push_described_in_a_heredoc_is_not_a_force_push(on_feature):
    command = "git commit -F - <<EOF\nreverted the git push --force from yesterday\nEOF"
    assert guard.git_guard(command, ".") is None


def test_push_on_a_later_line_is_still_seen(monkeypatch):
    monkeypatch.setattr(guard, "default_branch", lambda _: "main")
    monkeypatch.setattr(guard, "current_branch", lambda _: "main")
    decision = guard.git_guard("git add -A\ngit push origin main", ".")
    assert decision is not None
    assert decision.permission == "ask"


# ------------------------------------------------------------------------------ main


def _run(monkeypatch, capsys, payload, raw=None):
    monkeypatch.setattr(guard.sys, "stdin", _Stdin(raw if raw is not None else json.dumps(payload)))
    code = guard.main()
    return code, capsys.readouterr().out


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


@pytest.mark.parametrize(
    ("payload", "raw"),
    [
        (None, "not json at all"),
        (None, "[1, 2, 3]"),
        ({"tool_name": "Read", "tool_input": {"command": "make x | tail"}}, None),
        ({"tool_name": "Bash"}, None),
        ({"tool_name": "Bash", "tool_input": "nope"}, None),
        ({"tool_name": "Bash", "tool_input": {"command": 42}}, None),
        ({"tool_name": "Bash", "tool_input": {"command": "   "}}, None),
        ({"tool_name": "Bash", "tool_input": {"command": "make test"}}, None),
    ],
)
def test_main_stays_silent(monkeypatch, capsys, payload, raw):
    code, out = _run(monkeypatch, capsys, payload, raw)
    assert code == 0
    assert out == ""


def test_main_emits_a_deny_decision(monkeypatch, capsys):
    payload = {
        "tool_name": "Bash",
        "cwd": "/repo",
        "tool_input": {"command": "make test | tail -50"},
    }
    code, out = _run(monkeypatch, capsys, payload)
    assert code == 0
    emitted = json.loads(out)["hookSpecificOutput"]
    assert emitted["hookEventName"] == "PreToolUse"
    assert emitted["permissionDecision"] == "deny"
    assert "bare" in emitted["permissionDecisionReason"]


def test_main_defaults_cwd_when_absent(monkeypatch, capsys):
    seen = {}

    def record(command, cwd):
        seen["cwd"] = cwd
        return None

    monkeypatch.setattr(guard, "evaluate", record)
    _run(monkeypatch, capsys, {"tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert seen["cwd"] == "."


def test_main_passes_cwd_through(monkeypatch, capsys):
    seen = {}

    def record(command, cwd):
        seen["cwd"] = cwd
        return None

    monkeypatch.setattr(guard, "evaluate", record)
    _run(
        monkeypatch,
        capsys,
        {"tool_name": "Bash", "cwd": "/repo", "tool_input": {"command": "git status"}},
    )
    assert seen["cwd"] == "/repo"


def test_evaluate_prefers_the_make_guard(on_feature):
    decision = guard.evaluate("make test | git push origin main", ".")
    assert decision is not None
    assert decision.permission == "deny"
