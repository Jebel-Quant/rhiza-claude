# `/rhiza:boost`

Bump the current repo to a rhiza release, apply the template sync, run the
quality gates, and open a PR with a quality scorecard.

```
/rhiza:boost [version e.g. v0.19.9]
```

The optional argument pins an explicit template version tag; it defaults to the
latest release.

## What it does

1. **Preconditions** — confirms the repo is rhiza-managed and the working tree is
   clean; notes the hosting platform and current profile.
2. **Resolves the target version** — the given tag, or the latest
   `jebel-quant/rhiza` release. Major-version jumps require confirmation.
3. **Chooses the platform profile** (GitHub vs GitLab) and reconciles
   `templates:` entries when switching.
4. **Branches off the default branch**, bumps the template `ref` in
   `.rhiza/template.yml`, and runs `make sync`.
5. **Resolves conflicts** by taking the upstream (template) side, including
   `*.rej` fallout.
6. **Runs the quality gates** by delegating to [`/rhiza:quality`](quality.md) and
   captures the per-gate PASS/FAIL table plus the 1–10 scorecard.
7. **Opens a PR** whose body carries the gate table and scorecard.
8. **Files issues** (after confirmation) for each below-10 finding, deduped
   against existing open issues on the repo's platform.

## Notes

- Bumps only the **template content** version (`ref` / `template-branch`); it
  leaves the decoupled rhiza **tool** version (`.rhiza/.rhiza-version`) untouched.
- Restores the branch you started on when it finishes.
