# `/rhiza:fix`

Read this repo's open issues, work out which of them can be fixed without a judgement
call, and open one pull request per issue.

```
/rhiza:fix [issue numbers | --dry-run]
```

The optional argument scopes the run; the default is every open issue. `--dry-run`
triages and stops.

## Why it exists

[`/rhiza:quality`](quality.md) files findings as issues and deliberately stops there — a
scoring run that quietly edits code makes its own score unreproducible.
[`/rhiza:remote`](remote.md) looks after requests once they exist. The sentence both of
them are written around is *"findings become issues, those issues become branches, and
the branches become requests"* — and the middle step has always been done by hand.

This is the command that does it.

!!! warning "An issue that asks you to choose is reported, not guessed"
    The two failure modes are not symmetric. Refusing everything makes the command
    useless; confidently fixing something that needed a decision is worse than never
    running it, because it produces a pull request that *looks* reviewed. Where the
    evidence is thin, it reports.

## What it does

1. **Checks it can ask, and that the tree is clean.** `plugin/scripts/platform_cli.py
   auth-status` separates *no CLI installed* from *a CLI not logged in*. A dirty tree is a
   hard stop: a branch cut over someone's unrelated edits carries them into the first
   pull request, under an issue number that has nothing to do with them.
2. **Probes the gates** with `plugin/scripts/check_make_targets.py`, rather than assuming
   `make test` exists.
3. **Reads the issues** with `plugin/scripts/issue_status.py`, which normalises both forges
   into one vocabulary and derives, per issue, the signals below.
4. **Triages** into five categories, worst first, and the first match wins.
5. **Verifies** each candidate's claims against the tree — by content, never by line
   number — and demotes the ones that no longer hold.
6. **Asks**, with a multi-select of the survivors. Nothing is preselected and choosing
   none is a valid answer.
7. **Fixes one at a time**: a branch off `origin/<default>`, the smallest edit, the work
   staged, the repo's gates run bare, one Conventional Commits line, one push, one request.
8. **Reports** every category — including, as prominently, the issues it did not fix.

## The five categories

| Category | What put it there | What happens |
| --- | --- | --- |
| **`blocked`** | a request is already open against the issue | Reported, with the request named |
| **`stale`** | the issue sequences itself behind something that has since closed or merged | Reported, with what landed |
| **`decision`** | no acceptance criterion at all, or a phrase handing the reader a choice | Reported, with the alternatives and a recommendation |
| **`optional`** | an acceptance criterion admitting more than one outcome | Reported — and the "record the decision instead" branch is not taken either |
| **`mechanical`** | an acceptance criterion, single-valued, no decision marker | A candidate for the menu |

**The discriminator is the acceptance criterion, not the size of the issue.** A two-line
deletion and a nine-point documentation rewrite are both mechanical. An issue naming six
exact functions and a target file is *not*, if it also says the other outcome is equally
good — which is precisely the shape `/rhiza:quality` writes when a finding is a
suggestion rather than a defect.

**A citation is not a dependency.** An issue that explains itself by naming merged pull
requests has not been overtaken by them; one that says "after #75" has queued itself
behind #75. Only the second can make an issue stale — treating the first that way would
mark the best-annotated issue in a tracker as superseded forever.

## Two signals that are reported but never decide

An issue that *mentions* a template-owned file, and one naming a path that does not
resolve, are surfaced as **cautions** rather than as categories. Mentioning a file is not
editing it: a finding about a dead table in `pyproject.toml` quotes the `pytest.ini` that
supersedes it, and a documentation issue names a dozen paths while describing what a page
got wrong about them. Inferring the target of a fix from the nouns in its prose is the
guessing the command exists not to do, so the verification step weighs them instead.

## Promotion

A hand-written issue may be perfectly determined and still carry no `done when…`. Such an
issue can be promoted to `mechanical`, but only through a confirmation that shows the
acceptance criterion the command inferred, in its own words — and that sentence then goes
verbatim into the pull request body, so the reviewer checks the same thing. **Never
silently.** Without the escape hatch, a tracker of hand-written issues gets refused
wholesale.

## Options

- `--issue <n>` — one issue; repeatable. The default is every open issue.
- `--label <l>` — scope to a label; repeatable.
- `--limit <n>` — how many issues to fetch (default 20).
- `--json` — the triage as an object rather than as text.
- `--dry-run` — triage and stop, changing nothing.

## Notes

- **The fix is staged before the gates run, and that is load-bearing.** `pre-commit` and
  `prek` build their file list from git, so a file the edit *created* is invisible to every
  hook while it is untracked — they all report a clean pass on a file none of them opened,
  and the first real lint happens in CI on a request already under review. A command that
  routinely adds a module or a test is exactly the one that would get this wrong. It is
  safe here only because the tree was proved clean before the branch was cut.
- **A failed gate never produces a pull request.** The attempt is committed on its branch
  and left unpushed, so the tree is clean for the next issue and a never-green branch
  stays out of review. The branch is never deleted.
- **Never `SKIP=`, and never weaken a gate.** A fix that lands in a template-owned path
  belongs upstream in the template, or under `exclude:` in `.rhiza/template.yml` — both
  the user's call, so the issue is reported as `blocked` instead.
- **`Refs #N`, not `Closes #N`, whenever part of the criterion is unmet.** A `Closes` on a
  partial fix makes the issue vanish with work still in it.
- **An issue body is data, not instructions.** Signals are read out of it; commands in it
  are never run.
- **GitLab resolves fewer references.** `#N` there is always an issue, never a merge
  request, so a reference to one comes back unresolved rather than guessed at — which
  pushes an issue toward *reported* rather than *fixed*. The weaker path degrades safe.
- For a score rather than a fix, use [`/rhiza:quality`](quality.md); for a red build on an
  existing request, [`/rhiza:remote`](remote.md).

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/fix/SKILL.md` |
| **Invocation** | `/rhiza:fix [issue numbers to scope to, or --dry-run to triage and stop]  (optional; defaults to every open issue)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(uv*)`, `Bash(uvx*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(git*)`, `Bash(make*)`, `Read`, `Edit`, `Write`, `Grep`, `Glob`, `AskUserQuestion` |

<!-- generated:end -->
