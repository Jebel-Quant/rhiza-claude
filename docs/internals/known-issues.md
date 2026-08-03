# known-issues

An **internal procedure**, not a slash command. It lives in `prompts/` so it cannot be
invoked directly; `/rhiza:quality` reaches it with `Read`.

## What it is for

`/rhiza:quality` reads it **only when a gate fails**, before diagnosing. It lists the
failures that are upstream and unsatisfiable in the repo being scored, so a known
non-issue is marked out-of-scope rather than FAIL — and, in one case, so the obvious
"fix" is not applied, because it would trade a failing gate for an unbuildable package.

## Why it is a separate file

These notes used to sit inline in `plugin/commands/quality.md`, as two long block quotes on the
path between "run the gates" and "report the results". That was wrong twice over.

**They were loaded on every run.** Around eighteen lines describing failures most runs
never encounter, in the stretch where the command is deciding what to do about a result.
Reading them only on the failure branch shortens the operational path.

**They were the only prose in the repo that could silently go stale.** Both entries were
scoped to template versions (`through v1.2.1`, `up to rhiza v1.1.3`) that the pinned ref
had already moved past, and nothing checked them. In a repo whose position is that prose
is gated exactly like code, that was the one uncovered surface.

The file now states how to read its own version column: compare each entry against the
ref recorded in `.rhiza/template.lock`, and treat an entry entirely behind that ref as a
candidate for deletion rather than a reason to excuse a gate.

## Current entries

| Entry | Gate | Affects |
| --- | --- | --- |
| `test_license_classifier_present` — PEP 639 | `make rhiza-test` | rhiza through v1.2.1 |
| `make validate` — removed from the template | `make validate` | rhiza up to v1.1.3 |

The first cross-references `jebel-quant/rhiza-hooks`' **`check-license-metadata`** hook,
which rejects the broken combination at commit time. A repo not running that hook has a
real, in-scope finding — adopt the hook — rather than a manifest to edit.

## Related

- [quality](../commands/quality.md) — the only command that reads this.
- [scorecard](scorecard.md) — owns the scoping rule that turns "out-of-scope" into marks.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/prompts/known-issues.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:quality`](../commands/quality.md) |

<!-- generated:end -->
