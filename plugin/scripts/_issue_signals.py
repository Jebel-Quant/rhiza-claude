#!/usr/bin/env python3
"""What an issue's *text* says about whether it can be fixed without a judgement call.

``issue_status.py``'s other half. That module talks to a forge — two CLIs that disagree
about the shape of an issue — and this one never does: everything here is a pure
function over a title, a body and the repo's lock file, which is why it carries the
doctests and why it can be covered exhaustively.

**The discriminator is the acceptance criterion, not the size of the issue.** The
tempting signal is length — a two-line deletion feels safe and a nine-point rewrite
feels risky — and it is the wrong one in both directions. What actually separates an
issue a command may fix from one it may not is whether the issue says what "done" means
and whether that sentence admits exactly one outcome. ``/rhiza:quality`` writes such a
sentence (``prompts/scorecard.md`` §4 requires a ``done when…``), so its own issues are
the easy case; a hand-written issue that happens to carry one is just as fixable, and
one of its own that offers the reader a choice is not.

Three issues filed by the same ``/quality`` run make the point:

    #95  "done when… `make test` runs without the warning"          one outcome
    #94  "done when… every claim above matches the repo"            one outcome
    #96  "done when… **either** plot.py is under ~250 lines …       two outcomes
          **or** the split is judged not worth it"

#96 names six exact functions and a target file. It is the most mechanically specified
of the three and it is the one that must not be fixed, because the issue says the
non-split is an equally good outcome. **A disjunction in the acceptance criterion is
disqualifying on its own**, whatever the rest of the body looks like.

The categories are ordered worst-first and the first match wins, so a single decision
marker outranks every mechanical signal beneath it. The category this module derives is
a *starting point*: ``skills/fix/SKILL.md`` re-verifies each claim against the tree and
may demote it. Nothing here may promote an issue that the prose demoted.
"""

from __future__ import annotations

import re
from typing import Any

# Worst-first. `classify` returns the first that matches, so the order is the policy.
CATEGORIES = ("blocked", "stale", "decision", "optional", "mechanical")

# The acceptance criterion `prompts/scorecard.md` asks every filed finding to carry.
# Matched case-insensitively and without the bolding, because a hand-written issue that
# says "done when" in plain prose is making the same promise as a generated one.
_ACCEPTANCE = re.compile(
    r"(?:\*\*)?done\s+when(?:\s*…|\s*\.\.\.|:)?(?:\*\*)?\s*(.+?)(?:\n\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# "Either A or B", and the two phrasings that say the same thing without "either".
_DISJUNCTIVE = (
    re.compile(r"\beither\b.+?\bor\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bequally good outcome\b", re.IGNORECASE),
    re.compile(r"\bor the \w+ is judged\b", re.IGNORECASE),
)

# Phrases in which an issue hands the reader a choice rather than an instruction. Each
# one is quoted from a real issue body; this is a list of observed spellings, not an
# attempt at natural-language understanding.
_DECIDE_MARKERS = (
    re.compile(r"\btwo (?:honest )?ways\b", re.IGNORECASE),
    re.compile(r"\bpick one\b", re.IGNORECASE),
    re.compile(r"\bthe issue is to\b", re.IGNORECASE),
    re.compile(r"\bleaning toward\b", re.IGNORECASE),
    re.compile(r"\bor delete it\b", re.IGNORECASE),
    re.compile(r"^\s*consider\b", re.IGNORECASE),
)

# `#123`, but not `#123` inside a fenced block or a URL fragment. Kept deliberately
# simple: a false positive costs a resolved reference the caller then ignores, while a
# false negative costs a missed supersession, which is the expensive direction.
_REFERENCE = re.compile(r"(?<![\w/])#(\d{1,6})\b")

# A reference the issue *depends on*, as opposed to one it merely cites. The difference
# decides whether a merged reference makes an issue stale, and getting it wrong is not
# symmetric: #94 cites seven merged PRs while explaining what drifted — treating those
# as dependencies would mark the most fixable issue in the tracker as superseded and
# refuse it forever. Only a clause that declares an ordering counts.
_DEPENDENCY = re.compile(
    r"(?:sequencing\s*:?\s*|\bafter\b|\bblocked by\b|\bdepends on\b|\bonce\b|"
    r"\bsupersed\w*\s+by\b|\bwaits? on\b)[^.\n#]{0,40}#(\d{1,6})\b",
    re.IGNORECASE,
)

# A backticked token that looks like a repo path: it has a slash or a known suffix, and
# no spaces. `make test` and `[tool.pytest.ini_options]` must not match.
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_PATH_SUFFIX = re.compile(
    r"\.(?:py|toml|md|ya?ml|cfg|ini|txt|json|lock|tex|sh|rs|go|js|ts)$", re.IGNORECASE
)
# A `file.py:67` citation. The line number is dropped: it drifts, and `skills/fix` is
# required to verify by content rather than by line anyway.
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


def acceptance(body: str) -> str | None:
    """The issue's ``done when…`` sentence, or None when it carries none.

    >>> acceptance("**done when…** the warning is gone.")
    'the warning is gone.'

    The bolding and the ellipsis are both optional, so a hand-written issue reaches
    this too:

    >>> acceptance("Done when: every claim matches the repo.")
    'every claim matches the repo.'

    An issue that never says what done means gets None, which is the single strongest
    signal in the module:

    >>> acceptance("Two honest ways out, and the issue is to pick one.") is None
    True
    """
    match = _ACCEPTANCE.search(body)
    return " ".join(match.group(1).split()) if match else None


def is_disjunctive(text: str) -> bool:
    """Whether *text* admits more than one outcome.

    >>> is_disjunctive("either plot.py is under 250 lines or the split is judged "
    ...                "not worth the indirection")
    True
    >>> is_disjunctive("the warning is gone and testpaths is unchanged")
    False

    "An equally good outcome" is the same claim without the word "either":

    >>> is_disjunctive("...and that judgement is recorded, which is an equally "
    ...                "good outcome.")
    True
    """
    return any(pattern.search(text) for pattern in _DISJUNCTIVE)


def decide_markers(body: str) -> list[str]:
    """Every phrase in *body* that hands the reader a choice.

    >>> decide_markers("Two honest ways out, and the issue is to pick one.")
    ['pick one', 'the issue is to', 'two honest ways']

    >>> decide_markers("Delete the dead table from pyproject.toml.")
    []
    """
    found = {
        match.group(0).strip().lower()
        for pattern in _DECIDE_MARKERS
        if (match := pattern.search(body))
    }
    return sorted(found)


def references(body: str) -> list[int]:
    """The issue and request numbers *body* mentions, in ascending order.

    >>> references("Sequencing: after #75. See also #86 and #75 again.")
    [75, 86]

    A bare number, or one inside a path, is not a reference:

    >>> references("bumped to 1.8.0 and src/x.py#L12")
    []
    """
    return sorted({int(m.group(1)) for m in _REFERENCE.finditer(body)})


def dependencies(body: str) -> list[int]:
    """The references *body* declares an ordering against, in ascending order.

    A subset of :func:`references`, and the distinction is the one that decides
    staleness. An issue sequenced behind work that has since merged may have been
    overtaken by it; an issue that merely *cites* a merged PR has not:

    >>> dependencies("**Sequencing:** after #75. Building on a caption that lies "
    ...              "means writing the fix twice.")
    [75]

    >>> dependencies("the fuzzing entries were pruned in #71 and #73, and the "
    ...              "version moved to a git tag in #91")
    []

    Both spellings of a block, and a supersession named outright:

    >>> dependencies("Blocked by #12; superseded by #34.")
    [12, 34]
    """
    return sorted({int(m.group(1)) for m in _DEPENDENCY.finditer(body)})


def paths(body: str) -> list[str]:
    """The backticked tokens in *body* that are shaped like repository paths.

    A slash or a known file suffix qualifies; anything else in backticks is prose,
    a command or a config key, and those outnumber the paths in a typical body:

    >>> paths("Delete `[tool.pytest.ini_options]` from `pyproject.toml`, then "
    ...       "run `make test` and check `src/jointview/plot.py`.")
    ['pyproject.toml', 'src/jointview/plot.py']

    A token carrying a space is a command, whatever else it looks like:

    >>> paths("`uv run pytest tests/test_x.py`")
    []

    A `file:line` citation names the file; the line number is dropped, because line
    numbers drift and the file is the part still worth checking:

    >>> paths("see `src/jointview/cli.py:67`")
    ['src/jointview/cli.py']

    A leading `./` is removed without eating the dot of a dotfile — `.rhiza/tests`
    is a directory, not `rhiza/tests`:

    >>> paths("`./setup.cfg` and `.rhiza/template.yml`")
    ['.rhiza/template.yml', 'setup.cfg']

    A command namespaced with a colon is not a path, however many slashes it has:

    >>> paths("run `/rhiza:update` afterwards")
    []
    """
    found = set()
    for match in _BACKTICKED.finditer(body):
        token = match.group(1).strip()
        if " " in token or not token:
            continue
        token = _LINE_SUFFIX.sub("", token)
        if ":" in token:
            continue
        token = token.removeprefix("./").lstrip("/")
        if token and ("/" in token or _PATH_SUFFIX.search(token)):
            found.add(token)
    return sorted(found)


def quality_filed(body: str) -> bool:
    """Whether *body* has the shape ``/rhiza:quality`` writes.

    ``prompts/scorecard.md`` §5 requires a subcategory line and an acceptance
    criterion, so both together identify an issue this plugin wrote — which means its
    structure can be relied on rather than inferred.

    >>> quality_filed("**Subcategory:** config hygiene — **9 → 10**\\n\\n"
    ...               "**done when…** the warning is gone.")
    True
    >>> quality_filed("**done when…** the warning is gone.")
    False
    """
    return "**Subcategory:**" in body and acceptance(body) is not None


def classify(
    body: str,
    *,
    has_open_request: bool = False,
    superseded: bool = False,
) -> str:
    """Which of :data:`CATEGORIES` *body* falls into, worst first.

    The two keyword arguments carry what the text cannot know, and both are facts
    rather than readings: whether a request is already open against this issue, and
    whether a reference the issue **sequences itself behind** has since settled. The
    caller resolves them; this decides.

    Work already under way elsewhere is not work to start again:

    >>> classify("**done when…** it works.", has_open_request=True)
    'blocked'

    An issue queued behind something that has since merged may have been overtaken by
    it, and that is a question for a human:

    >>> classify("**Sequencing:** after #75.", superseded=True)
    'stale'

    No acceptance criterion at all means nobody has said what done looks like:

    >>> classify("Two honest ways out, and the issue is to pick one.")
    'decision'

    A criterion that admits two outcomes is a choice wearing a criterion's clothes:

    >>> classify("**done when…** either it is split or the decision is recorded.")
    'optional'

    And the case the command exists for:

    >>> classify("**done when…** `make test` runs without the warning.")
    'mechanical'

    Note what is deliberately **not** here. An issue that *mentions* a template-owned
    file, or one whose backticked prose names a path that does not resolve, is not
    demoted on that evidence: #95 quotes `pytest.ini` to explain why the table in
    `pyproject.toml` is dead, and #94 names a dozen paths while describing what a
    document got wrong about them. Mentioning a file is not editing it, and inferring
    the target of a fix from the nouns in its prose is precisely the guessing this
    command exists not to do. Both are reported by :func:`signals` as cautions for the
    verification step — which reads the issue properly — to weigh.
    """
    if has_open_request:
        return "blocked"
    if superseded:
        return "stale"
    criterion = acceptance(body)
    if criterion is None or decide_markers(body):
        return "decision"
    if is_disjunctive(criterion):
        return "optional"
    return "mechanical"


def signals(
    body: str,
    *,
    template_owned: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    open_requests: tuple[int, ...] = (),
    superseded_by: tuple[int, ...] = (),
) -> dict[str, Any]:
    """Every derived fact about *body*, plus the category they add up to.

    One call so a caller cannot read half the signals and reach its own verdict.

    >>> report = signals("**Subcategory:** x\\n\\n**done when…** the warning is gone.")
    >>> report["category"], report["quality_filed"]
    ('mechanical', True)

    ``template_owned`` and ``missing`` are carried into the report but never into the
    category — see :func:`classify` for why a mention is not a target:

    >>> signals("fix it", template_owned=("pytest.ini",))["cautions"]
    ['mentions template-owned paths: pytest.ini']
    """
    criterion = acceptance(body)
    cautions: list[str] = []
    if template_owned:
        cautions.append(f"mentions template-owned paths: {', '.join(template_owned)}")
    if missing:
        cautions.append(f"names paths that do not resolve: {', '.join(missing)}")
    return {
        "acceptance": criterion,
        "acceptance_disjunctive": criterion is not None and is_disjunctive(criterion),
        "quality_filed": quality_filed(body),
        "decide_markers": decide_markers(body),
        "paths": paths(body),
        "missing_paths": list(missing),
        "template_owned": list(template_owned),
        "cautions": cautions,
        "references": references(body),
        "dependencies": dependencies(body),
        "open_requests": list(open_requests),
        "superseded_by": list(superseded_by),
        "category": classify(
            body,
            has_open_request=bool(open_requests),
            superseded=bool(superseded_by),
        ),
    }
