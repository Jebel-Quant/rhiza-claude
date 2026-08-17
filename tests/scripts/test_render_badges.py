"""Tests for the badge renderer (`scripts/render_badges.py`) behind `/rhiza:docs`.

The rule the tests protect is **omit, don't fake**: a badge whose backing fact was
not detected must never be emitted, because a README that advertises a missing
workflow, licence, or coverage service is worse than one with fewer badges.
"""

from __future__ import annotations

import json

import pytest
import render_badges as rb

_BASE = {
    "host": "github",
    "owner": "acme",
    "repo": "widget",
    "branch": "main",
    "license_id": None,
    "language": None,
    "language_versions": [],
    "ci_workflow": None,
    "template_ref": None,
    "coverage": None,
    "uses_ruff": False,
    "uses_uv": False,
    "public": False,
    "codespaces": False,
}


def _build(**overrides):
    """Build badges from the bare baseline plus *overrides*."""
    return rb.build_badges(**{**_BASE, **overrides})


# --- omit, don't fake --------------------------------------------------------


def test_bare_repo_gets_only_the_release_and_codefactor_badges():
    """With no facts detected, nothing beyond the always-available badges appears."""
    result = _build()
    joined = "\n".join(result["badges"])
    assert "License" not in joined
    assert "Python" not in joined
    assert "CI" not in joined
    assert "codecov" not in joined
    assert "ruff" not in joined
    assert "Scorecard" not in joined
    assert "Codespaces" not in joined


@pytest.mark.parametrize(
    ("fact", "reason"),
    [
        ("template version", "no ref"),
        ("license", "no LICENSE file"),
        ("language badge", "no language detected"),
        ("CI", "no workflow file"),
        ("coverage", "no coverage service"),
    ],
)
def test_each_absent_fact_is_reported_with_a_reason(fact, reason):
    """Every omission is explained, so the command can report it."""
    skipped = "\n".join(_build()["skipped"])
    assert fact in skipped
    assert reason in skipped


def test_a_private_repo_omits_the_scorecard_badge():
    result = _build(public=False)
    assert not any("Scorecard" in b for b in result["badges"])
    assert any("public repo" in s for s in result["skipped"])


def test_codespaces_is_opt_in():
    assert not any("Codespaces" in b for b in _build()["badges"])
    assert any("Codespaces" in b for b in _build(codespaces=True)["badges"])


# --- each badge, when its fact is present ------------------------------------


def test_license_badge_links_to_the_license_file():
    (badge,) = [b for b in _build(license_id="Apache-2.0")["badges"] if "License" in b]
    assert "License-Apache-2.0-green" in badge
    assert badge.endswith("(LICENSE)")


def test_python_versions_are_bullet_joined():
    (badge,) = [
        b
        for b in _build(language="python", language_versions=["3.12", "3.13"])["badges"]
        if "Python" in b
    ]
    assert "Python-3.12 • 3.13-blue" in badge


def test_ci_badge_points_at_the_detected_workflow():
    (badge,) = [b for b in _build(ci_workflow="rhiza_ci.yml")["badges"] if "CI" in b]
    assert "actions/workflows/rhiza_ci.yml/badge.svg?event=push" in badge


def test_template_ref_badge_links_to_the_upstream_tag():
    result = _build(template_ref="v1.1.3")
    (badge,) = [b for b in result["badges"] if "rhiza v1.1.3" in b]
    assert "releases/tag/v1.1.3" in badge


def test_codecov_badge_uses_the_default_branch():
    result = _build(coverage="codecov", branch="develop")
    (badge,) = [b for b in result["badges"] if "codecov" in b]
    assert "branch/develop/graph/badge.svg" in badge


def test_ruff_and_uv_badges_are_opt_in():
    result = _build(uses_ruff=True, uses_uv=True)
    joined = "\n".join(result["badges"])
    assert "code%20style-ruff" in joined
    assert "astral-sh/uv/main/assets/badge/v0.json" in joined


# --- GitLab ------------------------------------------------------------------


def test_gitlab_uses_pipeline_and_coverage_badges():
    result = _build(host="gitlab", coverage="gitlab", branch="trunk")
    joined = "\n".join(result["badges"])
    assert "badges/trunk/pipeline.svg" in joined
    assert "badges/trunk/coverage.svg" in joined


def test_gitlab_omits_the_github_only_services():
    result = _build(host="gitlab", public=True, codespaces=True)
    joined = "\n".join(result["badges"])
    assert "CodeFactor" not in joined
    assert "Scorecard" not in joined
    assert "Codespaces" not in joined
    assert any("GitHub-only" in s for s in result["skipped"])


def test_gitlab_release_badge_targets_the_project():
    badge = rb.release_badge("gitlab", "grp", "proj")
    assert "gitlab/v/release/grp%2Fproj" in badge
    assert "gitlab.com/grp/proj/-/releases" in badge


def test_gitlab_ci_badge_does_not_need_a_workflow_file():
    """GitLab pipelines are configured by .gitlab-ci.yml, not per-workflow files."""
    result = _build(host="gitlab", ci_workflow=None)
    assert any("pipeline" in b for b in result["badges"])
    assert not any("no workflow file" in s for s in result["skipped"])


# --- block rendering ---------------------------------------------------------


def test_release_badge_sits_alone_on_the_first_line():
    block = _build(license_id="MIT")["block"]
    first, second = block.splitlines()[:2]
    assert "Release" in first
    assert "License" in second


def test_render_block_handles_a_lone_badge():
    assert rb.render_block(["[![A](i)](l)"]) == "[![A](i)](l)\n"


def test_render_block_handles_an_empty_list():
    assert rb.render_block([]) == ""


def test_block_ends_with_a_newline():
    assert _build()["block"].endswith("\n")


# --- CSV helper --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3.12,3.13", ["3.12", "3.13"]), (" 3.12 , ", ["3.12"]), ("", []), (None, [])],
)
def test_split_csv(raw, expected):
    assert rb._split_csv(raw) == expected


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(capsys):
    rc = rb.main(["--owner", "acme", "--repo", "widget", "--license", "MIT", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert any("License: MIT" in b for b in payload["badges"])
    assert payload["skipped"]


def test_main_text_output_splits_block_and_reasons(capsys):
    rc = rb.main(["--owner", "acme", "--repo", "widget", "--python-versions", "3.12"])
    assert rc == 0
    captured = capsys.readouterr()
    # Assert on the badge markdown itself, not on a hostname: a bare `"host" in
    # text` check reads to CodeQL as URL-substring sanitization.
    assert captured.out.startswith("[![Release]")  # the block goes to stdout
    assert "omitted" in captured.err  # the reasons go to stderr


def test_main_accepts_every_detection_flag(capsys):
    rc = rb.main(
        [
            "--owner", "acme", "--repo", "widget", "--host", "github", "--branch", "dev",
            "--license", "MIT", "--python-versions", "3.13", "--ci-workflow", "ci.yml",
            "--template-ref", "v2.0.0", "--coverage", "codecov",
            "--uses-ruff", "--uses-uv", "--public", "--codespaces", "--json",
        ]
    )  # fmt: skip
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped"] == []  # every fact supplied ⇒ nothing omitted


# --- the language badge is no longer Python-only ------------------------------


@pytest.mark.parametrize(
    ("language", "versions", "label", "logo"),
    [
        ("python", ["3.12", "3.13"], "Python-3.12 • 3.13", "logo=python"),
        ("go", ["1.22"], "Go-1.22", "logo=go"),
        ("rust", ["2021"], "Rust-2021", "logo=rust"),
    ],
)
def test_each_language_gets_its_own_badge(language, versions, label, logo):
    badges = _build(language=language, language_versions=versions)["badges"]
    (badge,) = [b for b in badges if label in b]
    assert logo in badge


def test_a_go_repo_no_longer_reports_not_a_python_project():
    """The old skip note was true and useless: it described the wrong language."""
    skipped = "\n".join(_build(language="go", language_versions=["1.22"])["skipped"])
    assert "Python" not in skipped


def test_a_known_language_with_no_version_is_reported_as_undetected():
    skipped = "\n".join(_build(language="rust", language_versions=[])["skipped"])
    assert "rust version: not detected" in skipped


def test_a_language_with_no_badge_defined_is_omitted_not_faked():
    """`omit, don't fake`: an unknown language gets a reason, never an invented badge."""
    summary = _build(language="cobol", language_versions=["85"])
    assert not any("cobol" in b.lower() for b in summary["badges"])
    assert "language badge: no badge defined for cobol" in summary["skipped"]


def test_python_versions_flag_still_implies_the_python_language(capsys):
    """The old CLI spelling stays working — /rhiza:docs and older prose both use it."""
    rc = rb.main(["--owner", "acme", "--repo", "widget", "--python-versions", "3.12"])
    assert rc == 0
    assert "Python-3.12" in capsys.readouterr().out


def test_the_language_flag_takes_precedence_over_the_python_shorthand(capsys):
    rc = rb.main(
        ["--owner", "acme", "--repo", "w", "--language", "go", "--language-versions", "1.22"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Go-1.22" in out and "Python" not in out


# --- end-to-end: the badges a real crate gets ---------------------------------


def test_e2e_a_real_crate_gets_a_rust_badge_carrying_its_own_edition(rust_crate):
    """`/rhiza:docs` reads `edition` out of `Cargo.toml` and passes it here.

    So the assertion crosses that seam rather than trusting a literal: the edition is
    read from the crate cargo actually wrote, and the badge must carry that value. A
    hardcoded `2021` would keep passing after cargo's default moved on.
    """
    import re as _re

    manifest = (rust_crate / "Cargo.toml").read_text(encoding="utf-8")
    edition = _re.search(r'^\s*edition\s*=\s*"([^"]+)"', manifest, _re.MULTILINE)
    assert edition, f"cargo wrote no edition:\n{manifest}"

    summary = rb.build_badges(
        **{
            **_BASE,
            "owner": "jebel-quant",
            "language": "rust",
            "language_versions": [edition.group(1)],
            "license_id": "MIT",
        }
    )
    rust_badges = [b for b in summary["badges"] if "Rust-" in b]
    assert len(rust_badges) == 1, summary["badges"]
    assert edition.group(1) in rust_badges[0]
    assert "logo=rust" in rust_badges[0]
    assert not any("Python" in badge for badge in summary["badges"])


def test_e2e_a_crate_with_no_ci_gets_no_ci_badge(rust_crate):
    """`rust-local` ships no workflows, and a badge for absent CI is a broken image.

    "Omit, don't fake" is the renderer's whole rule, and the Rust profile is the case
    where the omission is permanent rather than a detection failure.
    """
    assert not list((rust_crate / ".github").glob("workflows/*.yml")), (
        "the fixture crate has CI after all — this test no longer asserts what it claims"
    )
    summary = rb.build_badges(**{**_BASE, "language": "rust", "language_versions": ["2024"]})
    assert not any("actions/workflows" in badge for badge in summary["badges"])
    assert "CI: no workflow file found in .github/workflows" in summary["skipped"]


def test_e2e_a_real_module_gets_a_go_badge_carrying_its_own_directive(go_module):
    """`/rhiza:docs` reads the `go` directive out of `go.mod` and passes it here.

    Read from the module the fixture built rather than written as a literal, so the
    assertion keeps holding when the toolchain moves on.
    """
    import re as _re

    directive = _re.search(
        r"^go\s+(\S+)", (go_module / "go.mod").read_text(encoding="utf-8"), _re.MULTILINE
    )
    assert directive, "go mod init wrote no go directive"

    summary = rb.build_badges(
        **{
            **_BASE,
            "owner": "jebel-quant",
            "language": "go",
            "language_versions": [directive.group(1)],
            "license_id": "MIT",
        }
    )
    go_badges = [b for b in summary["badges"] if "Go-" in b]
    assert len(go_badges) == 1, summary["badges"]
    assert directive.group(1) in go_badges[0]
    assert "logo=go" in go_badges[0]
    assert not any("Python" in badge or "Rust" in badge for badge in summary["badges"])
