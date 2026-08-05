# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
[security advisories](https://github.com/Jebel-Quant/rhiza-claude/security/advisories/new)
rather than opening a public issue.

We aim to acknowledge reports within a few business days and will keep you
updated on remediation progress.

## Scope

This repository distributes Claude Code slash commands (Markdown prompts) and
plugin manifests (JSON). There is no runtime service. The most relevant
concerns are the shell/`gh` commands the slash commands instruct Claude Code to
run. Before installing the plugin, review the skills under `plugin/skills/` — one
`<name>/SKILL.md` per slash command — along with the internal procedures they
`Read` under `plugin/prompts/` and the stdlib-only Python they drive under
`plugin/scripts/`. Each skill declares the tools it may use in its
`allowed-tools` frontmatter, which is the shortest way to see what a command can
reach before you run it.
