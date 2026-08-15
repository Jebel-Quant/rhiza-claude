---
description: Check what CI on the origin says about this repo's open pull/merge requests, then diagnose and fix the red ones on their own branches. Reads the forge, reproduces locally, pushes fixes to the request's branch — never to the default branch.
argument-hint: "[branch, or --all for every open request]  (optional; defaults to the branch you are on)"
allowed-tools: Bash(uv*), Bash(uvx*), Bash(gh*), Bash(glab*), Bash(git*), Bash(make*), Read, Edit, Write, Grep, Glob, AskUserQuestion
---

You are running `/remote` in the **current working directory's repo**.

**The gap this closes.** `/rhiza:quality` files findings as issues, those issues become
branches, and the branches become requests that were green when they left. Local green
and origin green are different claims, and only the second one merges. A suite that
passes on a warm cache with the author's toolchain says nothing about a matrix leg on
another OS, a lockfile the runner resolves differently, a gate that exists only in the
workflow, or a network call that is rate-limited today.

This command asks the forge what actually happened, and then fixes what it finds. It is
the only rhiza command that reads CI.

**One rule outranks everything below: never make a check green by weakening it.**
Deleting the failing test, lowering the threshold, narrowing the matrix, adding
`continue-on-error` or `--ignore` — each of those turns a red build into a green one
without changing what is broken, and the next person inherits both the defect and a gate
that will never mention it again. If the honest fix is out of reach, say so, leave the
build red, and report why. A red request is information; a falsely green one is not.

## 0. Preconditions

```bash
git rev-parse --is-inside-work-tree
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" auth-status
```

`${CLAUDE_PLUGIN_ROOT}` resolves at runtime (**keep the quotes**); in a source checkout
it is empty, so fall back to `plugin/scripts/platform_cli.py`. The same substitution
applies to every script below.

`auth-status` distinguishes the two failures that look alike from here — **no CLI
installed** and **a CLI that is not logged in** — and it names which of `gh`/`glab` this
repo's `origin` calls for. Neither is something to work around: without it there is no
way to read CI, and guessing at the state of a build is worse than reporting that you
could not read it. Stop and say which of the two it was.

This command needs no `.rhiza/` directory and no template. A repo that is not
rhiza-managed still has requests and still has CI, and all of this applies unchanged.

## 1. Read the state

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/pr_status.py"
```

Flags:

- `--branch <name>` — one branch's request. The default is **the branch you are on**, so
  the bare command answers "is the thing I am working on green?".
- `--all` — every open request. Use it when `$ARGUMENTS` says so, and when the branch you
  are on has no request.
- `--limit <n>` — how many requests to fetch (default 20).
- `--json` — the same report as an object, when you want to reason over it rather than
  read it.
- `--dry-run` — print the query without running it.

If `$ARGUMENTS` names a branch, pass it to `--branch`; if it is `--all`, pass that.

**What the report means, precisely**, because two of its states are routinely
misread:

| state | reading |
| --- | --- |
| `fail` | at least one check failed. This is the work. |
| `pending` | something is still running. **Not yet an answer** — say so rather than reporting the passing subset as a verdict. |
| `cancelled` | usually superseded by a newer push, occasionally a runner that died. Look before treating it as either. |
| `unknown` | a state the script has not seen, **or no checks at all**. |
| `pass` | every check that ran, passed. |

**`unknown` with an empty check list is a finding, not a blank.** A request whose
workflow never triggered — a path filter that no longer matches, a workflow file the
runner refuses to parse, a fork whose runs need approval — shows a perfectly clean
report. Merging it is merging untested code. Chase it exactly as hard as a `fail`.

**The report is per-job on GitHub and per-pipeline on GitLab.** That asymmetry is
deliberate and is stated in `plugin/scripts/pr_status.py`: only GitHub's per-job shape has been
verified against a live forge. On GitLab the drill-down command under a failing pipeline
is the one that lists its failing jobs, so the extra step is a command away, not a guess.

## 2. Triage before diagnosing

For each failing check, the report prints a `logs:` line — the exact command for this
platform. Run it, and read the failure rather than the check name.

```bash
gh run view <RUN_ID> --log-failed
glab ci get --pipeline-id <PIPELINE_ID> --status failed --with-job-details
```

On GitLab that lists the failing jobs; `glab ci trace <JOB_ID>` then streams one job's
log. **Always name a job** — bare `glab ci trace` opens an interactive picker, which
hangs a non-interactive run.

Sort what you find into four kinds, because only one of them is a code fix:

1. **A real defect the local gates do not cover.** CI runs something you did not: another
   OS, another language version, a stricter flag, a job that only exists in the workflow.
   The code is wrong. Fix the code.
2. **An environment difference.** The runner has no `cargo`, resolves a lockfile
   differently, starts from a cold cache, or lacks a secret. The code may be fine and the
   *workflow* is what needs the change — or the dependency needs pinning.
3. **Infrastructure, upstream, transient.** A 429 from someone's CDN, a runner outage, a
   registry timeout. **Re-run it; do not "fix" it.** Editing code in response to a flake
   is how a real fix gets buried under an unrelated diff. Say plainly that you are
   attributing it to infrastructure and on what evidence — a second red run on the same
   commit means it was never a flake.
4. **A known upstream failure.** In a rhiza-managed repo, `Read`
   `${CLAUDE_PLUGIN_ROOT}/prompts/known-issues.md` (source checkout:
   `plugin/prompts/known-issues.md`) before diagnosing. It names failures that are not this
   repo's to fix, keyed by the template ref in `.rhiza/template.lock` — and one of them
   must specifically *not* be fixed, because the obvious fix makes the package
   unbuildable.

State which kind each failure is **before** proposing anything. The four have different
fixes and three of them are not code.

## 3. Reproduce locally, when it is reproducible

Before changing a line, try to make the failure happen here:

```bash
make test
make lint
```

Run the target the failing job ran, bare — no pipe, redirect, chain or `cd` prefix. The
plugin's own `PreToolUse` hook denies a compound `make` and tells you to re-run it bare,
because the arguments and thresholds live in the target.

**A failure you can reproduce is one you can verify you fixed.** One you cannot is the
common case here — that is what "passes locally, fails on origin" means — and it changes
the standard of evidence, not the standard of care. Say which situation you are in. When
you cannot reproduce it, the fix is a hypothesis until CI agrees, and the honest sentence
is "this should fix it; the run on origin will say".

## 4. Fix on the request's own branch

```bash
git fetch origin
git checkout <BRANCH>
git pull --ff-only
```

Then make the smallest change that addresses the cause, run the local gates, and commit
in Conventional Commits form:

```bash
git commit -am "fix(ci): <what changed and why>"
git push origin HEAD
```

Four boundaries, none of them negotiable:

- **Never push to the default branch.** Every fix lands on the branch its request already
  has, where it gets reviewed with the rest of that work.
- **Never force-push.** Someone else's branch may have work you cannot see, and a request
  under review has reviewers holding line numbers. If history genuinely has to be
  rewritten, ask first with `AskUserQuestion`.
- **One request at a time.** With `--all`, finish and report one before starting the
  next; a single commit spanning three unrelated red builds cannot be reviewed or
  reverted.
- **Uncommitted work that predates this command is left alone.** It rides along or stays
  behind, untouched — never stashed, never discarded.

If the branch has diverged, or the fix belongs somewhere other than this request, stop
and say so instead of improvising a merge.

## 5. Confirm, then report

Re-run step 1 for the branch you pushed to. CI takes minutes, so a `pending` report right
after a push is expected, not a result — say that rather than presenting it as one, and
let the user decide whether to wait.

Close with, per request touched:

- the check that failed, and which of the four kinds it was;
- the evidence — the log line, not a paraphrase of the job name;
- what changed, or why nothing did;
- what is still red, still pending, or deliberately left alone.

**Report the ones you did not fix as prominently as the ones you did.** An infrastructure
flake you re-ran, a failure whose honest fix is out of scope, a request you never got to
— each is a thing the user has to decide about, and a summary that mentions only the
fixed ones reads as "all clear".

For a quality score rather than a CI report, use `/rhiza:quality`; it is the only command
that scores, and it never reads the forge.
