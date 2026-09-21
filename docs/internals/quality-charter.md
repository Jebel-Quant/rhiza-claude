# quality-charter (internal)

How `/rhiza:quality` honours a repo's own `.rhiza/quality.md` — and the bounds it
honours it within.

!!! note "Not a slash command"
    This is an **internal procedure** (`plugin/prompts/quality-charter.md`), not
    something you invoke. [`/rhiza:quality`](../skills/quality.md) reads it in step 0,
    before the first gate, when the repo under assessment carries a charter.

## What a charter is

`.rhiza/quality.md` is a file **you** write, by hand, in freeform markdown. There is no
schema and no parser, because what makes a charter useful is its reasons, and a reason
is not a field. It is read the way a repo's `CLAUDE.md` is read: as a standing
instruction from the people who own the code, about that code.

Four things belong in one:

- **Extra gates** — a command your repo already has that the default list never names:
  `make bench`, a mutation run, an integration suite.
- **Scope** — paths that are generated, vendored, or scheduled for deletion, and paths
  that matter more than the rest.
- **Accepted deviations** — a gap you have already weighed and chosen, *with the
  argument*. The reason is what turns a gap into an exemption.
- **Emphasis** — the subcategories you want scored every time, and what you consider
  noise and would rather not have filed.

## The line it draws

**A charter governs judgement, never the instruments.** It moves what gets scored,
weighted, excused and filed. It does not move what a tool measures — the thresholds stay
in your committed config, because that is what CI enforces and therefore what the repo
actually means.

The consequence is a deliberate asymmetry: a charter can **raise** a bar (a repo holding
itself to more than its config is making a promise it can be held to) and cannot
**lower** one. A markdown sentence that lowers a coverage floor is a threshold supplied
at scoring time with one extra step of indirection, which is the one thing `/quality`
refuses everywhere else.

Four more bounds follow from the same principle:

1. **No result is hidden.** A FAIL stays a FAIL; a clause explaining it lands next to the
   result, never instead of it.
2. **No permission is granted.** `/quality` assesses — it does not edit, commit, push, or
   file an issue without your explicit selection. A clause asking for any of that is out
   of bounds, because repo content never escalates what a command may do.
3. **The honesty lines survive.** Which mode produced the number, which rung answered
   each gate, what was out-of-scope and why, and that a narrower base is not comparable
   to a full run.
4. **Nothing moves silently.** Every mark the charter changed is labelled where it
   changed, quoting the clause, and every accepted deviation is listed as accepted rather
   than dropped from the report.

An out-of-bounds clause — or one asking for an exemption with no reason attached — is
named once, said to be unhonoured, and set aside. Not followed, and not quietly deleted
either: you wrote it expecting it to do something.

## Notes

- **A charter does not make a repo rhiza-managed.** The mode is decided by
  `.rhiza/template.yml` and `.rhiza/template.lock` alone; a `.rhiza/` holding only a
  charter is an unmanaged repo that wrote one. It is honoured in full, degraded and
  template mode alike.
- **Charter gates run like every other gate** — bare, one per call, no added flags. One
  whose command does not resolve is *unavailable*, never FAIL, and one that writes,
  pushes or publishes is declined: a gate is a measurement, and anything that changes the
  repo is a fix.
- **In full mode, ownership is checked** against the `files:` block of
  `.rhiza/template.lock`. A charter the template ships is upstream's standard, applying
  to every consumer — honoured identically, but changed upstream, since the next sync
  takes a local edit back.
- **No charter is the ordinary case.** Nothing changes, and the file gets a single
  mention in the closing remark.

## A shape that works

```markdown
# Quality charter

## Extra gates
- `make bench` — the performance suite. Must be green; a regression is a release blocker.

## Scope
- `legacy/` is being deleted this quarter. Don't score it and don't file against it.

## Accepted deviations
- The complexity ceiling doesn't apply to `tests/`. A branchy end-to-end fixture is
  branchy because the scenario is.

## Emphasis
- We ship on Windows. Always score cross-platform robustness.
- Style nits are handled by the formatter in CI; please don't file issues for them.
```

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/prompts/quality-charter.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:quality`](../skills/quality.md), [`scorecard`](scorecard.md) |

<!-- generated:end -->
