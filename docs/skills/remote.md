# `/rhiza:remote`

Ask the forge what CI actually said about this repo's open requests, then diagnose and
fix the red ones on their own branches.

```
/rhiza:remote [branch | --all]
```

The optional argument scopes the run; the default is the branch you are on.

## Why it exists

[`/rhiza:quality`](quality.md) files findings as issues, those issues become branches,
and the branches become requests that were green when they left. **Local green and
origin green are different claims, and only the second one merges.** A suite that passes
on a warm cache with your toolchain says nothing about a matrix leg on another OS, a
lockfile the runner resolves differently, a gate that exists only in the workflow, or a
network call that is rate-limited today.

This is the only rhiza command that reads CI.

!!! warning "Never make a check green by weakening it"
    Deleting the failing test, lowering the threshold, narrowing the matrix, adding
    `continue-on-error` — each turns a red build green without changing what is broken,
    and the next person inherits both the defect and a gate that will never mention it
    again. If the honest fix is out of reach, the command leaves the build red and says
    why. A red request is information; a falsely green one is not.

## What it does

1. **Checks it can ask.** `plugin/scripts/platform_cli.py auth-status` distinguishes *no CLI
   installed* from *a CLI that is not logged in*, and names whether this repo's `origin`
   calls for `gh` or `glab`. Neither is worked around — guessing at the state of a build
   is worse than reporting that it could not be read.
2. **Reads the state** with `plugin/scripts/pr_status.py`, which normalises both forges into
   one vocabulary and prints, per request, a rollup plus the individual checks — each
   failing one carrying the exact drill-down command for its platform.
3. **Triages** each failure into one of four kinds (below) *before* proposing anything.
4. **Reproduces locally** where the failure is reproducible, using the repo's own `make`
   targets, bare.
5. **Fixes on the request's own branch**, commits in Conventional Commits form, and
   pushes there — never to the default branch, never with `--force`.
6. **Reports** what was fixed, what was not, and what is still pending.

## The four kinds of failure

Only one of them is a code fix, which is why the command names the kind first.

| Kind | What it looks like | What to do |
| --- | --- | --- |
| **Real defect** | CI runs something you don't: another OS, another language version, a stricter flag, a CI-only job | Fix the code |
| **Environment difference** | No `cargo` on the runner, a cold cache, a lockfile resolved differently, a missing secret | Fix the workflow, or pin the dependency |
| **Infrastructure** | A 429 from a CDN, a runner outage, a registry timeout | **Re-run it.** Editing code in response to a flake buries the real fix |
| **Known upstream** | A failure the template is already carrying | [`known-issues`](../internals/known-issues.md) names them, keyed by your `template.lock` ref — one of them must specifically *not* be fixed |

## Reading the report

| state | reading |
| --- | --- |
| `fail` | at least one check failed — this is the work |
| `pending` | something is still running; **not yet an answer** |
| `cancelled` | usually superseded by a newer push, occasionally a runner that died |
| `unknown` | a state the script has not seen, **or no checks at all** |
| `pass` | every check that ran, passed |

**`unknown` with an empty check list is a finding, not a blank.** A request whose
workflow never triggered — a path filter that no longer matches, a workflow file the
runner refuses to parse, a fork whose runs need approval — shows a perfectly clean
report. Merging it is merging untested code.

## Options

- `--branch <name>` — one branch's request; the default is the branch you are on.
- `--all` — every open request, one at a time.
- `--limit <n>` — how many requests to fetch (default 20).
- `--json` — the report as an object rather than as text.
- `--dry-run` — print the query without running it.

## Notes

- **The report is per-job on GitHub and per-pipeline on GitLab**, and that asymmetry is
  deliberate. Only GitHub's per-job shape has been verified against a live forge, and a
  normaliser written from a guess is exactly how a `glab` flag that never existed once
  shipped. On GitLab the drill-down command under a failing pipeline is the one that
  lists its failing jobs.
- **It needs no `.rhiza/` directory and no template.** A repo that isn't rhiza-managed
  still has requests and still has CI.
- **CI takes minutes.** A `pending` report right after a push is expected, not a result.
- For a quality score rather than a CI report, use [`/rhiza:quality`](quality.md) — it is
  the only command that scores, and it never reads the forge.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/remote/SKILL.md` |
| **Invocation** | `/rhiza:remote [branch, or --all for every open request]  (optional; defaults to the branch you are on)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(uv*)`, `Bash(uvx*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(git*)`, `Bash(make*)`, `Read`, `Edit`, `Write`, `Grep`, `Glob`, `AskUserQuestion` |

<!-- generated:end -->
