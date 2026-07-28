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
    "python_versions": [],
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
        ("python versions", "not a Python project"),
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
    (badge,) = [b for b in _build(python_versions=["3.12", "3.13"])["badges"] if "Python" in b]
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
