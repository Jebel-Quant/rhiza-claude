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
- **No required status checks** — deliberately, so the org-enforced CodeQL
  check (which cannot analyze this Markdown/JSON-only repo) never blocks merges.
- Repository admins may bypass (`bypass_actors`).

## Apply / update

```bash
# Create (first time)
gh api --method POST repos/Jebel-Quant/rhiza-config/rulesets \
  --input .github/rulesets/main-protection.json

# Update an existing ruleset (replace <id> from `gh api .../rulesets`)
gh api --method PUT repos/Jebel-Quant/rhiza-config/rulesets/<id> \
  --input .github/rulesets/main-protection.json
```
