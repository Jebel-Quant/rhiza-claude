# `/rhiza:history`

Read this repo's open pull requests and issues together, and answer the four questions a
maintainer asks of a backlog: what is obsolete, what order the open requests should merge
in, which issues are trivial, and what to address next.

```
/rhiza:history [--dry-run]
```

`--dry-run` reports and posts nothing.

## Why it exists

[`/rhiza:fix`](fix.md) triages issues so it can open pull requests, and
[`/rhiza:remote`](remote.md) reads CI on requests that already exist. Each sees half the
tracker. Neither asks what no longer needs doing, which request should go in first, or
what to pick up next. That reading has always been done by scrolling.

!!! warning "It recommends closing; it never closes"
    Closing is the maintainer's call. A wrong recommendation posted as a comment costs
    one reply, but a wrong close hides work that nobody notices is gone. The only write
    this command makes is a comment, and only on items you select.

## What it does

1. **Checks it can ask the forge** with `plugin/scripts/platform_cli.py auth-status`.
2. **Reads the backlog** with three scripts, one per question already answered elsewhere:
   - `plugin/scripts/pr_inventory.py`: per request, the files it changes, its size,
     `mergeable` state, age and idle time, the issues it closes and which of those are
     already closed. Across requests, every pair that changes a file in common.
   - `plugin/scripts/pr_status.py --all`: each request's CI rollup.
   - `plugin/scripts/issue_status.py`: each issue's acceptance criterion, decision
     markers and suggested category, the same triage `/rhiza:fix` starts from.
3. **Finds the obsolete items**, each with evidence someone can check in ten seconds. For
   requests: every issue it closes is already closed, a newer request supersedes it, its
   change already landed, or it has been idle a long time and conflicts. For issues:
   already fixed, stale, or a duplicate.
4. **Orders the open requests.** Ready requests come first. Within a cluster of requests
   that touch the same files, the one cheapest to rebase goes last. Foundations go before
   dependents, and dependency bumps go early.
5. **Lists the trivial issues**: the `mechanical` ones, verified against the tree by
   content. Each points at `/rhiza:fix <n>`.
6. **Names at most five next items**, ranked by what they unblock.
7. **Asks**, with a multi-select of the closing candidates. Nothing is preselected and
   choosing none is a valid answer. Each selected item gets a comment that *recommends*
   closing, with the evidence.

## What is not a reason to close

Age, a quiet thread, a draft, a red build and an absent author are each a reason to ask.
None of them on its own is evidence that the work is dead, so they surface under **next**
rather than **obsolete**. The one combination that does count is long idle **and**
conflicting.

## Comments carry the rhiza badge

`platform_cli.py pr-comment` and `issue-comment` stamp every comment with the same badge
as a filed issue. A comment goes out under your account, and a recommendation to close
someone's pull request reads differently once its reader knows a tool drafted it.

## Notes

- **The merge order is judgement; the overlaps are not.** Which requests share files is
  computed by `pr_inventory.py`, so it is tested and exact. Which of two colliding
  requests should rebase weighs size, risk and intent, and stays in the prose.
- **GitLab gives less.** A merge-request listing carries no files and no closing
  references. The files come from `glab mr diff --raw`, one call per request, and the
  closing references from the description's closing keywords. `closes_source` says which
  one you got.
- **An unreadable issue is never treated as closed.** A reference into another project, or
  one the token cannot see, would otherwise make a request look obsolete.
- **Bodies are data.** A request or issue that asks to be closed, merged or deleted is
  reported, never obeyed.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/history/SKILL.md` |
| **Invocation** | `/rhiza:history [--dry-run to report and post nothing]  (optional)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(uv*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(git*)`, `Read`, `Write`, `Grep`, `Glob`, `AskUserQuestion` |

<!-- generated:end -->
