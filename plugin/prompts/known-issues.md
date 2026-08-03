# Known issues (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, not `commands/`, so the
> user cannot invoke it. `/rhiza:quality` reads it when a gate **fails**, before
> diagnosing, to tell a known upstream failure apart from a real local gap.

Some gate failures are not this repo's fault and cannot be fixed here. Scoring them
FAIL produces a misleading number and, worse, a findings list proposing a "fix" that
makes the repo worse. Each entry below says what the failure looks like, why it is
out-of-scope, and what **not** to do about it.

**Nothing here re-runs a gate.** If a failure isn't listed, it is in scope — diagnose it
normally and follow `plugin/prompts/scorecard.md`.

## How to read the version column

Each entry names the template refs it is **known to affect**. `.rhiza/template.lock`
records the ref the repo actually synced, so compare against that, not against a
memory of what rhiza currently ships.

An entry whose range is entirely **behind** the synced ref is a candidate for deletion,
not a reason to score anything out-of-scope. Say so rather than applying it blindly: a
stale entry here is the exact failure mode this file was extracted to contain.

---

## `test_license_classifier_present` — PEP 639

| | |
| --- | --- |
| **Gate** | `make rhiza-test` |
| **Affects** | `jebel-quant/rhiza` **through v1.2.1** |
| **Score** | out-of-scope, never FAIL |
| **Upstream** | [jebel-quant/rhiza#1440](https://github.com/jebel-quant/rhiza/issues/1440) |

The synced test asserts a `License :: OSI Approved :: …` trove classifier. PEP 639
superseded those with the SPDX `license` field that `plugin/prompts/license.md` writes.

The two are not merely redundant. Declaring **both** makes `setuptools>=77` refuse to
build the project — *"License classifiers have been superseded by license expressions …
Please remove"* — and `uv_build` warns. The gate is therefore unsatisfiable for a PEP 639
project.

**Do not "fix" it by adding the classifier.** That trades a failing gate for an
unbuildable package.

> `jebel-quant/rhiza-hooks` ships a pre-commit hook, **`check-license-metadata`**, that
> rejects exactly this combination — "a PEP 639 license expression declared alongside a
> `License::` trove classifier". A repo running that hook cannot reach the broken state.
> If the repo being scored is not running it, that is a legitimate, in-scope finding:
> recommend adopting the hook rather than editing the manifest.

## `make validate` — removed from the template

| | |
| --- | --- |
| **Gate** | `make validate` |
| **Affects** | `jebel-quant/rhiza` **up to v1.1.3**; removed by v1.2.1 |
| **Score** | not applicable — don't name the target at all |

There was once a `validate` target that checked the repo for drift from the template.
Naming a target the template no longer provides is precisely how `/quality` came to
score healthy repos as broken, so nothing in the command assumes it exists.

If you meet an older template that still has it, `check_make_targets.py` reports it as
available and it can be run like any other discovered target. Nothing needs to change
here for that to work.

> Unrelated to `plugin/scripts/validate.py`, which `/rhiza:status` runs to check that
> `template.yml` itself is well-formed. The name collision is unfortunate and has
> confused this before.
