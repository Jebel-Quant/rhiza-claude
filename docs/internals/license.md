# license (internal)

Apply a project's **license** — sets the SPDX `license` / `license-files` metadata in
`pyproject.toml` and writes the `LICENSE` file's full text.

!!! note "Not a slash command"
    This is an **internal procedure** (`prompts/license.md`), not something you
    invoke. [`/rhiza:init`](../commands/init.md) reads and follows it at its step 5c,
    right after the [skeleton](skeleton.md).

You're asked for the id. Bundled full texts: **MIT**, **Apache-2.0**,
**BSD-3-Clause**. `none` clears the metadata and leaves any existing `LICENSE` in
place. Overwriting an existing `LICENSE` is opt-in — without `--force` the script
refuses and **exits 3**, changing nothing at all, metadata included.

## What it does

Runs the bundled `scripts/set_license.py` — stdlib-only — which:

- **replaces** (not just adds) the SPDX `license` / `license-files` fields in the
  `[project]` table — the PEP 639 expression field, never a deprecated
  `License :: OSI Approved :: …` trove classifier;
- writes the `LICENSE` file from the bundled template, filling the copyright year
  and holder;
- for `none`, clears the metadata and leaves any existing `LICENSE` untouched.

The command settles three inputs first: the **license id** (argument or a prompt),
the **copyright holder** (derived from the `origin` remote's owner or
`git config user.name`, else asked), and — only when an existing `LICENSE` would
change — an **overwrite confirmation**.

## Notes

- Works without the `rhiza` CLI installed.
- **Safe by default:** without `--force` the script refuses to overwrite a
  differing `LICENSE` and exits 3, changing nothing (metadata included) — so the
  file and the metadata never diverge.
- A non-bundled SPDX id still sets the metadata; the script tells you to add the
  `LICENSE` text by hand.

<!-- generated:begin — rendered by scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `prompts/license.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:init`](../commands/init.md), [`known-issues`](known-issues.md), [`skeleton`](skeleton.md) |

<!-- generated:end -->
