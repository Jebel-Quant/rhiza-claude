#!/usr/bin/env python3
"""Resolve rhiza-sync fallout in a single repo, taking the upstream side.

Repo-agnostic helper extracted from update_rhiza_versions.py so it can run from
any working tree (used by the global /rhiza_boost slash command).

Usage:
  python rhiza_resolve.py [REPO_DIR]   # default: current working directory

For every conflicted/modified file it:
  - replaces `<<<<<<< / ======= / >>>>>>>` conflict blocks with the *theirs*
    (upstream) section, then `git add`s the file;
  - applies any `*.rej` files left by `git apply` / rhiza, taking the upstream
    (`+`) side of each hunk, then removes the `.rej`.

Prints a summary; exits 0 always (resolution is best-effort).
"""

import re
import subprocess
import sys
from pathlib import Path

CONFLICT_START = re.compile(r"^<{7} ")
CONFLICT_SEP = re.compile(r"^={7}$")
CONFLICT_END = re.compile(r"^>{7} ")


def run_soft(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def resolve_conflict_markers(text: str) -> tuple[str, int]:
    """Replace conflict blocks with the 'theirs' (upstream) section."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    conflicts = 0
    i = 0
    while i < len(lines):
        if CONFLICT_START.match(lines[i]):
            conflicts += 1
            i += 1  # skip ours section
            while i < len(lines) and not CONFLICT_SEP.match(lines[i].rstrip("\n")):
                i += 1
            i += 1  # skip ======= line
            while i < len(lines) and not CONFLICT_END.match(lines[i]):
                out.append(lines[i])
                i += 1
            i += 1  # skip >>>>>>> line
        else:
            out.append(lines[i])
            i += 1
    return "".join(out), conflicts


def parse_rej_hunks(rej_path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    hunks: list[tuple[str, list[tuple[str, str]]]] = []
    header: str | None = None
    lines: list[tuple[str, str]] = []
    for raw in rej_path.read_text(errors="replace").splitlines():
        if raw.startswith(("diff ", "index ", "--- ", "+++ ")):
            continue
        if raw.startswith("@@"):
            if header is not None:
                hunks.append((header, lines))
            header, lines = raw, []
        elif header is not None:
            if raw.startswith("-"):
                lines.append(("-", raw[1:]))
            elif raw.startswith("+"):
                lines.append(("+", raw[1:]))
            else:
                lines.append((" ", raw[1:] if raw.startswith(" ") else raw))
    if header is not None:
        hunks.append((header, lines))
    return hunks


def apply_hunk(file_lines: list[str], header: str, hunk: list[tuple[str, str]]) -> list[str] | None:
    """Apply one hunk, taking the upstream (+) side. None if unlocatable."""
    before = [t + "\n" for typ, t in hunk if typ in (" ", "-")]
    after = [t + "\n" for typ, t in hunk if typ in (" ", "+")]
    m = re.match(r"@@\s+-(\d+)", header)
    hint = max(0, int(m.group(1)) - 1) if m else 0
    if not before:
        pos = min(hint, len(file_lines))
        return file_lines[:pos] + after + file_lines[pos:]
    n = len(before)
    matches = [i for i in range(len(file_lines) - n + 1) if file_lines[i : i + n] == before]
    if not matches:
        return None
    pos = min(matches, key=lambda i: abs(i - hint))
    return file_lines[:pos] + after + file_lines[pos + n :]


def resolve_rej_files(repo: Path) -> int:
    rej_files = sorted(repo.rglob("*.rej"))
    count = 0
    for rej_file in rej_files:
        target = Path(str(rej_file)[:-4])
        rel = rej_file.relative_to(repo)
        if not target.exists():
            rej_file.unlink(missing_ok=True)
            print(f"  [rej] removed orphan: {rel}")
            count += 1
            continue
        hunks = parse_rej_hunks(rej_file)
        if not hunks:
            rej_file.unlink(missing_ok=True)
            count += 1
            continue
        file_lines = target.read_text(errors="replace").splitlines(keepends=True)
        applied = failed = 0
        for hdr, hunk_lines in hunks:
            result = apply_hunk(file_lines, hdr, hunk_lines)
            if result is not None:
                file_lines = result
                applied += 1
            else:
                failed += 1
        if applied:
            target.write_text("".join(file_lines))
            run_soft(["git", "add", str(target.relative_to(repo))], repo)
        rej_file.unlink(missing_ok=True)
        status = f"{applied} hunk(s) applied"
        if failed:
            status += f", {failed} could not locate (left as-is)"
        print(f"  [rej] {rel}: {status}")
        count += 1
    return count


def resolve_conflicts_in_repo(repo: Path) -> int:
    result = run_soft(["git", "ls-files", "--unmerged", "-z"], repo)
    unmerged_paths: set[Path] = set()
    if result.stdout.strip():
        for entry in result.stdout.split("\0"):
            parts = entry.strip().split("\t", 1)
            if len(parts) == 2:
                unmerged_paths.add(repo / parts[1])

    status = run_soft(["git", "status", "--porcelain", "-z"], repo)
    candidate_paths: set[Path] = set(unmerged_paths)
    for entry in status.stdout.split("\0"):
        if not entry:
            continue
        xy, rel = entry[:2], entry[3:]
        if xy.strip() in ("M", "A", "UU", "AA", "DU", "UD"):
            candidate_paths.add(repo / rel.strip())

    total_conflicts = 0
    for path in sorted(candidate_paths):
        if not path.exists() or path.is_dir():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if "<<<<<<<" not in text:
            continue
        resolved, count = resolve_conflict_markers(text)
        if count:
            path.write_text(resolved)
            run_soft(["git", "add", str(path.relative_to(repo))], repo)
            print(f"  [conflict] resolved {count} block(s) in {path.relative_to(repo)}")
            total_conflicts += count
    return total_conflicts


def main() -> None:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    n_conflicts = resolve_conflicts_in_repo(repo)
    print(f"  [conflict] {n_conflicts} block(s) resolved (took upstream)" if n_conflicts
          else "  [conflict] no conflict markers found")
    n_rej = resolve_rej_files(repo)
    if n_rej:
        print(f"  [rej] {n_rej} .rej file(s) processed")
    else:
        print("  [rej] no .rej files")


if __name__ == "__main__":
    main()
