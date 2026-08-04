"""Tests for the `template.yml` field checks (`scripts/_validate_fields.py`).

Two contracts, and the split between them is what these assert: the mode/required/format
checks return a **verdict** that can refuse a sync, while `validate_optional_fields`
returns nothing and can only warn. A check that migrated across that line would either
block a working repo or wave through a broken one.
"""

from __future__ import annotations

import _validate_fields as vf
import pytest
from _validate_log import Log


def log() -> Log:
    """A verbose sink, so debug lines are exercised too."""
    return Log(verbose=True)


# --- profiles ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, None),
        ({"profiles": "x"}, False),
        ({"profiles": []}, False),
        ({"profiles": [""]}, False),
        ({"profiles": ["github-project"]}, True),
    ],
)
def test_profiles_field(config, expected):
    assert vf.validate_profiles_field(log(), config) is expected


# --- configuration mode ------------------------------------------------------


def test_config_mode_profiles_invalid():
    assert vf.validate_configuration_mode(log(), {"profiles": "x"}) is False


def test_config_mode_bundles_renamed():
    assert vf.validate_configuration_mode(log(), {"bundles": ["x"], "profiles": ["p"]}) is False


def test_config_mode_nothing_specified():
    assert vf.validate_configuration_mode(log(), {"ref": "main"}) is False


def test_config_mode_variants():
    assert vf.validate_configuration_mode(log(), {"profiles": ["p"]}) is True
    assert vf.validate_configuration_mode(log(), {"templates": ["a"], "include": ["b"]}) is True
    assert vf.validate_configuration_mode(log(), {"templates": ["a"]}) is True
    assert vf.validate_configuration_mode(log(), {"include": ["b"]}) is True


@pytest.mark.parametrize(
    ("config", "expected_mode"),
    [
        ({"profiles": ["p"]}, "profile mode"),
        ({"templates": ["a"], "include": ["b"]}, "hybrid mode"),
        ({"templates": ["a"]}, "template-based mode"),
        ({"include": ["b"]}, "path-based mode"),
    ],
)
def test_config_mode_announces_which_mode_resolved(capsys, config, expected_mode):
    """The success line is how a user confirms the config means what they intended."""
    assert vf.validate_configuration_mode(log(), config) is True
    assert expected_mode in capsys.readouterr().err


# --- required fields and repository format ------------------------------------


def test_required_fields():
    assert vf.validate_required_fields(log(), {}) is False
    assert vf.validate_required_fields(log(), {"repository": 5}) is False
    assert vf.validate_required_fields(log(), {"repository": "a/b"}) is True
    assert vf.validate_required_fields(log(), {"template-repository": "a/b"}) is True


def test_template_repository_wins_over_repository():
    """Both keys are accepted; the prefixed one is the newer spelling and takes priority."""
    lg = log()
    assert vf.validate_required_fields(lg, {"template-repository": "a/b", "repository": 5}) is True


def test_repository_format():
    assert vf.validate_repository_format(log(), {}) is True  # absent → caught elsewhere
    assert vf.validate_repository_format(log(), {"repository": 5}) is False
    assert vf.validate_repository_format(log(), {"repository": "noslash"}) is False
    assert vf.validate_repository_format(log(), {"repository": "a/b"}) is True


# --- list fields -------------------------------------------------------------


def test_string_list():
    assert vf.validate_string_list(log(), {}, "templates", "ex") is True  # absent
    assert vf.validate_string_list(log(), {"templates": "x"}, "templates", "ex") is False
    assert vf.validate_string_list(log(), {"templates": []}, "templates", "ex") is False
    lg = log()
    assert vf.validate_string_list(lg, {"templates": ["a", 5]}, "templates", "ex") is True
    assert lg.warnings  # non-string entry warned


def test_string_list_pluralises_its_count(capsys):
    """A cosmetic detail, but the message is the whole output of a passing check."""
    vf.validate_string_list(log(), {"templates": ["a"]}, "templates", "ex")
    assert "1 entry" in capsys.readouterr().err
    vf.validate_string_list(log(), {"templates": ["a", "b"]}, "templates", "ex")
    assert "2 entries" in capsys.readouterr().err


# --- optional fields: warnings only ------------------------------------------


def test_branch_field():
    vf._validate_branch_field(log(), {})  # absent → no-op
    lg = log()
    vf._validate_branch_field(lg, {"ref": 5})
    assert lg.warnings
    lg2 = log()
    vf._validate_branch_field(lg2, {"template-branch": "main"})
    assert not lg2.warnings


def test_host_field():
    vf._validate_host_field(log(), {})  # absent
    lg = log()
    vf._validate_host_field(lg, {"template-host": 5})
    assert lg.warnings
    lg2 = log()
    vf._validate_host_field(lg2, {"template-host": "bitbucket"})
    assert lg2.warnings
    lg3 = log()
    vf._validate_host_field(lg3, {"template-host": "github"})
    assert not lg3.warnings


def test_language_field():
    vf._validate_language_field(log(), {})
    lg = log()
    vf._validate_language_field(lg, {"language": 5})
    assert lg.warnings
    lg2 = log()
    vf._validate_language_field(lg2, {"language": "cobol"})
    assert lg2.warnings
    lg3 = log()
    vf._validate_language_field(lg3, {"language": "python"})
    assert not lg3.warnings


def test_exclude_field():
    vf._validate_exclude_field(log(), {})
    lg = log()
    vf._validate_exclude_field(lg, {"exclude": "x"})
    assert lg.warnings
    lg2 = log()
    vf._validate_exclude_field(lg2, {"exclude": ["ok", 5]})
    assert lg2.warnings  # non-string path


def test_optional_fields_can_only_warn_never_fail():
    """Every value here is malformed, and none of it may block a sync."""
    lg = log()
    assert (
        vf.validate_optional_fields(
            lg,
            {"ref": 5, "template-host": 5, "language": 5, "exclude": "x"},
        )
        is None
    )
    assert lg.warnings
    assert lg.errors == []
