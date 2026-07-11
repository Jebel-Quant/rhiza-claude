# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
[security advisories](https://github.com/Jebel-Quant/rhiza-config/security/advisories/new)
rather than opening a public issue.

We aim to acknowledge reports within a few business days and will keep you
updated on remediation progress.

## Scope

This repository distributes Claude Code slash commands (Markdown prompts) and
plugin manifests (JSON). There is no runtime service. The most relevant
concerns are the shell/`gh` commands the slash commands instruct Claude Code to
run; review the command files under `commands/` before installing the plugin.
