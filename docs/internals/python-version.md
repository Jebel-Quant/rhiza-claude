# python-version (internal)

Set a rhiza-managed Python project's standard interpreter version.

!!! note "Not a slash command"
    This is an **internal procedure** (`prompts/python-version.md`), not something
    you invoke. The [skeleton](skeleton.md) procedure reads and follows it at its
    step 6, which is itself reached from [`/rhiza:init`](../commands/init.md).

**Supported: 3.11, 3.12, 3.13, 3.14.** Python 3.9 and 3.10 are **not** supported —
the script rejects them.

`requires-python` is the upstream fact: `.python-version` is pinned from it, and
`ruff` derives its `target-version` from it. Set that one field and the rest follows.

!!! warning "Known upstream issue: ruff's `target-version`"
    Ruff normally infers `target-version` from `requires-python`, but rhiza's synced
    `ruff.toml` hardcodes `target-version = "py311"`, which overrides that inference.
    A repo retargeted to 3.13 therefore ends up with `requires-python = ">=3.13"`
    while ruff still lints as py311, so pyupgrade never suggests 3.12+ idioms.

    The procedure **detects and reports** this mismatch but deliberately does not fix
    it: `ruff.toml` is template-owned, so a local edit is reverted by the next
    [`/rhiza:update`](../commands/update.md) sync. The fix is to drop the line
    upstream in `jebel-quant/rhiza` and let ruff infer.

## What it does

Runs the bundled `scripts/set_python_version.py` — stdlib-only — which edits the
`pyproject.toml` `[project]` table:

- pins `requires-python = ">=X.Y"` (corrected in place);
- rewrites the `Programming Language :: Python :: X.Y` trove classifiers to the
  supported range from the chosen version upward, **dropping** any stale or
  unsupported Python classifiers (including a bare `Programming Language ::
  Python :: 3`) while **preserving** non-Python classifiers.

It then re-pins `.python-version` with **`uv python pin --no-python-downloads`** —
the tool that owns that file — rather than writing it by hand. The flag matters:
without it `uv` downloads the interpreter (~25 MiB) if it isn't installed, which a
metadata step has no business doing; with it, `uv` refuses a pin that contradicts the
`requires-python` just written, giving a free consistency check.

## Notes

- Works without the `rhiza` CLI installed.
- **Idempotent** — re-running with the same version changes nothing.
- `uv python pin` warns but still succeeds on a nonsense version, so it isn't the
  validation layer — the bundled script is, and it rejects anything outside 3.11–3.14.
- Out of scope: CI version matrices and other version references elsewhere in the
  repo. Check those separately when you drop or add a version.

<!-- generated:begin — rendered by scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `prompts/python-version.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:init`](../commands/init.md), [`skeleton`](skeleton.md) |

<!-- generated:end -->
