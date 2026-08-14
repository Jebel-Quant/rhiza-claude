# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and entries are generated from [Conventional Commits](https://www.conventionalcommits.org).

## [0.9.0] - 2026-08-14

### New Features
- *(quality)* Test the examples, not just the docstring count (#167)

## [0.8.2] - 2026-08-06

### New Features
- *(release)* Push the tag in phase B, and tag on merge in this repo (#162)

### Bug Fixes
- *(auto-tag)* Keep the no-op path free of uv (#163)

## [0.8.1] - 2026-08-06

### Bug Fixes
- *(release)* Guard phase B against the highest tag, not the declared version (#160)

## [0.8.0] - 2026-08-06

### New Features
- *(release)* Land the version bump through a PR, and tag the merged commit (#147)
- *(quality)* Degrade instead of refusing, and fix the detection gap that exposed (#153)
- *(quality)* Resolve four gates anywhere, pin the interpreter, add an audit gate (#156)

### Bug Fixes
- *(toolchain)* Pin the dev tools uvx resolves at call time (#157)

### Documentation
- *(readme)* Refresh the pinned-install examples, and track them in the bump (#148)
- Record that tests are exempt from the size and complexity bars (#154)

## [0.7.0] - 2026-08-05

### New Features
- *(quality)* Enforce subprocess discipline, add mutation testing, clear the C band (#134)
- *(prompt-wiring)* Fail the build when shipped prose names a directory that isn't there (#144)

### Bug Fixes
- *(skeleton)* Document cargo's placeholder fn so a fresh crate passes docs-coverage (#115)
- *(release)* Prepend the changelog section instead of regenerating the file (#116)
- *(release)* Treat Rust's version config as tag-derived, like Go's (#118)
- *(sync)* Match `exclude:` against destination paths, not source paths (#127)
- *(check_test_layout)* Exempt template-owned tests from mirror parity (#133)

### Documentation
- *(plugin)* Correct the spec claim, and gate the validation a submission is judged on (#137)
- *(plugin)* Stop justifying prompts/ against a directory that no longer exists (#143)
- Bring the paper up to v0.6.2, and retire commands/ from the prose (#145)

### Maintenance
- *(commands)* Rename /rhiza:uninstall to /rhiza:detach (#114)
- *(e2e)* Scaffold a real Python package, and pin its vacuous test gate (#119)
- *(ci)* Run the hooks through prek instead of pre-commit (#120)
- *(ci)* Harden every workflow job, and fix two faults in the drift job (#122)
- *(ci)* Cache uv, gate on one context, guard releases, check links (#123)
- *(skeleton)* Stop seeding a `lint` dependency group into new repos (#124)
- *(tests)* Pin the template at v1.3.2 and retire both self-retiring markers (#125)
- *(scripts)* Split the three oversized modules and clear every C-grade block (#132)
- *(sync-core)* Triage every mutation survivor in _rhiza_merge and stage_synced (#136)
- *(plugin)* Migrate maffay to the skills layout, and teach the gates both (#138)
- *(plugin)* Migrate detach, docs and status to the skills layout (#139)
- *(plugin)* Migrate the last four commands, completing the skills layout (#140)
- *(docs)* Rename docs/commands to docs/skills, and update every URL (#146)

## [0.6.2] - 2026-08-03

### New Features
- *(maffay)* Add /rhiza:maffay, a bonmot from a random Peter Maffay song (#77)
- *(book)* Publish a measured coverage badge and the HTML report (#82)
- *(contracts)* Gate the model-invocation policy and docs/nav parity (#92)
- *(rust)* Teach the plugin a third language (#85)
- *(language)* Carry the language axis past /init (#94)
- *(rust)* Run the language axis against a real crate, and check the profile exists (#100)
- *(go)* Bring Go onto the shared template, with the skeleton path it never had (#101)
- *(hooks)* Guard Bash at runtime; move the archaeology off the hot path; name the supported language axis (#110)

### Bug Fixes
- *(yaml)* Make the two readers agree, and measure the one that wasn't (#97)

### Documentation
- Introduce rhiza-claude before cataloguing it (#74) (#78)
- *(paper)* Illustrate the paper with captured output, and publish the PDF (#79)
- *(readme)* Show the CodeFactor grade badge (#81)
- Add CLAUDE.md and correct the drifted top-of-repo prose (#91)
- *(readme)* Name Rust in the language list /init actually offers (#93)
- State the docs/nav rule without dating it (#103)

### Maintenance
- *(badges)* One function per badge group, not one long build_badges (#80)
- *(pre-commit)* Gate the prose checks that had no caller (#84)
- Branch coverage, and a prose gate that reads past commands/ (#95)
- Compress command descriptions, generate docs reference blocks, adopt rhiza-hooks selectively (#111)
- Move the shipped plugin into plugin/, separating it from the repo that builds it (#112)
- *(tests)* Mirror plugin/ in the test tree, and reach the repo through fixtures (#113)

### Other Changes
- Update README.md (#83)

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
