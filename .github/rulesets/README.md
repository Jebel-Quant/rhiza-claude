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
- **Required status checks** — the CI `pre-commit` and `tests` jobs must pass
  before merge (non-strict, so branches need not be forcibly up to date).
- Repository admins may bypass (`bypass_actors`), so a solo maintainer can still
  merge in a pinch without waiting on a red/absent check.

## Apply / update

```bash
# Create (first time)
gh api --method POST repos/Jebel-Quant/rhiza-claude/rulesets \
  --input .github/rulesets/main-protection.json

# Update an existing ruleset (replace <id> from `gh api .../rulesets`)
gh api --method PUT repos/Jebel-Quant/rhiza-claude/rulesets/<id> \
  --input .github/rulesets/main-protection.json
```
