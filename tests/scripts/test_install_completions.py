"""Tests for the completion installer (`scripts/install_completions.py`).

Every test points the installer at a temporary data home, so nothing here can write into
the developer's real `~/.local/share`. That is the whole hazard this script carries: its
destinations are machine-wide paths for the `make` command in general, not repo files.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import install_completions as ic
import pytest

# A completion file this plugin did not write — no `_rhiza_make` anywhere in it.
_FOREIGN = "# hand-rolled\ncomplete -W 'build test' make\n"


@pytest.fixture
def env(tmp_path):
    """An environment whose XDG data home is a fresh temporary directory."""
    return {"XDG_DATA_HOME": str(tmp_path / "data")}


# --- the shell table ----------------------------------------------------------


class TestShell:
    """One shell's asset, destination and follow-up step."""

    def test_every_bundled_asset_is_shipped(self):
        """The table names files that exist — a missing one is a packaging fault."""
        for shell in ic.SHELLS:
            assert ic.asset(shell).is_file(), shell.asset

    def test_installs_under_the_generic_command_name(self):
        """`make` and `_make`, because both shells resolve completions by command name."""
        assert {shell.installed_as for shell in ic.SHELLS} == {"make", "_make"}

    def test_every_asset_carries_the_ownership_marker(self):
        """Without it, a re-run of the installer would report its own file as foreign."""
        for shell in ic.SHELLS:
            assert ic.is_ours(ic.asset(shell).read_text(encoding="utf-8"))

    def test_hint_formats_with_both_available_fields(self):
        """Each hint uses `{path}` or `{parent}`; neither may leave a stray placeholder."""
        for shell in ic.SHELLS:
            rendered = shell.hint.format(path="/p/make", parent="/p")
            assert "{" not in rendered


@pytest.mark.parametrize(("kind", "interpreter"), [("bash", "bash"), ("zsh", "zsh")])
def test_bundled_script_parses(kind, interpreter):
    """The only gate on the two shell assets: nothing else in the tree type-checks them.

    A syntax error here ships silently — the file is copied, not executed, so the
    installer succeeds and completion simply never works.
    """
    binary = shutil.which(interpreter)
    if binary is None:  # pragma: no cover - both are present wherever this matters
        pytest.skip(f"{interpreter} not installed")
    shell = ic.shells(kind)[0]
    result = subprocess.run([binary, "-n", str(ic.asset(shell))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shells_selects_one_kind():
    assert [shell.kind for shell in ic.shells("bash")] == ["bash"]


def test_shells_both_selects_every_supported_shell():
    assert [shell.kind for shell in ic.shells(ic.BOTH)] == [s.kind for s in ic.SHELLS]


# --- where things land --------------------------------------------------------


def test_data_home_prefers_xdg():
    assert ic.data_home({"XDG_DATA_HOME": "/opt/data"}).as_posix() == "/opt/data"


def test_data_home_treats_an_empty_xdg_as_unset():
    """`${XDG_DATA_HOME:-…}` falls back on empty, and so must this."""
    assert ic.data_home({"XDG_DATA_HOME": "", "HOME": "/home/ada"}).as_posix().startswith(
        "/home/ada"
    )


def test_data_home_falls_back_to_the_home_share_dir():
    home = ic.data_home({"HOME": "/home/ada"})
    assert home.as_posix() == "/home/ada/.local/share"


def test_data_home_with_no_environment_expands_the_user():
    """An environment with neither variable still resolves, rather than yielding `~`."""
    assert "~" not in ic.data_home({}).as_posix()


def test_data_home_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/opt/from-environ")
    assert ic.data_home().as_posix() == "/opt/from-environ"


def test_destination_is_the_documented_xdg_path(env):
    paths = {shell.kind: ic.destination(shell, env).as_posix() for shell in ic.SHELLS}
    assert paths["bash"].endswith("/bash-completion/completions/make")
    assert paths["zsh"].endswith("/zsh/site-functions/_make")


# --- classification -----------------------------------------------------------


def test_classify_install_when_nothing_is_there(tmp_path):
    assert ic.classify(tmp_path / "make", "body", force=False) == "install"


def test_classify_unchanged_on_an_identical_file(tmp_path):
    dest = tmp_path / "make"
    dest.write_text("body", encoding="utf-8")
    assert ic.classify(dest, "body", force=False) == "unchanged"


def test_classify_update_on_an_older_copy_of_ours(tmp_path):
    dest = tmp_path / "make"
    dest.write_text("_rhiza_make_completion() { :; } # v1\n", encoding="utf-8")
    assert ic.classify(dest, "new body", force=False) == "update"


def test_classify_blocks_a_foreign_file(tmp_path):
    dest = tmp_path / "make"
    dest.write_text(_FOREIGN, encoding="utf-8")
    assert ic.classify(dest, "body", force=False) == "blocked"


def test_classify_replaces_a_foreign_file_when_forced(tmp_path):
    dest = tmp_path / "make"
    dest.write_text(_FOREIGN, encoding="utf-8")
    assert ic.classify(dest, "body", force=True) == "replace"


def test_classify_blocks_a_destination_that_is_a_directory(tmp_path):
    """Not ours to remove, whatever `--force` says — and a traceback would be worse."""
    dest = tmp_path / "make"
    dest.mkdir()
    assert ic.classify(dest, "body", force=True) == "blocked"


def test_classify_blocks_undecodable_bytes_rather_than_raising(tmp_path):
    """A destination that isn't UTF-8 is certainly not ours; it takes the normal route."""
    dest = tmp_path / "make"
    dest.write_bytes(b"\xff\xfe not text")
    assert ic.classify(dest, "body", force=False) == "blocked"


# --- installing ---------------------------------------------------------------


def test_install_writes_both_completions(env):
    summary = ic.install(ic.BOTH, env=env)
    assert [entry["action"] for entry in summary["shells"]] == ["install", "install"]
    for entry, shell in zip(summary["shells"], ic.SHELLS, strict=True):
        dest = ic.destination(shell, env)
        assert dest.read_text(encoding="utf-8") == ic.asset(shell).read_text(encoding="utf-8")
        assert entry["written"] is True
    assert summary["needs_force"] is False


def test_install_creates_the_destination_directory(env):
    ic.install("zsh", env=env)
    assert ic.destination(ic.shells("zsh")[0], env).parent.is_dir()


def test_install_is_idempotent(env):
    ic.install("bash", env=env)
    summary = ic.install("bash", env=env)
    assert summary["shells"][0]["action"] == "unchanged"
    assert summary["shells"][0]["written"] is False


def test_install_updates_its_own_earlier_copy(env):
    shell = ic.shells("bash")[0]
    dest = ic.destination(shell, env)
    dest.parent.mkdir(parents=True)
    dest.write_text("_rhiza_make_completion() { :; } # stale\n", encoding="utf-8")
    summary = ic.install("bash", env=env)
    assert summary["shells"][0]["action"] == "update"
    assert dest.read_text(encoding="utf-8") == ic.asset(shell).read_text(encoding="utf-8")


def test_install_leaves_a_foreign_completion_alone(env):
    """The one destructive move available to this script, and it declines to make it."""
    dest = ic.destination(ic.shells("bash")[0], env)
    dest.parent.mkdir(parents=True)
    dest.write_text(_FOREIGN, encoding="utf-8")
    summary = ic.install("bash", env=env)
    assert summary["needs_force"] is True
    assert dest.read_text(encoding="utf-8") == _FOREIGN


def test_install_replaces_a_foreign_completion_when_forced(env):
    shell = ic.shells("bash")[0]
    dest = ic.destination(shell, env)
    dest.parent.mkdir(parents=True)
    dest.write_text(_FOREIGN, encoding="utf-8")
    summary = ic.install("bash", env=env, force=True)
    assert summary["shells"][0]["action"] == "replace"
    assert dest.read_text(encoding="utf-8") == ic.asset(shell).read_text(encoding="utf-8")


def test_dry_run_writes_nothing(env):
    summary = ic.install(ic.BOTH, env=env, dry_run=True)
    assert [entry["action"] for entry in summary["shells"]] == ["install", "install"]
    assert not any(entry["written"] for entry in summary["shells"])
    assert not any(ic.destination(shell, env).exists() for shell in ic.SHELLS)


# --- reporting ----------------------------------------------------------------


def test_report_names_the_path_and_the_follow_up(env, capsys):
    ic.report(ic.install("zsh", env=env))
    out = capsys.readouterr().out
    assert "installed" in out
    assert "site-functions/_make" in out.replace("\\", "/")
    assert "compinit" in out


def test_report_of_a_dry_run_is_conditional_and_omits_the_follow_up(env, capsys):
    ic.report(ic.install("bash", env=env, dry_run=True))
    captured = capsys.readouterr()
    assert "would install" in captured.out
    assert "next:" not in captured.out


def test_report_of_an_unchanged_install_does_not_claim_a_write(env, capsys):
    ic.install("bash", env=env)
    capsys.readouterr()
    ic.report(ic.install("bash", env=env))
    assert "already up to date" in capsys.readouterr().out


def test_report_sends_a_blocked_destination_to_stderr(env, capsys):
    dest = ic.destination(ic.shells("bash")[0], env)
    dest.parent.mkdir(parents=True)
    dest.write_text(_FOREIGN, encoding="utf-8")
    ic.report(ic.install("bash", env=env))
    captured = capsys.readouterr()
    assert "--force" in captured.err
    assert captured.out == ""


# --- the CLI ------------------------------------------------------------------


def test_main_installs_both_by_default(monkeypatch, tmp_path, capsys):
    """`both`, because nothing here can detect the login shell."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert ic.main([]) == 0
    out = capsys.readouterr().out
    assert "bash:" in out and "zsh:" in out


def test_main_shell_narrows_the_install(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert ic.main(["--shell", "zsh"]) == 0
    out = capsys.readouterr().out
    assert "zsh:" in out and "bash:" not in out


def test_main_json_is_parseable(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert ic.main(["--shell", "bash", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["shells"][0]["shell"] == "bash"
    assert summary["needs_force"] is False


def test_main_returns_needs_force_on_a_foreign_completion(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    dest = ic.destination(ic.shells("bash")[0], {"XDG_DATA_HOME": str(tmp_path / "data")})
    dest.parent.mkdir(parents=True)
    dest.write_text(_FOREIGN, encoding="utf-8")
    assert ic.main(["--shell", "bash"]) == ic.NEEDS_FORCE
    assert "--force" in capsys.readouterr().err


def test_main_dry_run_reports_without_writing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert ic.main(["--dry-run"]) == 0
    assert "would install" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()


def test_main_rejects_an_unknown_shell(capsys):
    with pytest.raises(SystemExit):
        ic.main(["--shell", "fish"])
    assert "invalid choice" in capsys.readouterr().err


def test_main_errors_when_an_asset_is_not_bundled(monkeypatch, tmp_path, capsys):
    """A packaging fault gets a message, not a traceback out of `read_text`."""
    monkeypatch.setattr(ic, "_ASSETS", tmp_path / "no-completions")
    with pytest.raises(SystemExit) as excinfo:
        ic.main(["--shell", "bash"])
    assert excinfo.value.code == 2
    assert "missing" in capsys.readouterr().err
