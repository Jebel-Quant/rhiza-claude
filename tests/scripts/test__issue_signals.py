"""Tests for the issue-text signals (`scripts/_issue_signals.py`).

The corpus below is excerpted **verbatim** from five real issues on
`Jebel-Quant/jointview`, and it is the reason this file is worth more than the sum of
its unit tests. Three were filed by a `/rhiza:quality` run and two were written by
hand, which is exactly the mix `/rhiza:fix` meets, and between them they cover every
category the module can return.

Keeping them here rather than fetching them means the taxonomy keeps its regression
test after the issues are closed and their bodies stop being reachable.

The case that matters most is #96. It names six exact functions and a target file — it
is the *most* mechanically specified issue of the five — and it must not be fixed,
because its acceptance criterion says the non-split is an equally good outcome. Any
change that reclassifies it as `mechanical` has broken the guarantee the command is
built on.
"""

from __future__ import annotations

import _issue_signals as sig
import pytest

# --- the corpus ---------------------------------------------------------------

# https://github.com/Jebel-Quant/jointview/issues/95 — /quality-filed, one outcome.
ISSUE_95 = """**Subcategory:** config hygiene — **9 → 10**

Every pytest run in this repo prints the warning. `pytest.ini` is template-owned and
takes precedence, so the `[tool.pytest.ini_options]` table in `pyproject.toml` is never
read.

**done when…** `make test` runs without the `ignoring pytest config in pyproject.toml`
warning, and `configfile: pytest.ini` / `testpaths: tests` are unchanged in the header.
"""

# https://github.com/Jebel-Quant/jointview/issues/94 — /quality-filed, one outcome,
# and it cites seven merged PRs while explaining what drifted. None is a dependency.
ISSUE_94 = """**Subcategory:** contributor documentation — **5 → 10**

The fuzzing entries were pruned in #71 and #73, the version moved to a git tag in #91,
and the syncs landed in #87 and #90. See also #79 and #86.

**done when…** every claim above matches the repo as committed — in particular the
template ref, the exclude-entry count and list, and the release flow under a dynamic
version.
"""

# https://github.com/Jebel-Quant/jointview/issues/96 — /quality-filed, TWO outcomes.
ISSUE_96 = """**Subcategory:** code complexity — **9 → 10**

Consider moving the pure layer builders into a private `src/jointview/_layers.py`.

**done when…** either `plot.py` is under ~250 lines with the layer helpers moved and
`make test` still at 100% coverage — or the split is judged not worth the indirection
and that judgement is recorded in `CLAUDE.md`'s layout section, which is an equally
good outcome.
"""

# https://github.com/Jebel-Quant/jointview/issues/76 — hand-written, offers a choice.
ISSUE_76 = """`stats.py` threads a risk-free rate through four functions and nothing
sets it.

Two honest ways out, and the issue is to pick one.

**Plumb it.** `--rf` on `cli._parser`, through `_app_args` into `mo.cli_args()`.

**Or delete it.** Drop the four parameters and let jQuantStats default.

Leaning toward plumbing it — the parameter is already correct at every layer.
"""

# https://github.com/Jebel-Quant/jointview/issues/78 — hand-written, sequenced behind
# work that has since merged.
ISSUE_78 = """The app draws the whole file, always. What is missing is one input.

**Sequencing:** after #75. Building a window on a caption that already misreports its
sample means writing the fix twice.
"""

CORPUS = {95: ISSUE_95, 94: ISSUE_94, 96: ISSUE_96, 76: ISSUE_76, 78: ISSUE_78}

# The acceptance criterion of the whole design. #78 reaches `stale` only once its
# dependency is resolved as settled, which is the caller's job, so it is asserted
# separately below.
EXPECTED = {95: "mechanical", 94: "mechanical", 96: "optional", 76: "decision", 78: "decision"}


# --- the acceptance test ------------------------------------------------------


@pytest.mark.parametrize("number", sorted(CORPUS))
def test_the_corpus_classifies_the_way_the_design_says_it_must(number):
    """The five real issues, each in the category `/rhiza:fix` is built to give it."""
    assert sig.classify(CORPUS[number]) == EXPECTED[number]


def test_a_settled_dependency_is_what_makes_78_stale():
    """#78 is only stale once `#75` is known to have closed — text alone cannot say."""
    assert sig.dependencies(ISSUE_78) == [75]
    assert sig.classify(ISSUE_78, superseded=True) == "stale"


def test_the_most_specified_issue_is_the_one_that_must_not_be_fixed():
    """#96 names a target file and six functions, and is still not fixable."""
    assert "src/jointview/_layers.py" in sig.paths(ISSUE_96)
    assert sig.classify(ISSUE_96) == "optional"


# --- acceptance ---------------------------------------------------------------


def test_acceptance_reads_the_bolded_ellipsis_form():
    assert sig.acceptance(ISSUE_95).startswith("`make test` runs without")


def test_acceptance_reads_a_plain_colon_form():
    assert sig.acceptance("Done when: it is gone.") == "it is gone."


def test_acceptance_is_none_without_one():
    assert sig.acceptance(ISSUE_76) is None


def test_acceptance_collapses_wrapped_whitespace():
    """The criterion spans lines in every real issue; it is compared as one string."""
    assert "\n" not in sig.acceptance(ISSUE_94)


def test_acceptance_stops_at_the_paragraph_break():
    assert sig.acceptance("done when… it works.\n\nSomething else entirely.") == "it works."


# --- disjunction --------------------------------------------------------------


def test_either_or_is_disjunctive():
    assert sig.is_disjunctive(sig.acceptance(ISSUE_96))


def test_a_conjunction_is_not():
    assert not sig.is_disjunctive(sig.acceptance(ISSUE_95))


def test_an_equally_good_outcome_is_disjunctive_without_the_word_either():
    assert sig.is_disjunctive("...and that is an equally good outcome.")


def test_or_the_thing_is_judged_is_disjunctive():
    assert sig.is_disjunctive("or the split is judged not worth it")


# --- decide markers -----------------------------------------------------------


def test_every_marker_in_76_is_found():
    assert sig.decide_markers(ISSUE_76) == [
        "leaning toward",
        "or delete it",
        "pick one",
        "the issue is to",
        "two honest ways",
    ]


def test_a_mechanical_body_has_no_markers():
    assert sig.decide_markers(ISSUE_95) == []


def test_a_leading_consider_is_a_marker():
    assert sig.decide_markers("Consider splitting the helpers out.") == ["consider"]


def test_consider_mid_sentence_is_not_a_marker():
    """`^` is deliberate — "considered and rejected" is a decision already taken."""
    assert sig.decide_markers("We considered and rejected that.") == []


# --- references and dependencies ----------------------------------------------


def test_references_are_deduplicated_and_sorted():
    assert sig.references(ISSUE_94) == [71, 73, 79, 86, 87, 90, 91]


def test_a_citation_is_not_a_dependency():
    """The distinction that keeps the most fixable issue in the tracker fixable."""
    assert sig.references(ISSUE_94) != []
    assert sig.dependencies(ISSUE_94) == []


def test_a_sequencing_clause_is_a_dependency():
    assert sig.dependencies(ISSUE_78) == [75]


@pytest.mark.parametrize(
    "body",
    ["Blocked by #12.", "Depends on #12.", "Once #12 lands.", "Superseded by #12.", "waits on #12"],
)
def test_every_dependency_spelling(body):
    assert sig.dependencies(body) == [12]


def test_a_line_anchor_is_not_a_reference():
    assert sig.references("see src/x.py#L12 and version 1.8.0") == []


# --- paths --------------------------------------------------------------------


def test_paths_take_slashes_and_known_suffixes():
    assert sig.paths("`pyproject.toml` and `src/a/b.py`") == ["pyproject.toml", "src/a/b.py"]


def test_a_config_key_is_not_a_path():
    assert sig.paths("`[tool.pytest.ini_options]`") == []


def test_a_command_is_not_a_path():
    assert sig.paths("`make test` and `uv run pytest tests/x.py`") == []


def test_a_line_citation_keeps_the_file_and_drops_the_line():
    assert sig.paths("`src/jointview/cli.py:67`") == ["src/jointview/cli.py"]


def test_a_line_range_citation_is_also_trimmed():
    assert sig.paths("`CLAUDE.md:188-190`") == ["CLAUDE.md"]


def test_a_dotfile_directory_keeps_its_dot():
    """`.rhiza/tests` is a directory; `rhiza/tests` is nothing at all."""
    assert sig.paths("`.rhiza/template.yml`") == [".rhiza/template.yml"]


def test_a_leading_dot_slash_is_removed():
    assert sig.paths("`./setup.cfg`") == ["setup.cfg"]


def test_a_namespaced_command_is_not_a_path():
    assert sig.paths("run `/rhiza:update`") == []


def test_an_empty_backtick_span_is_skipped():
    assert sig.paths("`` and `  `") == []


def test_a_leading_slash_is_stripped():
    assert sig.paths("`/etc/hosts.toml`") == ["etc/hosts.toml"]


# --- quality_filed ------------------------------------------------------------


def test_a_quality_issue_is_recognised():
    assert sig.quality_filed(ISSUE_95)


def test_a_hand_written_issue_is_not():
    assert not sig.quality_filed(ISSUE_76)


def test_a_subcategory_without_a_criterion_is_not_enough():
    assert not sig.quality_filed("**Subcategory:** x — **9 → 10**")


# --- classify -----------------------------------------------------------------


def test_an_open_request_blocks_whatever_else_the_text_says():
    """Precedence: the worst category wins, so a mechanical body still blocks."""
    assert sig.classify(ISSUE_95, has_open_request=True) == "blocked"


def test_blocked_outranks_stale():
    assert sig.classify(ISSUE_95, has_open_request=True, superseded=True) == "blocked"


def test_a_decide_marker_outranks_a_single_valued_criterion():
    body = "**done when…** it is gone.\n\nTwo honest ways out."
    assert sig.classify(body) == "decision"


def test_mentioning_a_template_owned_file_does_not_demote_an_issue():
    """#95 quotes `pytest.ini` to explain why the table is dead. It edits pyproject."""
    report = sig.signals(ISSUE_95, template_owned=("pytest.ini",))
    assert report["category"] == "mechanical"
    assert report["cautions"] == ["mentions template-owned paths: pytest.ini"]


def test_an_unresolvable_path_does_not_demote_an_issue_either():
    report = sig.signals(ISSUE_94, missing=(".rhiza/rhiza.mk",))
    assert report["category"] == "mechanical"
    assert report["cautions"] == ["names paths that do not resolve: .rhiza/rhiza.mk"]


# --- signals ------------------------------------------------------------------


def test_signals_carries_every_derived_fact():
    report = sig.signals(ISSUE_96)
    assert report["category"] == "optional"
    assert report["acceptance_disjunctive"] is True
    assert report["quality_filed"] is True
    assert report["cautions"] == []


def test_signals_reports_a_body_with_no_criterion_as_not_disjunctive():
    """None is not disjunctive — the field must not be true merely for being unset."""
    assert sig.signals(ISSUE_76)["acceptance_disjunctive"] is False


def test_signals_passes_the_caller_resolved_facts_through():
    report = sig.signals(ISSUE_78, superseded_by=(75,), open_requests=())
    assert report["category"] == "stale"
    assert report["superseded_by"] == [75]


def test_the_categories_are_ordered_worst_first():
    assert sig.CATEGORIES == ("blocked", "stale", "decision", "optional", "mechanical")
