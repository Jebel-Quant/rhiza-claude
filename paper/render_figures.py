#!/usr/bin/env python3
"""Render the paper's terminal figures to paper/images/*.png.

Run with:  uv run --with pillow python paper/render_figures.py

Every transcript below is REAL OUTPUT, captured verbatim from the plugin's own
stdlib-only scripts on 2026-07-29 (plugin v0.6.1, template v1.2.1). The command
that produced each one is recorded in its `source` field — re-run that command to
verify or refresh the figure. Long absolute paths are elided as `…/my-lib`; the
`…` marker on its own line means entries were dropped to fit the page. Nothing else is
edited: no invented output, no idealised formatting.

paper/images/plugin.png is the one asset not generated from a transcript — it is a
real screenshot of a Claude Code session, supplied by hand. This script does crop it
to paper/images/plugin-cropped.png (the region the paper actually cites), so every
file in images/ except plugin.png itself is reproducible by running this script.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- appearance ------------------------------------------------------------
# Colours match the LaTeX preamble: shell 245,245,242 / slate 70,78,86 /
# leaf 31,105,68. Figures and prose should not disagree about the palette.

SCALE = 3  # supersample factor; the PDF includes these at 1/SCALE size

BG = (245, 245, 242)
TITLEBAR = (233, 233, 228)
BORDER = (201, 204, 209)
TITLE_FG = (110, 118, 128)
SLATE = (70, 78, 86)
LEAF = (31, 105, 68)
BODY = (32, 34, 38)
DIM = (138, 144, 153)
WARN = (166, 106, 20)

FONT_REGULAR = "/System/Library/Fonts/Menlo.ttc"
FONT_INDEX_REGULAR = 0
FONT_INDEX_BOLD = 1

FONT_SIZE = 13 * SCALE
LINE_HEIGHT = int(FONT_SIZE * 1.55)
PAD_X = 14 * SCALE
PAD_Y = 11 * SCALE
TITLEBAR_H = 26 * SCALE
RADIUS = 7 * SCALE

# --- line styles -----------------------------------------------------------
# Each transcript line is a (style, text) pair.
#
#   prompt  what the user typed        → leaf, bold, with a `$` gutter
#   kv      "Label    : value"         → label slate, value body
#   ok      a `✓` line                 → tick leaf, rest body
#   warn    a `!` line                 → amber
#   out     plain output               → body
#   tree    a file-tree line           → tree glyphs dim, names body
#   dim     elision markers, comments  → dim


def _fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    regular = ImageFont.truetype(FONT_REGULAR, FONT_SIZE, index=FONT_INDEX_REGULAR)
    bold = ImageFont.truetype(FONT_REGULAR, FONT_SIZE, index=FONT_INDEX_BOLD)
    return regular, bold


def _draw_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    style: str,
    text: str,
    regular: ImageFont.FreeTypeFont,
    bold: ImageFont.FreeTypeFont,
) -> None:
    x, y = xy
    advance = regular.getlength(" ")

    if style == "prompt":
        draw.text((x, y), "$", font=bold, fill=DIM)
        draw.text((x + int(advance * 2), y), text, font=bold, fill=LEAF)
        return

    if style == "kv" and ":" in text:
        label, _, value = text.partition(":")
        draw.text((x, y), label + ":", font=regular, fill=SLATE)
        draw.text((x + regular.getlength(label + ":"), y), value, font=regular, fill=BODY)
        return

    if style == "ok" and text.startswith("✓"):
        draw.text((x, y), "✓", font=bold, fill=LEAF)
        draw.text((x + int(advance * 2), y), text[1:].lstrip(), font=regular, fill=BODY)
        return

    if style == "warn":
        draw.text((x, y), text, font=regular, fill=WARN)
        return

    if style == "tree":
        glyphs = "│├└─ "
        split = len(text) - len(text.lstrip(glyphs))
        draw.text((x, y), text[:split], font=regular, fill=DIM)
        draw.text((x + regular.getlength(text[:split]), y), text[split:], font=regular, fill=BODY)
        return

    if style == "dim":
        draw.text((x, y), text, font=regular, fill=DIM)
        return

    draw.text((x, y), text, font=regular, fill=BODY)


def render(title: str, lines: list[tuple[str, str]], out_path: Path) -> None:
    regular, bold = _fonts()

    widest = max(
        (regular.getlength(text) for _, text in lines),
        default=0.0,
    )
    widest = max(widest, bold.getlength(title) + 60 * SCALE)
    width = int(widest) + PAD_X * 2 + int(regular.getlength("  "))
    height = TITLEBAR_H + PAD_Y * 2 + LINE_HEIGHT * len(lines)

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)], radius=RADIUS, fill=BG, outline=BORDER, width=SCALE
    )
    # Title bar: rounded at the top, square where it meets the body.
    draw.rounded_rectangle([(0, 0), (width - 1, TITLEBAR_H + RADIUS)], radius=RADIUS, fill=TITLEBAR)
    draw.rectangle([(0, TITLEBAR_H - SCALE), (width - 1, TITLEBAR_H)], fill=BORDER)
    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)], radius=RADIUS, outline=BORDER, width=SCALE
    )

    for i, dot in enumerate(((237, 106, 94), (245, 191, 79), (98, 197, 84))):
        cx = PAD_X + i * 15 * SCALE
        cy = TITLEBAR_H // 2
        r = 5 * SCALE // 2
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=dot)

    tw = bold.getlength(title)
    draw.text(
        ((width - tw) / 2, (TITLEBAR_H - FONT_SIZE) / 2 - SCALE), title, font=bold, fill=TITLE_FG
    )

    y = TITLEBAR_H + PAD_Y
    for style, text in lines:
        _draw_line(draw, (PAD_X, y), style, text, regular, bold)
        y += LINE_HEIGHT

    img = img.resize((width // SCALE, height // SCALE), Image.LANCZOS)
    img.save(out_path)
    print(f"wrote {out_path.name}  ({img.width}x{img.height})")


# --- the transcripts -------------------------------------------------------

FIGURES: dict[str, dict] = {
    "fig-init": {
        "title": "/rhiza:init — the pointer, and nothing else",
        # source: init_scaffold.py + init_skeleton.py in an empty `uv init --lib`
        #         repo, then `cat .rhiza/template.yml`, `git status --short`,
        #         `ls .rhiza/`
        "lines": [
            ("prompt", "python3 scripts/init_scaffold.py --host github --language python ."),
            ("out", "created  .rhiza/template.yml"),
            ("out", ""),
            ("prompt", "python3 scripts/init_skeleton.py --owner jebel-quant --repo my-lib ."),
            ("dim", "note     normalised uv's placeholder hello() to a package docstring"),
            (
                "dim",
                "note     seeded the empty README.md uv left behind"
                " — /rhiza:docs owns the real one",
            ),
            ("dim", "note     pyproject.toml: description, project.urls, dependency-groups"),
            ("out", "modified src/my_lib/__init__.py"),
            ("out", "modified README.md"),
            ("out", "modified pyproject.toml"),
            ("out", ""),
            ("prompt", "cat .rhiza/template.yml"),
            ("out", 'repository: "jebel-quant/rhiza"'),
            ("out", 'ref: "main"'),
            ("out", "profiles:"),
            ("out", "  - github-project"),
            ("out", ""),
            ("prompt", "git status --short  &&  ls .rhiza/"),
            ("out", "A  .python-version"),
            ("out", "A  .rhiza/template.yml"),
            ("out", "A  README.md"),
            ("out", "A  pyproject.toml"),
            ("out", "A  src/my_lib/__init__.py"),
            ("out", "A  src/my_lib/py.typed"),
            ("out", "template.yml"),
            ("dim", "# no template.lock, no .github/workflows, no Makefile — by design"),
        ],
    },
    "fig-unsynced": {
        "title": "managed, but never synced — the pointer is valid, the lock is absent",
        # source: validate.py and status.py against the repo left behind by the
        #         init run above (paths elided)
        "lines": [
            ("prompt", "python3 scripts/validate.py …/my-lib"),
            ("dim", "  Validating template configuration in: …/my-lib"),
            ("ok", "✓ Template file exists: .rhiza/template.yml"),
            ("ok", "✓ YAML syntax is valid"),
            ("dim", "  Project language: python"),
            ("ok", "✓ pyproject.toml exists: …/my-lib/pyproject.toml"),
            ("ok", "✓ 'src' folder exists: …/my-lib/src"),
            ("warn", "! Standard 'tests' folder not found: …/my-lib/tests"),
            ("ok", "✓ Using profile mode (profiles: ['github-project'])"),
            ("ok", "✓ repository format is valid: jebel-quant/rhiza"),
            ("ok", "✓ ref is valid: main"),
            ("ok", "✓ Validation passed: template.yml is valid"),
            ("out", ""),
            ("prompt", "python3 scripts/status.py …/my-lib"),
            ("out", "No template.lock found — run /rhiza:update to perform the first sync"),
        ],
    },
    "fig-status": {
        "title": "/rhiza:status --files — both halves, and the managed tree",
        # source: status.py --files against a real synced repo
        #         (jebel-quant/greeks); the tree is truncated at the … markers
        "lines": [
            ("prompt", "python3 scripts/status.py --files ."),
            ("kv", "Repository : github/Jebel-Quant/rhiza"),
            ("kv", "Ref        : v1.2.1"),
            ("kv", "SHA        : e0fe02300840"),
            ("kv", "Synced at  : 2026-07-17T08:10:54Z"),
            ("kv", "Strategy   : merge"),
            ("kv", "Templates  : legal"),
            ("out", ""),
            ("out", "Files managed by Rhiza:"),
            ("tree", "."),
            ("tree", "├── .bandit"),
            ("tree", "├── .editorconfig"),
            ("tree", "├── .github"),
            ("tree", "│   ├── dependabot.yml"),
            ("tree", "│   ├── pull_request_template.md"),
            ("tree", "│   ├── rulesets"),
            ("tree", "│   │   ├── main-branch-protection.json"),
            ("tree", "│   │   └── tag-protection.json"),
            ("tree", "│   └── workflows"),
            ("tree", "│       ├── rhiza_ci.yml"),
            ("tree", "│       ├── rhiza_codeql.yml"),
            ("tree", "│       ├── rhiza_release.yml"),
            ("dim", "│       …"),
            ("tree", "├── .pre-commit-config.yaml"),
            ("tree", "├── .python-version"),
            ("tree", "└── .rhiza"),
            ("tree", "    ├── make.d"),
            ("tree", "    │   ├── quality.mk"),
            ("dim", "    │   …"),
            ("tree", "    └── rhiza.mk"),
        ],
    },
    "fig-check": {
        "title": "/rhiza:status --check — the pin against the latest release",
        # source: status.py --check against the same synced repo (needs network)
        "lines": [
            ("prompt", "python3 scripts/status.py --check ."),
            ("kv", "Repository : github/Jebel-Quant/rhiza"),
            ("kv", "Ref        : v1.2.1"),
            ("kv", "SHA        : e0fe02300840"),
            ("kv", "Synced at  : 2026-07-17T08:10:54Z"),
            ("kv", "Strategy   : merge"),
            ("kv", "Templates  : legal"),
            ("kv", "Update     : v1.2.1 → v1.2.4 (3 releases behind) — run /update"),
        ],
    },
    "fig-release": {
        "title": "/rhiza:release — the legal next versions, with no recommendation",
        # source: check_version_bump.py --current 0.6.1 in this repo
        "lines": [
            ("prompt", "python3 scripts/check_version_bump.py --current 0.6.1"),
            ("kv", "current  : 0.6.1"),
            ("kv", "floor    : v0.6.1"),
            ("kv", "patch    : v0.6.2"),
            ("kv", "minor    : v0.7.0"),
            ("kv", "major    : v1.0.0"),
            ("kv", "ok       : no target given — listing suggestions only"),
        ],
    },
}


# The band of the hand-supplied screenshot the paper cites: from the `plugins` prompt
# down through the contributed-commands line. Everything above it is the Claude Code
# welcome banner and everything below is input chrome — neither is evidence of anything.
PLUGIN_CROP = (117, 585, 2352, 1215)

# The screenshot the crop was measured against. Refuse to touch a differently-sized
# image rather than redact or crop the wrong pixels.
PLUGIN_SIZE = (2470, 1786)

# Redacted before the screenshot is committed: the organisation name in the welcome
# banner, which is not evidence of anything the paper claims. Filled with the panel
# background sampled just left of the region, so the byline simply ends after
# "Claude Team". Applied in place and idempotent — refilling a filled region is a no-op.
PLUGIN_REDACTIONS = ((648, 440, 802, 478),)
PLUGIN_BG_SAMPLE = (300, 460)


def redact_screenshot(images_dir: Path) -> Path | None:
    """Erase PLUGIN_REDACTIONS from plugin.png in place. Returns the path, or None."""
    source = images_dir / "plugin.png"
    if not source.exists():
        print(f"skipped redaction — {source.name} is not present", file=sys.stderr)
        return None
    with Image.open(source) as img:
        rgb = img.convert("RGB")
    if rgb.size != PLUGIN_SIZE:
        print(
            f"skipped redaction — {source.name} is {rgb.size}, expected {PLUGIN_SIZE};"
            " re-measure PLUGIN_REDACTIONS before trusting this script on it",
            file=sys.stderr,
        )
        return None
    fill = rgb.getpixel(PLUGIN_BG_SAMPLE)
    draw = ImageDraw.Draw(rgb)
    for box in PLUGIN_REDACTIONS:
        draw.rectangle(box, fill=fill)
    rgb.save(source)
    print(f"redacted {source.name}  ({len(PLUGIN_REDACTIONS)} region(s), fill {fill})")
    return source


def crop_screenshot(images_dir: Path) -> None:
    source = images_dir / "plugin.png"
    if not source.exists():
        print(f"skipped plugin-cropped.png — {source.name} is not present", file=sys.stderr)
        return
    with Image.open(source) as img:
        if img.size != PLUGIN_SIZE:
            print(
                f"skipped plugin-cropped.png — {source.name} is {img.size},"
                f" expected {PLUGIN_SIZE}; re-measure PLUGIN_CROP",
                file=sys.stderr,
            )
            return
        out_path = images_dir / "plugin-cropped.png"
        img.crop(PLUGIN_CROP).save(out_path)
    print(f"wrote {out_path.name}  (cropped from {source.name})")


def main() -> int:
    out_dir = Path(__file__).resolve().parent / "images"
    out_dir.mkdir(exist_ok=True)
    for name, spec in FIGURES.items():
        render(spec["title"], spec["lines"], out_dir / f"{name}.png")
    redact_screenshot(out_dir)
    crop_screenshot(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
