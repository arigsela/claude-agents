---
name: blog-diagrams
version: 0.1.0
description: Use when a blog post, Medium article or LinkedIn post needs a diagram — an architecture, AWS or Kubernetes diagram, a request, alert or approval flow, swimlanes, hub-and-spoke — or an animated GIF or MP4 that walks through it step by step. Not for hero art or illustrated infographics, which go to Codex image generation.
---

# blog-diagrams

Diagrams for the owner's posts are code. A JSON spec is drawn by one engine in one house look, checked for fit, and rendered by headless Chrome into a 2x PNG, a GIF and an MP4. Text comes out exactly as written, so labels need no letter-by-letter check.

## Pick a layout

| Layout | Draws | Start from |
|---|---|---|
| `lanes` | Parallel paths down the page, each a spine of steps: two approvals, before and after | `two-approvals.json` |
| `flow` | An architecture or pipeline on a grid, with groups such as a cluster, VPC or namespace | `alert-paths.json` |
| `hub` | One component and everything it talks to | `dispatcher-hub.json` |

Sizes: `portrait` (1080×1350, 4:5) is the default and fills a LinkedIn feed. `landscape` (1600×900) sits better inside a Medium article. `square` is 1080×1080. One spec renders one size: for both a post and an article, copy the spec, change `size` and `name`, and fix what the checker flags.

## Steps

The engine, script and examples sit next to this file; `<base>` below is this skill's directory.

1. **Facts.** List every label the diagram will carry: titles, descriptions, chips, edge labels, step captions and the final line. Each comes from the post or the owner's notes, so the diagram claims nothing the post doesn't. A title, footer or linking caption the sources don't contain restates them, and goes on a list of wording to confirm. Done when every label has a source sentence or is on that list.
2. **Spec.** Copy the closest example from `<base>/examples/` to `<post>/diagrams/<name>.json` and edit it. Read `<base>/references/spec.md` before the first spec in a session: it has every field, kind, icon and routing rule. Done when every node has a `kind`, and each step reveals one thing and says one sentence.
3. **Still.** Render and check:
   ```bash
   node <base>/scripts/render.mjs <post>/diagrams/<name>.json --out <post>/images --still
   ```
   Fix every problem it lists and run again. Then Read the PNG. The checker sees overflow and overlap; you check meaning: arrows point the way things move, groups hold what they claim, and each card reads right on its own. Done when it prints `0 problems` and the PNG reads right.
4. **Animate.** Run the same command without `--still`. Read `<post>/diagrams/<name>-steps.png`: one panel per step, then the final frame. Done when each panel's caption matches what lit up in it.
5. **Hand off.** Give the paths and sizes the script printed, and the wording to confirm. For a post, add a section to its `images.md` like the others: `File:`, `Alt text:` (what the finished diagram shows), `Caption:`, and the line "Not generated: rendered with blog-diagrams from `diagrams/<name>.json`."

Where each file goes:
- **Medium:** the GIF in the article (Medium plays GIFs), or the PNG for a still.
- **LinkedIn:** the MP4 as a native video post, or the GIF or PNG as the image.
- The HTML page and the step sheet stay in `diagrams/`. The HTML plays the animation in a browser.

## House look

Color is role. A node's `kind` sets its color and default icon, so a role looks the same in every post:

| Kind | Color | For |
|---|---|---|
| `alert` | amber | an alert, an incident, a trigger |
| `agent` | blue | an AI agent |
| `human` | pink, outlined | the owner, a reviewer: every human yes |
| `git` | teal | a repository, a pull request, Argo CD |
| `control` | violet | a dispatcher, a gateway, a policy, a check |
| `workload` | slate | a pod, a VM, a service |
| `ok` | green | the healthy end state |
| `refused` | red | a refusal, a blocked path |
| `cloud` | orange | an AWS or cloud service |
| `data` | cyan | a database, a bucket, a queue |
| `external` | slate | the internet, a third party |

Card text:
- `tag`: who or what, in two or three words (Implementer, Argo CD, Me).
- `title`: what happens, five words or fewer, starting with a verb where it can.
- `desc`: one short sentence.
- `chip`: a literal value in code font (`verdict: rollout-pending`, `k8s_delete_resource`).

Steps: each one reveals one card and says one sentence. Six to ten steps, then `final`, the takeaway in one line. The title is two to five words, with the key words wrapped in `*…*` for the accent color.

## Common mistakes

| Looks like | Do instead |
|---|---|
| Hand-written HTML or SVG for a new diagram | A spec: the engine keeps one look and the checker covers it |
| `--force` past a problem | Shorten the text, raise `card.w` or `gap.x`, or move an edge label into a card's `desc` |
| A long edge label in a narrow gap | One to three words, or the detail in the card |
| Every fact from the post on the canvas | The flow's steps only; details stay in the post |
| A new icon drawn inline | A built-in icon name, or `"icon": "file:…"` with an official SVG |
| An edit to the GIF or PNG | Edit the spec and render again |
