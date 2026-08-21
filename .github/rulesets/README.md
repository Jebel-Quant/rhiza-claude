# Branch protection as code

`main-protection.json` is the canonical definition of the **"main protection"**
repository ruleset. It is version-controlled here so the branch-protection
policy is reviewable and reproducible.

> GitHub does **not** auto-apply this file. It is the source of truth; changes
> here must be pushed to GitHub via the API (or the ruleset UI's import).

## What it enforces on the default branch

- Changes must go through a pull request (direct pushes blocked).
- 0 required approvals — a solo maintainer can still merge their own PR.
- Conversation resolution required before merge.
- No force-pushes; no branch deletion.
- **Required status checks** — one context, the `ci-gate` job in
  `.github/workflows/ci.yml` (non-strict, so branches need not be forcibly up to
  date). That job `needs: [lint, tests, cross-platform]` and passes only when all
  three report `success`, so the real gates are still what decides a merge — but they
  can be renamed, split or replaced without re-applying this file. Only a rename of
  `ci-gate` itself leaves a required check that can never report.
  Note the deliberate gap: the `build` (book.yml), `install smoke test` (plugin.yml)
  and `Analyze` (codeql.yml) contexts live in other workflows, and a job cannot
  `needs:` across workflows, so none of them can join this gate as it stands. They run
  on every PR and are advisory.
- Repository admins may bypass (`bypass_actors`), so a solo maintainer can still
  merge in a pinch without waiting on a red/absent check.
- Unattributed changes need an extra approval
  (`require_extra_approval_for_unattributed_changes`). This was enabled on the live
  ruleset but missing from this file, so a PUT of the file would have switched it off.
  A setting changed in the UI and not mirrored here is reverted by the next apply —
  which is the cost of this file being the source of truth, and the reason to diff
  before applying rather than after.

## Apply / update

**Applying is not optional, and the gap is silent.** This file named `ci-gate` while the
live ruleset still required `lint` and `tests` directly — so `cross-platform` ran on every
PR and could not block one. Nothing reports that divergence; check it after any edit here:

```bash
gh api repos/Jebel-Quant/rhiza-claude/rules/branches/main \
  --jq '.[] | select(.type=="required_status_checks")
              | .parameters.required_status_checks[].context'
```

```bash
# Create (first time)
gh api --method POST repos/Jebel-Quant/rhiza-claude/rulesets \
  --input .github/rulesets/main-protection.json

# Update an existing ruleset (replace <id> from `gh api .../rulesets`)
gh api --method PUT repos/Jebel-Quant/rhiza-claude/rulesets/<id> \
  --input .github/rulesets/main-protection.json
```
