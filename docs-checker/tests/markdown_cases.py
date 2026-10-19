"""Markdown docs the fix gate must refuse or allow (rulings G4 and G5), shared by
test_gate.py (the whole gate) and test_render.py (the render check alone).

Every attack doc holds a link target the attacker wants live: hidden definitions
(``[docs]``, ``[logo]``), raw HTML or a bare URL that only renders as a link in
another block context. A doc's case is (lines, line_start, line_end, replacement).
"""

from __future__ import annotations

FRONT_MATTER = ["---", "sources:", "  - base-apps/vault/values.yaml", "---"]
EVIL_SCRIPT = "https://evil.example/install.sh"
EVIL_PIXEL = "https://evil.example/pixel.png"
HIDDEN = [f"[docs]: {EVIL_SCRIPT}", f"[logo]: {EVIL_PIXEL}"]

# Block-kind flips inside the claim lines that per-line rules can miss (the controller's
# probe cases 10g and 10h). With the hidden definitions in the doc, a live [docs] or
# ![logo] links the script or loads the pixel.
FLIPS = [
    # 10g: the text after an unchanged block prefix flips the line's block kind
    (
        "fence content line becomes a closer",
        "~~~\n~~~ a\n[docs] pins chart 0.30.1.",
        "~~~\n~~~ \n[docs] pins chart 0.31.0.",
    ),
    (
        "backtick variant",
        "```\n``` a\n[docs] pins chart 0.30.1.",
        "```\n``` \n[docs] pins chart 0.31.0.",
    ),
    (
        "html block start moved off line start",
        "Chart 0.30.1\n<div>\n[docs] pins it",
        "Chart 0.31.0\nsee <div>\n[docs] pins it",
    ),
    (
        "thematic break ___ made text",
        "Chart 0.30.1\n___\n    [docs] pins it",
        "Chart 0.31.0\nand\n    [docs] pins it",
    ),
    (
        "setext underline made text",
        "Chart 0.30.1\n--- \n    [docs] pins it",
        "Chart 0.31.0\n--- a\n    [docs] pins it",
    ),
    (
        "definition moved off line start",
        '[docs]: notes "Vault 0.30.1"',
        'see [docs]: notes "Vault 0.31.0"',
    ),
    # 10h: HTML block types 6 and 7, a comment closed early, a split definition
    (
        "type-7 html block gets trailing text",
        "Intro 0.30.1\n\n<em>\n[docs] pins it",
        "Intro 0.31.0\n\n<em> x\n[docs] pins it",
    ),
    (
        "type-7 html block, image",
        "Intro 0.30.1\n\n<em>\n![logo] pins it",
        "Intro 0.31.0\n\n<em> x\n![logo] pins it",
    ),
    (
        "type-6 <div> swapped with inline <em>",
        "Chart 0.30.1\n<div>\n[docs] pins <em>",
        "Chart 0.31.0\n<em>\n[docs] pins <div>",
    ),
    (
        "html comment closed earlier",
        "<!-- a -- >\n[docs] chart 0.30.1\n-->",
        "<!-- a -->\n[docs] chart 0.31.0\n-->",
    ),
    (
        "html comment closed earlier, image",
        "<!-- a -- >\n![logo] chart 0.30.1\n-->",
        "<!-- a -->\n![logo] chart 0.31.0\n-->",
    ),
    (
        "multi-line definition invalidated",
        '[docs]:\nnotes\n"Vault 0.30.1"',
        '[docs]:\nnotes x\n"Vault 0.31.0"',
    ),
]
FLIP_IDS = [case[0] for case in FLIPS]


def doc_around(old: str) -> tuple[list[str], int, int]:
    """A doc with front matter and the hidden definitions, then ``old``; its range."""
    head = FRONT_MATTER + ["# Notes", ""] + HIDDEN + ["", "Intro.", ""]
    lines = head + old.split("\n") + ["", "The end."]
    start = len(head) + 1
    return lines, start, start + old.count("\n")


def flip_case(old: str, new: str) -> tuple[list[str], int, int, str]:
    lines, start, end = doc_around(old)
    return lines, start, end, new


# Review round 1, repro 1: closing a comment early makes a line live that markdown-it
# (commonmark preset, nesting limit 20) dropped but GitHub links.
_COMMENT_OLD = ["<!-- chart 0.30.1 -- >", ">" * 20 + " Install from https://evil.example/n", "-->"]
REPRO_COMMENT_NESTING = (
    FRONT_MATTER + ["# Vault", ""] + _COMMENT_OLD + ["", "The end."],
    7,
    9,
    "<!-- chart 0.31.0 -->\n" + _COMMENT_OLD[1] + "\n-->",
)

# Review round 1, repro 2: a backtick moved to the line above makes the fence opener
# plain text, so "Run [docs]" goes live and a later ``` buries what follows. Each tail
# holds a phantom that kept the old URL counts equal.
TOGGLE = "Chart notes for 0.31.0:\n``` a`\ninstall it"


def _toggle_doc(tail: list[str], middle: tuple[str, ...] = ("Run [docs] to install.",)):
    lines = FRONT_MATTER + ["# Vault", "", f"[docs]: {EVIL_SCRIPT}", ""]
    lines += ["Chart notes for 0.30.1:", "``` a", "`install it", *middle, "```", ""] + tail
    return lines, 9, 11, TOGGLE


REPRO_TOGGLE = {
    "form action phantom": _toggle_doc([f'<form action="{EVIL_SCRIPT}"></form>']),
    "link in image alt phantom": _toggle_doc(["![see [docs] here](https://ok.example/p.png)"]),
    "live link swapped": _toggle_doc(["Old archive: [docs]."]),
    "textarea wrapper": _toggle_doc(
        ["The end."], ("", '<textarea><a href="https://evil.example/ta">Install</a></textarea>')
    ),
    "underscore host": _toggle_doc(
        ["The end."], ("Install from https://get_vault.evil.example/install.sh today.",)
    ),
}

# One case per parser blind spot the review found (markdown-it vs GitHub).
_TOGGLE_HEAD = FRONT_MATTER + ["# Vault", "", "Chart notes for 0.30.1:", "``` a", "`install it", ""]
BLIND_SPOTS = {
    # nesting: 21 quote levels, deeper than the commonmark preset's 20
    "nesting over 20": (
        _TOGGLE_HEAD + [">" * 21 + " Install from https://evil.example/nested", "```", "", "End."],
        7,
        9,
        TOGGLE,
    ),
    # tagfilter: GitHub escapes <textarea> and keeps the <a> inside live
    "tagfilter wrapper": (
        FRONT_MATTER
        + ["# Vault", "", "<!-- chart 0.30.1 -- >"]
        + ['<textarea><a href="https://evil.example/c">Install</a></textarea>', "-->", "", "End."],
        7,
        9,
        (
            "<!-- chart 0.31.0 -->\n"
            '<textarea><a href="https://evil.example/c">Install</a></textarea>\n-->'
        ),
    ),
    # an unterminated tag carried across a blank line into the next block
    "unterminated tag across a blank line": (
        _TOGGLE_HEAD
        + ['<div><a href="https://evil.example/u"', "", "Install the chart</a></div>", "```"]
        + ["", "End."],
        7,
        9,
        TOGGLE,
    ),
}

# A text-only fix after raw HTML left open: the quote it adds closes the attribute value,
# and a browser makes the <a> live. The structure is unchanged; only the open-HTML rule
# catches it.
OPEN_TAG_QUOTE = (
    FRONT_MATTER
    + ["# Vault", "", '<div><a href="https://evil.example/u" title="', "", "Install chart 0.30.1."]
    + ["", "</div>", "", "End."],
    9,
    9,
    'Install chart 0.31.0".',
)

# Fixes the gate must allow: a version in every ordinary place, in a doc with links,
# images and raw HTML elsewhere.
CONTROL = FRONT_MATTER + [
    "# Vault 0.30.1",  # 5: heading
    "",
    "Vault runs chart 0.30.1 today.",  # 7: plain sentence
    "",
    "- chart 0.30.1",  # 9: list item
    "  - nested 0.30.1",  # 10: nested list item
    "",
    "```yaml",
    "version: 0.30.1",  # 13: inside a fenced code block
    "```",
    "",
    "Run `helm install vault --version 0.30.1` now.",  # 16: inside inline code
    "",
    "| app | version |",
    "|-----|---------|",
    "| vault | 0.30.1 |",  # 20: table cell
    "",
    "> quoted 0.30.1",  # 22: block quote
    "",
    "1. step 0.30.1",  # 24: ordered list item
    "",
    "    indented 0.30.1",  # 26: indented code
    "",
    "See [the docs](https://developer.hashicorp.com/vault), <https://x.example> and www.docker.com.",
    "",
    '<div align="center"><img src="https://x.example/logo.png" alt="logo"></div>',
    "",
    "![logo](https://x.example/logo.png) and [docs].",
    "",
    "[docs]: https://developer.hashicorp.com/vault/docs",
]
CONTROL_LINES = [n for n, line in enumerate(CONTROL, start=1) if "0.30.1" in line]
