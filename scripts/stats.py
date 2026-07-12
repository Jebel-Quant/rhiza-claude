#!/usr/bin/env python3
"""Read-only statistics dashboard for a rhiza-managed repo — no agent, no tokens.

This is the implementation behind the `/rhiza:stats` slash command, which is a
thin wrapper that just runs this script and relays its output. It can also be run
directly — no agent, no tokens. It gathers the numbers (LOC, tests, coverage,
complexity, deps, git activity, rhiza template status), prints a terminal
dashboard, and writes a self-contained `docs/stats.html` you can wire into
`mkdocs.yml`.

Usage:
  python3 scripts/stats.py [PATH] [--slow] [--no-html] [--html-out docs/stats.html]

  PATH        optional path/pathspec to scope code-size metrics to (default: whole repo)
  --slow      permit slow/networked fallbacks (uvx radon/interrogate, uv pip --outdated)
  --no-html   skip writing the HTML artifact (terminal only)
  --html-out  where to write the HTML (default: docs/stats.html under the repo root)

By design it counts and measures, it does NOT score, fix, or
file anything (that's `/quality`'s job). The lone artifact it writes is the HTML
dashboard. Missing tools degrade to "n/a (<reason>)" rather than failing the run.
Tracked files (`git ls-files`) are the file list — never `find .` — so
git-ignored runtime state can't inflate the counts.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

try:  # py3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore

SLOW = False


# --------------------------------------------------------------------------- #
# shell helpers
# --------------------------------------------------------------------------- #
def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess | None:
    """Run a command, returning the CompletedProcess or None if the binary is absent."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def out(cmd: list[str], timeout: int = 60) -> str | None:
    """stdout (stripped) of a successful command, else None."""
    p = run(cmd, timeout=timeout)
    if p is None or p.returncode != 0:
        return None
    return p.stdout.strip()


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def tool(name: str) -> list[str] | None:
    """Resolve a tool to a runnable command: local binary, else `uvx <name>` under --slow."""
    if have(name):
        return [name]
    if SLOW and have("uvx"):
        return ["uvx", name]
    return None


def na(reason: str) -> str:
    return f"n/a ({reason})"


def count_lines(path: Path) -> int:
    try:
        n = 0
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                n += chunk.count(b"\n")
        return n
    except OSError:
        return 0


def ls_files(pathspec: str | None = None) -> list[str]:
    cmd = ["git", "ls-files"]
    if pathspec:
        cmd += ["--", pathspec]
    res = out(cmd)
    return res.splitlines() if res else []


# --------------------------------------------------------------------------- #
# section model + rendering
# --------------------------------------------------------------------------- #
class Section:
    def __init__(self, title: str) -> None:
        self.title = title
        self.rows: list[tuple[str, object]] = []
        self.tables: list[dict] = []

    def row(self, label: str, value: object) -> None:
        self.rows.append((label, value))

    def table(self, caption: str, headers: list[str], rows: list[list[object]]) -> None:
        self.tables.append({"caption": caption, "headers": headers, "rows": rows})


# --------------------------------------------------------------------------- #
# TOML / config readers
# --------------------------------------------------------------------------- #
def read_toml(path: Path) -> dict | None:
    if tomllib is None or not path.exists():
        return None
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 1. repo identity
# --------------------------------------------------------------------------- #
def parse_remote(url: str) -> tuple[str, str]:
    """Return (platform, owner/repo) from a git remote URL."""
    u = url.strip()
    if u.endswith(".git"):
        u = u[:-4]
    host = ""
    path = ""
    m = re.match(r"git@([^:]+):(.+)", u)
    if m:
        host, path = m.group(1), m.group(2)
    else:
        m = re.match(r"[a-zA-Z]+://(?:[^@]+@)?([^/]+)/(.+)", u)
        if m:
            host, path = m.group(1), m.group(2)
    if "github.com" in host:
        platform = "GitHub"
    elif "gitlab" in host:
        platform = "GitLab"
    else:
        platform = host or "unknown"
    return platform, path


def default_branch() -> str:
    db = out(["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"])
    if db:
        return db
    ref = out(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    if ref:
        return ref.rsplit("/", 1)[-1]
    return "main"


def section_identity(root: Path, scope: str | None) -> tuple[Section, dict]:
    s = Section("Repo identity")
    ctx: dict = {}
    branch = out(["git", "branch", "--show-current"]) or "(detached)"
    db = default_branch()
    ctx["branch"], ctx["default_branch"] = branch, db
    s.row("Root", str(root))
    s.row("Branch", branch)
    s.row("Default branch", db)

    remote = out(["git", "remote", "get-url", "origin"])
    if remote:
        platform, slug = parse_remote(remote)
        ctx["platform"], ctx["slug"] = platform, slug
        s.row("Platform", f"{platform} — {slug}")
    else:
        ctx["platform"], ctx["slug"] = None, None
        s.row("Platform", na("no remote"))

    pyproject = read_toml(root / "pyproject.toml")
    if pyproject:
        proj = pyproject.get("project", {})
        ctx["pyproject"] = pyproject
        s.row("Project", f"Python — {proj.get('name', '?')} {proj.get('version', '')}".strip())
        s.row("Requires-Python", proj.get("requires-python", na("unset")))
    else:
        exts = [f.rsplit(".", 1)[-1] for f in ls_files() if "." in f]
        top = max(set(exts), key=exts.count) if exts else "?"
        s.row("Project", f"non-Python (dominant .{top})")
        ctx["pyproject"] = None

    s.row("License", detect_license(root, ctx.get("pyproject")))

    tracked = out(["bash", "-c", "git ls-files | xargs du -ch 2>/dev/null | tail -1 | cut -f1"])
    gitdir = out(["du", "-sh", str(root / ".git")])
    s.row("Tracked-tree size", tracked or na("du unavailable"))
    s.row("`.git` size", gitdir.split()[0] if gitdir else na("du unavailable"))

    # host social stats
    if ctx.get("platform") == "GitHub":
        raw = out(
            [
                "gh",
                "repo",
                "view",
                "--json",
                "stargazerCount,forkCount,isArchived,createdAt,pushedAt,diskUsage",
            ]
        )
        if raw:
            try:
                d = json.loads(raw)
                subs = out(["gh", "api", f"repos/{ctx['slug']}", "--jq", ".subscribers_count"])
                s.row("Stars", d.get("stargazerCount"))
                s.row("Forks", d.get("forkCount"))
                s.row("Watchers", subs or na("unavailable"))
                s.row("Archived", d.get("isArchived"))
                ctx["stars"] = d.get("stargazerCount")
            except ValueError:
                s.row("Host stats", na("gh json parse failed"))
        else:
            s.row("Host stats", na("gh unavailable/unauthenticated"))
    elif ctx.get("platform") == "GitLab":
        jq = "{stars: .star_count, forks: .forks_count}"
        raw = out(["glab", "api", "projects/:id", "--jq", jq])
        if raw:
            try:
                d = json.loads(raw)
                s.row("Stars", d.get("stars"))
                s.row("Forks", d.get("forks"))
                ctx["stars"] = d.get("stars")
            except ValueError:
                s.row("Host stats", na("glab json parse failed"))
        else:
            s.row("Host stats", na("glab unavailable/unauthenticated"))
    return s, ctx


def detect_license(root: Path, pyproject: dict | None) -> str:
    if pyproject:
        lic = pyproject.get("project", {}).get("license")
        if isinstance(lic, str):
            return lic
        if isinstance(lic, dict) and lic.get("text"):
            return lic["text"]
    lf = root / "LICENSE"
    if lf.exists():
        head = lf.read_text(errors="ignore").splitlines()[:2]
        return head[0].strip() if head else "present"
    return na("no LICENSE / pyproject license")


# --------------------------------------------------------------------------- #
# 2. code size & language mix
# --------------------------------------------------------------------------- #
def section_code_size(root: Path, scope: str | None) -> tuple[Section, dict]:
    s = Section("Code size & language mix")
    ctx: dict = {}
    files = ls_files(scope)

    ext_counts: dict[str, int] = {}
    for f in files:
        ext = f.rsplit(".", 1)[-1] if "." in f else "(none)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
    top_ext = sorted(ext_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    s.table("Extension mix (file counts)", ["ext", "files"], [[e, n] for e, n in top_ext])

    # code/comment/blank split only if scc/tokei already on PATH
    split = language_split(scope)
    if split:
        val = f"{split['code']} / {split['comment']} / {split['blank']} ({split['tool']})"
        s.row("Code / comment / blank", val)
    else:
        s.row("Code / comment / blank", na("scc/tokei not on PATH — raw line counts only"))

    def loc_of(pathspec: str) -> int:
        return sum(count_lines(root / f) for f in ls_files(pathspec))

    src_dir = "src" if ls_files("src") else None
    src_loc = loc_of("src") if src_dir else None
    test_loc = loc_of("tests") if ls_files("tests") else None
    total_loc = sum(count_lines(root / f) for f in files)
    ctx["src_loc"], ctx["test_loc"], ctx["total_loc"] = src_loc, test_loc, total_loc

    s.row("Source LOC", src_loc if src_loc is not None else na("no src/ tree"))
    s.row("Test LOC", test_loc if test_loc is not None else na("no tests/ tree"))
    s.row("Total tracked LOC", total_loc)
    if src_loc and test_loc:
        ratio = test_loc / src_loc
        s.row("Test-to-code ratio", f"{ratio:.2f}:1 ({ratio * 100:.0f}%)")
        ctx["ratio"] = f"{ratio:.2f}:1"
    else:
        s.row("Test-to-code ratio", na("needs both src/ and tests/"))
        ctx["ratio"] = None

    for label, dirspec in (("src/", "src"), ("tests/", "tests"), ("docs/", "docs")):
        n = len(ls_files(dirspec))
        if n:
            s.row(f"Files in {label}", n)

    if src_dir:
        py = [root / f for f in ls_files("src") if f.endswith(".py")]
        classes = defs = 0
        for p in py:
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            classes += len(re.findall(r"^\s*class ", txt, re.M))
            defs += len(re.findall(r"^\s*(?:async\s+)?def ", txt, re.M))
        s.row("Definitions (src)", f"{len(py)} modules, {classes} classes, {defs} functions")

    markers = out(["git", "grep", "-I", "-nE", "TODO|FIXME|XXX|HACK"])
    marker_n = len(markers.splitlines()) if markers else 0
    s.row("TODO/FIXME markers", marker_n)

    sized = sorted(((count_lines(root / f), f) for f in files), reverse=True)[:10]
    s.table("Largest files (by line count)", ["lines", "file"], [[n, f] for n, f in sized])
    return s, ctx


def language_split(scope: str | None) -> dict | None:
    target = scope or "."
    if have("scc"):
        raw = out(["scc", "--format", "json", target])
        if raw:
            try:
                langs = json.loads(raw)
                return {
                    "tool": "scc",
                    "code": sum(x.get("Code", 0) for x in langs),
                    "comment": sum(x.get("Comment", 0) for x in langs),
                    "blank": sum(x.get("Blank", 0) for x in langs),
                }
            except ValueError:
                return None
    if have("tokei"):
        raw = out(["tokei", "--output", "json", target])
        if raw:
            try:
                data = json.loads(raw)
                tot = data.get("Total", {})
                return {
                    "tool": "tokei",
                    "code": tot.get("code", 0),
                    "comment": tot.get("comments", 0),
                    "blank": tot.get("blanks", 0),
                }
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------- #
# 3. tests & coverage
# --------------------------------------------------------------------------- #
def section_tests(root: Path) -> Section:
    s = Section("Tests & coverage")
    if ls_files("tests"):
        test_files = [f for f in ls_files("tests") if re.search(r"test_.*\.py$", f)]
        count = 0
        for f in test_files:
            try:
                txt = (root / f).read_text(errors="ignore")
                count += len(re.findall(r"^\s*(?:async\s+)?def test_", txt, re.M))
            except OSError:
                pass
        s.row("Tests", f"{count} test functions in {len(test_files)} files")
    else:
        s.row("Tests", na("no tests/ dir"))

    # threshold from pyproject [tool.coverage.report].fail_under
    pyproject = read_toml(root / "pyproject.toml")
    fail_under = None
    if pyproject:
        cov_cfg = pyproject.get("tool", {}).get("coverage", {}).get("report", {})
        fail_under = cov_cfg.get("fail_under")
    thr = fail_under if fail_under is not None else na("no fail_under in pyproject")
    s.row("Coverage threshold", thr)

    cov_xml = root / "coverage.xml"
    if cov_xml.exists():
        m = re.search(r'line-rate="([0-9.]+)"', cov_xml.read_text(errors="ignore"))
        cov = f"{float(m.group(1)) * 100:.1f}%" if m else na("coverage.xml unparsed")
        s.row("Coverage (cached)", cov)
    else:
        s.row("Coverage (cached)", na("no coverage.xml (not re-running suite)"))

    interp = tool("interrogate")
    if interp:
        raw = out([*interp, "-q", "src"]) if ls_files("src") else None
        m = re.search(r"actual:\s*([0-9.]+)%", raw) if raw else None
        s.row("Docstring coverage", f"{m.group(1)}%" if m else na("interrogate produced no number"))
    else:
        s.row("Docstring coverage", na("interrogate not on PATH (use --slow for uvx)"))
    return s


# --------------------------------------------------------------------------- #
# 4. complexity (Python)
# --------------------------------------------------------------------------- #
def section_complexity() -> Section:
    s = Section("Complexity (Python)")
    if not ls_files("src"):
        s.row("Complexity", na("no src/ tree"))
        return s
    radon = tool("radon")
    if not radon:
        s.row("Complexity", na("radon not on PATH (use --slow for uvx)"))
        return s
    cc = out([*radon, "cc", "src", "-a", "-s"])
    if cc:
        m = re.search(r"Average complexity:\s*([A-F])\s*\(([0-9.]+)\)", cc)
        worse = re.findall(r"^\s+\S+ \d+:\d+ .+ - ([C-F]) \(", cc, re.M)
        avg = f"{m.group(1)} ({m.group(2)})" if m else na("radon cc unparsed")
        s.row("Avg cyclomatic complexity", avg)
        s.row("Blocks rated C or worse", len(worse))
    else:
        s.row("Cyclomatic complexity", na("radon cc failed"))
    mi = out([*radon, "mi", "src", "-s"])
    if mi:
        below_a = len(re.findall(r"- [B-F] \(", mi))
        s.row("Modules below MI rank A", below_a)
    return s


# --------------------------------------------------------------------------- #
# 5. dependencies
# --------------------------------------------------------------------------- #
def section_deps(root: Path) -> Section:
    s = Section("Dependencies")
    pyproject = read_toml(root / "pyproject.toml")
    if not pyproject:
        s.row("Dependencies", na("no pyproject.toml"))
        return s
    proj = pyproject.get("project", {})
    runtime = proj.get("dependencies", []) or []
    optional = proj.get("optional-dependencies", {}) or {}
    groups = pyproject.get("dependency-groups", {}) or {}
    opt_count = sum(len(v) for v in optional.values()) + sum(len(v) for v in groups.values())
    s.row("Runtime deps", len(runtime))
    s.row("Optional/dev deps", opt_count)
    s.row("Requires-Python", proj.get("requires-python", na("unset")))

    lock = root / "uv.lock"
    if lock.exists():
        s.row("Locked packages", lock.read_text(errors="ignore").count("[[package]]"))
    else:
        reqs = list(root.glob("requirements*.txt"))
        if reqs:
            n = sum(
                1
                for line in reqs[0].read_text(errors="ignore").splitlines()
                if line.strip() and not line.startswith("#")
            )
            s.row("Pinned packages", f"{n} ({reqs[0].name})")

    if SLOW:
        cmd = ["uv", "pip", "list", "--outdated"] if have("uv") else ["pip", "list", "--outdated"]
        res = out(cmd, timeout=120)
        if res:
            lines = [ln for ln in res.splitlines() if ln.strip()]
            s.row("Outdated deps", max(0, len(lines) - 2))  # minus header rows
    return s


# --------------------------------------------------------------------------- #
# 6. git activity
# --------------------------------------------------------------------------- #
def section_git(ctx: dict) -> tuple[Section, dict]:
    s = Section("Git activity")
    gc: dict = {}
    total = out(["git", "rev-list", "--count", "HEAD"])
    d30 = out(["git", "rev-list", "--count", "--since=30 days ago", "HEAD"])
    d90 = out(["git", "rev-list", "--count", "--since=90 days ago", "HEAD"])
    gc["commits"], gc["d90"] = total, d90
    s.row("Commits", f"{total} total  (30d: {d30}, 90d: {d90})")

    shortlog = out(["git", "shortlog", "-sn", "--no-merges", "HEAD"])
    if shortlog:
        lines = shortlog.splitlines()
        gc["contributors"] = len(lines)
        s.row("Contributors", len(lines))
        top = []
        for ln in lines[:5]:
            m = re.match(r"\s*(\d+)\s+(.+)", ln)
            if m:
                top.append([m.group(1), m.group(2)])
        s.table("Top contributors", ["commits", "author"], top)

    dates = out(["git", "--no-pager", "log", "--format=%as"])
    if dates:
        parts = dates.splitlines()
        first, last = parts[-1], parts[0]
        try:
            age_days = (date.today() - date.fromisoformat(first)).days
            s.row("Age", f"{age_days} days (first commit {first})")
        except ValueError:
            s.row("First commit", first)
        s.row("Last commit", last)

    db = ctx.get("default_branch", "main")
    ahead = out(["git", "rev-list", "--count", f"origin/{db}..HEAD"]) or out(
        ["git", "rev-list", "--count", f"{db}..HEAD"]
    )
    if ahead is not None:
        s.row(f"Ahead of {db}", ahead)

    tags = out(["git", "tag"])
    s.row("Tags", len(tags.splitlines()) if tags else 0)

    if ctx.get("platform") == "GitHub":
        rel = out(["gh", "release", "list", "-L", "1", "--json", "tagName,publishedAt"])
        latest_rel = na("none / gh unavailable")
        if rel:
            try:
                arr = json.loads(rel)
                if arr:
                    r0 = arr[0]
                    latest_rel = f"{r0.get('tagName', '?')} ({r0.get('publishedAt', '')[:10]})"
                else:
                    latest_rel = "none"
            except ValueError:
                pass
        s.row("Latest release", latest_rel)
        prs = out(["gh", "pr", "list", "--state", "open", "--json", "number", "--jq", "length"])
        gc["open_prs"] = prs
        s.row("Open PRs", prs if prs is not None else na("gh unavailable"))
        run_info = out(
            ["gh", "run", "list", "-L", "1", "--json", "conclusion,name", "--jq", ".[0].conclusion"]
        )
        s.row("Latest CI", run_info if run_info else na("gh unavailable"))
        if ctx.get("slug"):
            oic = out(["gh", "api", f"repos/{ctx['slug']}", "--jq", ".open_issues_count"])
            if oic is not None and prs is not None:
                try:
                    issues_only = int(oic) - int(prs)
                    s.row("Open issues", f"{issues_only} (issues only; {oic} incl. PRs)")
                    gc["open_issues"] = issues_only
                except ValueError:
                    s.row("Open issues", oic)
            elif oic is not None:
                s.row("Open issues", f"{oic} (incl. PRs)")
    elif ctx.get("platform") == "GitLab":
        prs = out(["glab", "mr", "list", "--opened"])
        s.row("Open MRs", len(prs.splitlines()) if prs else na("glab unavailable"))
        oic = out(["glab", "api", "projects/:id", "--jq", ".open_issues_count"])
        s.row("Open issues", oic if oic else na("glab unavailable"))
        gc["open_issues"] = oic

    remote_branches = out(["bash", "-c", "git branch -r | grep -v HEAD | wc -l"])
    gc["branches"] = remote_branches.strip() if remote_branches else None
    s.row("Remote branches", gc["branches"] or na("unknown"))

    churn = out(
        [
            "bash",
            "-c",
            "git log --since=90.days --name-only --pretty=format: | sort | uniq -c "
            "| sort -rn | grep -v '^ *[0-9]* *$' | head",
        ]
    )
    if churn:
        rows = []
        for ln in churn.splitlines()[:8]:
            m = re.match(r"\s*(\d+)\s+(.+)", ln)
            if m:
                rows.append([m.group(1), m.group(2)])
        if rows:
            s.table("Most-changed files (90d)", ["changes", "file"], rows)
    return s, gc


# --------------------------------------------------------------------------- #
# 7. rhiza template status
# --------------------------------------------------------------------------- #
def _rhiza_status_json(root: Path) -> dict | None:
    """Authoritative lock state from `rhiza status --json`, or None if unavailable.

    Prefers the rhiza CLI's own reading of .rhiza/template.lock (accurate sha,
    synced_at, strategy, and the exact template/include lists) over regex-parsing
    the lock here, so this section can't drift from the tool. Returns None when the
    `rhiza` CLI is absent, errors, or emits anything but a JSON object — callers
    then fall back to reading the lock file directly.
    """
    raw = out(["rhiza", "status", str(root), "--json"])
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def section_rhiza(root: Path) -> tuple[Section, dict]:
    s = Section("Rhiza template status")
    rc: dict = {}
    tmpl = root / ".rhiza" / "template.yml"
    if not tmpl.exists():
        s.row("Rhiza", na("not a rhiza-managed repo (.rhiza/template.yml missing)"))
        return s, rc
    text = tmpl.read_text(errors="ignore")

    # Prefer the rhiza CLI's own lock reading; fall back to regex-parsing the files.
    status = _rhiza_status_json(root)

    if status and status.get("ref"):
        ref = str(status["ref"])
    else:
        ref_m = re.search(r"^\s*(?:template-branch|ref)\s*:\s*[\"']?([^\"'\n]+)", text, re.M)
        ref = ref_m.group(1).strip() if ref_m else na("unparsed")
    rc["ref"] = ref
    s.row("Template content version", ref)

    if status:
        if status.get("sha"):
            s.row("Synced commit", str(status["sha"])[:12])
        if status.get("synced_at"):
            s.row("Synced at", str(status["synced_at"]))
        if status.get("strategy"):
            s.row("Sync strategy", str(status["strategy"]))

    ver_file = root / ".rhiza" / ".rhiza-version"
    if ver_file.exists():
        tool_ver = ver_file.read_text(errors="ignore").strip()
    else:
        tool_ver = na("no .rhiza-version")
    s.row("Rhiza tool version", f"{tool_ver} (decoupled from content version)")

    latest = out(
        [
            "gh",
            "release",
            "list",
            "-R",
            "jebel-quant/rhiza",
            "-L",
            "1",
            "--json",
            "tagName",
            "--jq",
            ".[0].tagName",
        ]
    )
    if latest:
        s.row("Latest rhiza release", f"{latest} ({'on latest' if latest == ref else 'behind'})")
    else:
        s.row("Latest rhiza release", na("gh unavailable/unauthenticated"))

    prof_m = re.search(r"profiles\s*:\s*\[([^\]]*)\]", text)
    if not prof_m:
        prof_m = re.search(r"profiles\s*:\s*\n((?:\s*-\s*.+\n?)+)", text)
    if prof_m:
        profiles = re.sub(r"\s+", " ", prof_m.group(1)).strip()
        s.row("Active profiles", profiles)
    else:
        s.row("Active profiles", na("no profiles: key (template lists bundles directly)"))

    if status:
        selection = (status.get("templates") or []) + (status.get("include") or [])
        if selection:
            s.row("Synced from template", ", ".join(str(x) for x in selection))
        s.row("Files synced from template", str(len(status.get("files") or [])))
    else:
        lock = root / ".rhiza" / "template.lock"
        if lock.exists():
            synced_n = len(re.findall(r"^\s*-\s+", lock.read_text(errors="ignore"), re.M))
            s.row("Files synced from template", f"~{synced_n} (rough count from template.lock)")
    return s, rc


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def fmt(value: object) -> str:
    return "—" if value is None else str(value)


def render_terminal(
    headline: list[tuple[str, object]], summary: str, sections: list[Section]
) -> None:
    bold = "\033[1m" if sys.stdout.isatty() else ""
    dim = "\033[2m" if sys.stdout.isatty() else ""
    rst = "\033[0m" if sys.stdout.isatty() else ""
    print(f"\n{bold}=== Repo statistics ==={rst}\n")
    for label, value in headline:
        print(f"  {bold}{fmt(value):<18}{rst} {dim}{label}{rst}")
    print(f"\n  {summary}\n")
    for s in sections:
        print(f"{bold}## {s.title}{rst}")
        for label, value in s.rows:
            print(f"  {label:<28} {fmt(value)}")
        for t in s.tables:
            print(f"  {dim}{t['caption']}{rst}")
            for r in t["rows"]:
                print("    " + "  ".join(fmt(c) for c in r))
        print()


def render_html(
    headline: list[tuple[str, object]],
    summary: str,
    sections: list[Section],
    title: str,
    generated: str,
) -> str:
    e = html.escape

    def tiles() -> str:
        cells = "".join(
            f'<div class="tile"><div class="num">{e(fmt(v))}</div>'
            f'<div class="lbl">{e(label)}</div></div>'
            for label, v in headline
        )
        return f'<div class="tiles">{cells}</div>'

    def section_html(s: Section) -> str:
        rows = "".join(f"<tr><th>{e(label)}</th><td>{e(fmt(v))}</td></tr>" for label, v in s.rows)
        body = f"<table class='kv'>{rows}</table>" if rows else ""
        for t in s.tables:
            head = "".join(f"<th>{e(str(h))}</th>" for h in t["headers"])
            trs = "".join(
                "<tr>" + "".join(f"<td>{e(fmt(c))}</td>" for c in r) + "</tr>" for r in t["rows"]
            )
            body += (
                f"<div class='caption'>{e(t['caption'])}</div>"
                f"<div class='scroll'><table class='data'><thead><tr>{head}</tr></thead>"
                f"<tbody>{trs}</tbody></table></div>"
            )
        return f"<section><h2>{e(s.title)}</h2>{body}</section>"

    sections_html = "".join(section_html(s) for s in sections)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} — stats</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --card: #f6f7f9;
    --border: #e5e7eb; --accent: #11d48e; --th: #f0f1f3;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e; --card: #161b22;
      --border: #30363d; --accent: #11d48e; --th: #1c2128;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    Helvetica, Arial, sans-serif; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
  header h1 {{ margin: 0 0 .25rem; font-size: 1.6rem; }}
  header .meta {{ color: var(--muted); font-size: .9rem; }}
  .summary {{ margin: 1rem 0 1.5rem; padding: .75rem 1rem; background: var(--card);
    border-left: 3px solid var(--accent); border-radius: 4px; font-size: .95rem; }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: .75rem; margin-bottom: 2rem; }}
  .tile {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 1rem; text-align: center; }}
  .tile .num {{ font-size: 1.5rem; font-weight: 700; color: var(--accent); }}
  .tile .lbl {{ color: var(--muted); font-size: .8rem; margin-top: .25rem; }}
  section {{ margin-bottom: 2rem; }}
  h2 {{ font-size: 1.15rem; border-bottom: 1px solid var(--border); padding-bottom: .3rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  table.kv th {{ text-align: left; color: var(--muted); font-weight: 500; width: 240px;
    vertical-align: top; padding: .3rem .5rem; }}
  table.kv td {{ padding: .3rem .5rem; }}
  .caption {{ color: var(--muted); font-size: .85rem; margin: .75rem 0 .25rem; }}
  .scroll {{ overflow-x: auto; }}
  table.data {{ font-size: .9rem; }}
  table.data th, table.data td {{ text-align: left; padding: .35rem .6rem;
    border-bottom: 1px solid var(--border); white-space: nowrap; }}
  table.data thead th {{ background: var(--th); }}
  footer {{ color: var(--muted); font-size: .8rem; margin-top: 3rem;
    border-top: 1px solid var(--border); padding-top: 1rem; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{e(title)}</h1>
    <div class="meta">Generated {e(generated)} · point-in-time snapshot</div>
  </header>
  <div class="summary">{e(summary)}</div>
  {tiles()}
  {sections_html}
  <footer>Generated by <code>scripts/stats.py</code> — descriptive only, no scoring.
    Run <code>/quality</code> for an assessment.</footer>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    global SLOW
    ap = argparse.ArgumentParser(description="Read-only repo statistics dashboard.")
    ap.add_argument(
        "path", nargs="?", default=None, help="path/pathspec to scope code-size metrics to"
    )
    ap.add_argument(
        "--slow", action="store_true", help="permit slow/networked fallbacks (uvx, --outdated)"
    )
    ap.add_argument("--no-html", action="store_true", help="skip writing docs/stats.html")
    ap.add_argument("--html-out", default=None, help="HTML output path (default: docs/stats.html)")
    args = ap.parse_args()
    SLOW = args.slow

    root_str = out(["git", "rev-parse", "--show-toplevel"])
    if not root_str:
        print("error: not inside a git repository", file=sys.stderr)
        sys.exit(1)
    root = Path(root_str)
    os.chdir(root)

    scope = args.path

    id_sec, ctx = section_identity(root, scope)
    code_sec, code_ctx = section_code_size(root, scope)
    tests_sec = section_tests(root)
    cx_sec = section_complexity()
    deps_sec = section_deps(root)
    git_sec, git_ctx = section_git(ctx)
    rhiza_sec, rhiza_ctx = section_rhiza(root)
    sections = [id_sec, code_sec, tests_sec, cx_sec, deps_sec, git_sec, rhiza_sec]

    name = ctx.get("slug") or root.name
    headline: list[tuple[str, object]] = [
        ("Source LOC", code_ctx.get("src_loc") if code_ctx.get("src_loc") is not None else "n/a"),
        ("Test LOC", code_ctx.get("test_loc") if code_ctx.get("test_loc") is not None else "n/a"),
        ("Test:code ratio", code_ctx.get("ratio") or "n/a"),
        ("Stars", ctx.get("stars", "n/a")),
        ("Open issues", git_ctx.get("open_issues", "n/a")),
        ("Branches", git_ctx.get("branches", "n/a")),
        ("Commits", git_ctx.get("commits", "n/a")),
    ]
    stars = ctx.get("stars", "n/a")
    issues = git_ctx.get("open_issues", "n/a")
    branches = git_ctx.get("branches", "n/a")
    summary = (
        f"{name} — {fmt(code_ctx.get('src_loc'))} LOC / "
        f"{fmt(code_ctx.get('test_loc'))} test LOC "
        f"(ratio {code_ctx.get('ratio') or 'n/a'}), {stars}★, "
        f"{issues} open issues, {branches} branches, "
        f"{fmt(git_ctx.get('commits'))} commits, rhiza {rhiza_ctx.get('ref', 'n/a')}"
    )

    render_terminal(headline, summary, sections)

    if not args.no_html:
        generated = out(["date", "+%Y-%m-%d"]) or date.today().isoformat()
        html_doc = render_html(headline, summary, sections, name, generated)
        out_path = Path(args.html_out) if args.html_out else root / "docs" / "stats.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_doc)
        rel = out_path.relative_to(root) if out_path.is_relative_to(root) else out_path
        print(f"Wrote {rel}")
        print("\nWire it into mkdocs.yml nav (this script does NOT edit mkdocs.yml):\n")
        print("  nav:")
        print(f"    - Stats: {rel.name if rel.parent.name == 'docs' else rel}")
        print()


if __name__ == "__main__":
    main()
