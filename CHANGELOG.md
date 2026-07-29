# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and entries are generated from [Conventional Commits](https://www.conventionalcommits.org).

## [0.6.1] - 2026-07-29

### New Features
- *(release)* Present version options as a table, never a suggestion (#76)

### Bug Fixes
- *(release)* Push the release commit and tag atomically (#75)

## [0.6.0] - 2026-07-29

### New Features
- Move the gh/glab mapping into a script, making GitLab testable (#60)
- *(ci)* Watch for template drift on a schedule (#64) (#66)
- *(update)* Execute conflict resolution instead of describing it (#61) (#67)
- *(platform)* One tested home for the gh/glab mapping (#63) (#69)

### Bug Fixes
- *(init)* Stop conflating where the repo lives with where the template lives (#59)

### Maintenance
- Add integration tests for the prose commands (#56)
- Drive commands against fixture repos, and probe /quality's gates (#57)
- Always-on end-to-end tests for all seven commands (fixes three live bugs) (#58)
- *(sync)* Assert the merge algorithm's invariants, not its line coverage (#65) (#70)
- *(sync)* Merge the snapshots directly, deleting the diff round-trip (#71)
- *(sync)* Split sync.py into one module per concern (#72)
- *(quality)* Run the gates end to end instead of probing them (#62) (#68)
- Remove scripts/release.sh, now that /rhiza:release covers this repo (#73)

## [0.5.0] - 2026-07-28

### Bug Fixes
- *(release)* [**breaking**] Bump every declared version location, and offer a version menu (#55)

### Maintenance
- [**breaking**] Split commands from internal procedures; 12 commands to 7; fix /update's template-only guarantee (#54)

## [0.4.2] - 2026-07-19

### New Features
- *(install)* Run make test and enhance a pre-existing pyproject.toml (#34)
- *(new)* Add /rhiza:new to scaffold a module + mirrored test (#39)
- *(status)* Add --check (is the template behind the latest release?) (#37)
- *(release)* Add /rhiza:release to prepare an app release locally (#40)
- *(init)* Wrap uv init; delegate to /update when already managed (#43)
- *(init)* Wrap uv init; delegate to /update when already managed (#46)
- Fold make-help README sync into /revisit (#48)
- /revisit make-help README sync; harden /release version + pin bumps (#49)
- *(check_test_layout)* Exempt tests/benchmarks and tests/stress from parity (#50)
- *(check_test_layout)* Add documented opt-out for behaviour-organised suites (#51)

### Documentation
- Explain how to install a pinned plugin version (#33)
- *(readme)* Document the status/validate/uninstall repo-utility commands (#38)

### Maintenance
- Remove the /sync command (subsumed by /update) (#32)
- *(status)* Fold /tree into `status --files`, retire /tree (#36)
- Smoke-test that the rhiza plugin installs and its commands register (#35)
- *(commands)* Rename install→init (reverses #28) (#41)
- *(init_scaffold)* Retire package/readme templates; drop the last uvx rhiza dependency (#44)
- Drop Makefile targets redundant with `make lint` (#45)
- Run bundled scripts under uv-pinned python 3.12

## [0.4.1] - 2026-07-13

### Maintenance
- Drop the retired .rhiza-version tool-version field (#31)

## [0.4.0] - 2026-07-13

### New Features
- *(boost)* Always branch from default, restore invocation branch on exit (#11)
- *(stats)* Extract /stats into scripts/stats.py + HTML dashboard (#12)
- *(stats)* Prefer `rhiza status --json` for authoritative template state (#14)
- *(commands)* Add stdlib-only validate + status commands with tests (#15)
- *(commands)* Add stdlib-only tree + uninstall commands with tests (#16)
- *(make)* Add `make install` target for plugin installation (#17)
- *(commands)* Add stdlib-only repos command listing rhiza-topic repos as JSON (#18)
- *(commands)* Add `init` command to bootstrap a rhiza-managed repo (#19)
- *(sync)* Bundle a stdlib-only `rhiza sync` port + /rhiza:sync command (#30)

### Documentation
- Add mkdocs book with a page per command + Pages CI/CD (#20)

### Maintenance
- Add `make clean` target (#13)
- Rename rhiza-config → rhiza-claude (#21)
- Reach 100% script coverage + raise gate to 100% (#23)
- Raise script coverage to 85% + enforce an 80% gate (#22)
- Add a strict mypy type-check gate (#24)
- Add community files + a 100% docstring-coverage gate (#25)
- Add CodeQL + OpenSSF Scorecard security workflows (#26)
- Require the CI checks in the main-protection ruleset (#27)
- *(commands)* Rename boost→update and init→install (#28)
- Enforce 1:1 test/source layout parity (new gate + suite refactor) (#29)

## [0.3.0] - 2026-07-11

### Other Changes
- Add release, changelog, pre-commit, CI, and Dependabot machinery (#9)

## [0.2.0] - 2026-07-11

### Other Changes
- Track authored Claude Code config
- Add README
- Add /global_rhiza_revisit and /global_rhiza_stats commands
- Merge pull request #1 from tschm/add-rhiza-revisit-stats-commands
- Fix global_rhiza_stats robustness from a real run
- Merge pull request #2 from tschm/fix-rhiza-stats-robustness
- Revisit README: badges and repo identity
- Add MIT license
- Merge pull request #3 from Jebel-Quant/revisit-readme
- Keep only the License badge
- Merge pull request #4 from Jebel-Quant/revisit-readme
- Fix global_rhiza_stats robustness from a real run (#6)
- Convert repo into a Claude Code plugin marketplace (#5)
- Add main branch-protection ruleset as code (#7)
- Bump plugin version to 0.2.0 (#8)

<!-- generated by git-cliff -->
