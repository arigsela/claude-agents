# Spec reference

A spec is one JSON file. The examples in `examples/` use every field below.

## Top level

| Field | Meaning |
|---|---|
| `name` | Lowercase letters, digits and hyphens. Names the output files. Defaults to the file name. |
| `layout` | `lanes`, `flow` or `hub`. |
| `size` | `portrait` (default), `landscape` or `square`. |
| `series` | Optional pill above the title, such as `PART 1 · LIMITS FOR AI AGENTS`. |
| `title` | Two to five words. `*…*` marks the accent words. |
| `accent` | Color of the accent words (default `pink`). |
| `subtitle` | One sentence, at most two lines. |
| `footer` | `[left, right]`, small caps at the bottom. |
| `nodes` | The cards. |
| `lanes` | `lanes` layout only: `{ "id", "label", "color" }`, left to right, up to three. |
| `groups` | `flow` layout only: `{ "id", "label", "color", "contains": [ids] }`. A group can contain other groups. |
| `edges` | Optional. Edges named in steps are created for you; list an edge here to give it a label or route, or to draw an edge no step animates. |
| `steps` | The animation, in order. Without steps the render is a still with no step band. |
| `final` | The takeaway shown in the band after the last step. |
| `finalLabel` | The band label for `final` (default `THE WHOLE FLOW`). |
| `timing` | `{ "step": 1.6, "hold": 3.4 }`: seconds per step, and seconds on the final frame. |
| `card` | `{ "w", "h" }`: card size in pixels, overriding the layout's default. |
| `gap` | `flow` only: `{ "x", "y" }`, the space between cards (defaults 90 and 70). Widen `x` for edge labels. |

## Nodes

| Field | Meaning |
|---|---|
| `id` | Unique. Steps and edges refer to it. |
| `kind` | The role: sets color and default icon (table in `SKILL.md`). |
| `color` | Overrides the kind's color: `amber`, `blue`, `pink`, `teal`, `violet`, `slate`, `green`, `red`, `orange`, `cyan`. |
| `icon` | A built-in icon name (below), or `file:path.svg`. |
| `tag`, `title`, `desc`, `chip` | The card text (rules in `SKILL.md`). Only `title` is required. |
| `badge` | A pill at the right of the tag row, such as `YES #1`. |
| `place` | `banner`: a full-width card across the top of the body. Edges from it drop straight down. |
| `lane`, `row` | `lanes`: which lane, and which row (rows default to the next free one in that lane). Set `row` to line cards up across lanes. |
| `col`, `row` | `flow`: grid cell, from 0. Fractions center a card between cells (`"row": 0.5`). |
| `hub`, `angle` | `hub`: `"hub": true` on the one center card. Spokes go clockwise from the top (from the top-right corner when there are four). `angle` in degrees (0 right, 90 down) overrides. |
| `w`, `h` | This card's size, overriding `card`. |

## Edges

| Field | Meaning |
|---|---|
| `from`, `to` | Node ids. The arrow points at `to`. |
| `label` | One to three words. Wraps at spaces, never inside a word. Placed on the first straight stretch where it clears every card, label and line. |
| `labelAt` | 0 to 1 along the edge: forces the label's position. |
| `color` | Overrides the color, which is otherwise the target's. |
| `route` | `below` or `above`: for an edge running back across other cards, such as a pull request returning to Git. It goes around everything between its ends. |
| `offset` | Distance of a `below`/`above` route from what it goes around (default 30). |

Routing: in `lanes`, edges run down the spine of icons. In `flow`, an edge is straight when the cards share a row or column and has one elbow otherwise. In `hub`, edges are straight lines between the cards.

## Steps

| Field | Meaning |
|---|---|
| `show` | The id (or ids) revealed in this step. |
| `from` | The id (or ids) a dot travels from. The card appears when the dot lands. |
| `flow` | `[[from, to], …]`: dots along edges between cards already shown, with nothing revealed. |
| `pulse` | An id (or ids) whose ring pulses, such as an alert firing again. |
| `text` | The caption: one sentence, at most two lines. |
| `dur` | Seconds for this step, overriding `timing.step`. |

A node that no step shows is visible from the first frame. An edge no step animates is drawn once both of its cards are visible.

## Icons

Built in, line style, white on the role color:

`bell` `robot` `person` `people` `sync` `cube` `cube-check` `check` `x` `shield` `pause` `play` `pr` `git` `repo` `file` `server` `cluster` `layers` `database` `bucket` `function` `queue` `gateway` `split` `route` `network` `globe` `cloud` `lock` `key` `chart` `eye` `search` `chat` `mail` `terminal` `sliders` `clock` `dollar` `warning` `cpu` `flask`

Official icons keep their own colors and sit on a white circle: `"icon": "file:k8s/pod.svg"` looks next to the spec first, then in the skill's `icons/` folder. Use them where readers expect a vendor's icon, such as AWS services in an AWS architecture.

## What the checker flags

| Problem | Fix |
|---|---|
| `text needs Npx of height` | Shorten the text, or raise `card.h` (or the card's `h`). |
| `a word is wider than the card`, `chip … is cut off` | A shorter chip, or a wider card (`card.w`). |
| `X overlaps Y` | Move a card (`row`, `col`, `angle`), widen `gap`, or shorten a label. |
| `edge … runs through X` | Move a card out of the line, or give the edge a `route`. |
| `edge label … covers edge` | A shorter label, a wider `gap.x`, or the detail in a card. |
| `caption is longer than two lines` | One shorter sentence. |
| `the title is wider than the canvas` | Fewer words. |
| `not placed` | The node is missing its `lane`, `col`/`row`, or the hub. |
