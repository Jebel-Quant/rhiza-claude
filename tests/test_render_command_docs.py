"""Tests for `scripts/render_command_docs.py`.

The property that matters most: the generator is **additive**. It appends a reference
block and must never touch a hand-written line, because the docs pages are independent
prose — `docs/commands/maffay.md` is longer than the command it documents. Several
tests below assert exactly that.
"""

from __future__ import annotations

import _rhiza_layout as layout
import render_command_docs as rcd

COMMAND = """---
description: Do a thing.
argument-hint: "[a path]  (optional)"
allowed-tools: Bash(git*), Read
---

Body that is instructions to a model, not documentation.
"""

DESTRUCTIVE = """---
description: Remove things.
argument-hint: "[a path]"
allowed-tools: Bash(uv*)
disable-model-invocation: true
---

Body.
"""

PAGE = """# `/rhiza:thing`

A hand-written explanation that the generator must not touch.

## Notes

- something a person wrote
"""


def _repo(tmp_path, commands=None, prompts=None, pages=None, internals=None):
    """Build a miniature repo with the directory shape the renderer expects."""
    for name, text in (commands or {}).items():
        (tmp_path / layout.COMMANDS_DIR).mkdir(parents=True, exist_ok=True)
        (tmp_path / layout.COMMANDS_DIR / f"{name}.md").write_text(text)
    for name, text in (prompts or {}).items():
        (tmp_path / layout.PROMPTS_DIR).mkdir(parents=True, exist_ok=True)
        (tmp_path / layout.PROMPTS_DIR / f"{name}.md").write_text(text)
    for name, text in (pages or {}).items():
        (tmp_path / "docs" / "commands").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "commands" / f"{name}.md").write_text(text)
    for name, text in (internals or {}).items():
        (tmp_path / "docs" / "internals").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "internals" / f"{name}.md").write_text(text)
    for directory in (layout.COMMANDS_DIR, layout.PROMPTS_DIR):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ----------------------------------------------------------------- frontmatter


def test_frontmatter_parses_fields():
    assert rcd.frontmatter(COMMAND)["allowed-tools"] == "Bash(git*), Read"


def test_frontmatter_of_a_file_without_any():
    assert rcd.frontmatter("# Just a heading\n") == {}


def test_unquote_strips_matching_quotes():
    assert rcd._unquote('"[a path]"') == "[a path]"
    assert rcd._unquote("'[a path]'") == "[a path]"


def test_unquote_leaves_bare_and_short_values():
    assert rcd._unquote("[a path]") == "[a path]"
    assert rcd._unquote('"') == '"'


def test_tools_renders_each_as_code():
    assert rcd._tools("Bash(git*), Read") == "`Bash(git*)`, `Read`"


def test_tools_with_nothing_declared():
    assert rcd._tools("  ") == "_none declared_"


# --------------------------------------------------------------------- blocks


def test_command_block_carries_the_facts_that_drift():
    block = rcd.command_block("thing", rcd.frontmatter(COMMAND))
    assert f"`{layout.COMMANDS_DIR}/thing.md`" in block
    assert "`/rhiza:thing [a path]  (optional)`" in block
    assert "| **Model-invocable** | yes |" in block
    assert "`Bash(git*)`, `Read`" in block


def test_command_block_reports_a_model_invocation_opt_out():
    block = rcd.command_block("uninstall", rcd.frontmatter(DESTRUCTIVE))
    assert "no — excluded from model invocation" in block


def test_command_block_without_an_argument_hint():
    block = rcd.command_block("thing", {"allowed-tools": "Read"})
    assert "`/rhiza:thing`" in block


def test_procedure_block_links_commands_and_procedures():
    block = rcd.procedure_block("skeleton", ["commands/init", "prompts/scorecard"])
    assert "[`/rhiza:init`](../commands/init.md)" in block
    assert "[`scorecard`](scorecard.md)" in block
    assert "not a slash command" in block


def test_procedure_block_with_no_readers():
    assert "orphan" in rcd.procedure_block("lonely", [])


# -------------------------------------------------------------------- readers


def test_readers_of_finds_commands_and_procedures(tmp_path):
    root = _repo(
        tmp_path,
        commands={"init": "Read prompts/skeleton.md now", "other": "nothing here"},
        prompts={"skeleton": "self reference prompts/skeleton.md", "scorecard": "no ref"},
    )
    assert rcd.readers_of("skeleton", root) == ["commands/init"]


def test_readers_of_ignores_a_procedures_own_self_reference(tmp_path):
    root = _repo(tmp_path, prompts={"skeleton": "see prompts/skeleton.md"})
    assert rcd.readers_of("skeleton", root) == []


# --------------------------------------------------------------------- splice


def test_splice_appends_when_the_page_has_no_block():
    out = rcd.splice(PAGE, "BLOCK")
    assert out.startswith("# `/rhiza:thing`")
    assert "something a person wrote" in out
    assert out.rstrip().endswith("BLOCK")


def test_splice_replaces_an_existing_block_without_touching_prose():
    first = rcd.splice(PAGE, rcd._table([("Source", "old")]))
    second = rcd.splice(first, rcd._table([("Source", "new")]))
    assert "old" not in second
    assert "new" in second
    assert second.count(rcd._BEGIN) == 1
    assert "something a person wrote" in second


def test_splice_is_idempotent():
    block = rcd._table([("Source", "x")])
    once = rcd.splice(PAGE, block)
    assert rcd.splice(once, block) == once


# --------------------------------------------------------------------- render


def test_render_covers_commands_and_procedures(tmp_path):
    root = _repo(
        tmp_path,
        commands={"thing": COMMAND},
        prompts={"proc": "a procedure"},
        pages={"thing": PAGE},
        internals={"proc": "# proc\n\nprose\n"},
    )
    wanted = rcd.render(root)
    assert {p.name for p in wanted} == {"thing.md", "proc.md"}


def test_render_skips_a_command_with_no_page(tmp_path):
    root = _repo(tmp_path, commands={"thing": COMMAND})
    assert rcd.render(root) == {}


# ----------------------------------------------------------------------- main


def test_main_writes_and_then_reports_up_to_date(tmp_path, capsys):
    root = _repo(tmp_path, commands={"thing": COMMAND}, pages={"thing": PAGE})
    assert rcd.main(["--root", str(root)]) == 0
    assert "updated" in capsys.readouterr().out
    assert rcd.main(["--root", str(root)]) == 0
    assert "up to date" in capsys.readouterr().out


def test_main_check_fails_on_a_stale_page(tmp_path, capsys):
    root = _repo(tmp_path, commands={"thing": COMMAND}, pages={"thing": PAGE})
    assert rcd.main(["--root", str(root), "--check"]) == 1
    captured = capsys.readouterr()
    assert "Stale generated block" in captured.err
    assert "thing.md" in captured.err


def test_main_check_writes_nothing(tmp_path):
    root = _repo(tmp_path, commands={"thing": COMMAND}, pages={"thing": PAGE})
    page = root / "docs" / "commands" / "thing.md"
    rcd.main(["--root", str(root), "--check"])
    assert page.read_text() == PAGE


def test_main_check_passes_once_rendered(tmp_path, capsys):
    root = _repo(tmp_path, commands={"thing": COMMAND}, pages={"thing": PAGE})
    rcd.main(["--root", str(root)])
    capsys.readouterr()
    assert rcd.main(["--root", str(root), "--check"]) == 0


def test_main_preserves_every_hand_written_line(tmp_path):
    """The whole point: generation is additive."""
    root = _repo(tmp_path, commands={"thing": COMMAND}, pages={"thing": PAGE})
    rcd.main(["--root", str(root)])
    after = (root / "docs" / "commands" / "thing.md").read_text()
    for line in PAGE.splitlines():
        assert line in after
