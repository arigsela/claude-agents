# docs-checker evals

The eval harness runs the audit graph on labelled doc instances, scores the findings and
records what each run cost. It is cheap by construction: every model response is recorded,
so a re-run whose prompts did not change replays from disk for nothing, and every priced run
goes through a $20 spend guard (spec §8).

| Path | What | In git |
|---|---|---|
| `instances.json` | The instances and named sets (Task 17) | yes |
| `labels/*.json` | Labelled lines, one JSON list per file (Task 17) | yes |
| `cassettes/` | Recorded model responses, one file per request key | yes |
| `results.jsonl` | One record per run and per arm, appended | yes |
| `results.md` | The same records as a table, between its markers; prose outside them is kept | yes |
| `cassettes-raw/` | Scratch | no |

The spend ledger and the one-harness lock are not here: they live at one per-user path,
`~/.cache/docs-checker/spend.json` (and `spend.lock`), whatever checkout or `--evals-dir`
a harness runs from (`DOCS_CHECKER_SPEND_LEDGER` moves them; it exists for tests).

## Running

Run from `docs-checker/`. The harness needs a local clone of `arigsela/kubernetes`
(`--clone`, default `$DOCS_CHECKER_EVAL_CLONE` or `~/git/kubernetes`) that has every
instance's commit.

```bash
# Free: every response from the cassettes. A request with no recording stops the run.
.venv/bin/python -m docs_checker.evals run --instances lever --levers none --arm baseline

# Zero cost: what a priced run of these instances would spend, against the cap.
.venv/bin/python -m docs_checker.evals run --instances lever --levers none --dry-run

# Priced: requests with no recording go to the API and are recorded.
DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY=... \
  .venv/bin/python -m docs_checker.evals run --instances lever --levers none \
  --mode record-missing --arm baseline

# The short-circuit lever: run 2 reads the memory run 1 wrote, per instance.
.venv/bin/python -m docs_checker.evals run --instances lever --levers all \
  --arm "short_circuit cold" --memory-out /tmp/memory.json
.venv/bin/python -m docs_checker.evals run --instances lever --levers all \
  --arm "short_circuit warm" --memory-in /tmp/memory.json

# The per-user spend ledger; settle a reservation a crashed run left, at the console's figure.
.venv/bin/python -m docs_checker.evals spend
.venv/bin/python -m docs_checker.evals spend --settle '<run id>' --cash 0.12
```

- `--instances`: `all`, `dev`, `holdout`, a set named in `instances.json` (`lever` is the
  three-doc lever subset), or ids joined by commas.
- `--levers`: `all`, `none`, a list (`cache_prefix,short_circuit`), or leave-one-out
  (`-right_size`).
- `--overloaded N`: the first N requests of every key get a synthetic 529 before their
  recordings (marked replayed, never recorded), for the retry lever's row at no cost.
- `--run-budget-usd`: each instance's run budget (default $2.00, so a baseline run is never
  cut short); a priced run also stops at the cap's headroom.
- Exit code 2 means refused: no key, past the cap, another harness running, an unwritable
  spend ledger, or a replay miss.

Each run is the production graph (`build_graph`, the rules fix gate, the real tool belt)
on the local fake of the agent-docs server, in scheduled mode, with the instance's doc as
the scope. Nothing goes through gRPC.

## The key and the money

- The key comes from `DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY` only (a separate Anthropic
  workspace, spend limit $25), passed to the client explicitly, never `ANTHROPIC_API_KEY`.
  `record-missing` refuses to start without it; `replay` needs none.
- The $20 cap is counted in the per-user ledger (`~/.cache/docs-checker/spend.json`), so a
  fresh clone, a worktree or another `--evals-dir` does not start again at $0. A priced
  run refuses to start when that ledger cannot be written.
- Before it starts, a priced run reserves all it may spend: its run budget, or what is left
  under the cap when that is smaller (and that is then its budget). It is refused only when
  what is left is below its estimate. After the run the reservation becomes the run's cash
  cost: the priced calls that reached the API, plus the reservations of live calls whose
  cost is unknown. A crash (Ctrl-C, a timeout, a kill) leaves the whole reservation counted
  until it is settled by hand, unless the run sent no request at all: then it settles to $0.
- The cap is the harness's own count. The eval workspace's $25 Anthropic spend limit
  remains the hard backstop.
- Estimates: the largest workload cost of earlier runs of the same instance and levers
  (replays count, memory runs do not), else $0.60 per doc, or $0.05 with every lever on.
- Workload cost prices every call, replayed ones included: it is what the lever table
  compares. Cash cost is what was paid.

## Cassettes

A request's key is `sha256(method | path and query | canonical JSON body)`. Its cassette
is the ordered list of attempts made for it (status, `request-id`, `retry-after`,
`content-type`, JSON body), replayed in that order within a run, so a recorded 529 and its
retry's 200 come back in order. A priced run never trusts a recorded failure: a cassette
whose last attempt is not a 2xx (retries that ran out) is recorded again the first time a
priced run uses it, and a non-retryable 4xx (400, 401, 403: a bad request, a wrong key, no
credit) is passed on but never written. A cassette never holds the request, the API key or any
other header, and its body is redacted before it is written. Prompts carry no per-run data
(the fence token is derived from the commit), so a re-run hits the same keys; a changed
prompt, model or lever that reaches the request is a miss.

## The eval set

`instances.json`:

```json
{
  "instances": [
    {"id": "kagent-live", "doc": "base-apps/kagent/docs.md", "commit": "<40-hex sha>",
     "head": true, "overlays": {}, "split": "holdout", "purpose": "live positive"}
  ],
  "sets": {"lever": ["<id>", "<id>", "<id>"]}
}
```

`overlays` map a path to text (replace or add that file at the commit) or `null` (delete
it): planted mutations and the canary doc. An overlay is served as if committed at the
instance's commit.

`labels/<name>.json` is a list of labelled lines:

```json
[{"instance": "kagent-live", "line": 42, "label": "stale",
  "source": "base-apps/kagent/harness.yaml:12", "note": "",
  "labeller_a": "stale", "labeller_b": "stale", "adjudicated_by": null,
  "reviewed_by_ari": false}]
```

## Labelling rubric

Label every claim line of the instance's doc, as the file reads at the instance's commit
with its overlays applied (`git -C ~/git/kubernetes show <commit>:<path>`, then the
overlay). Line 1 is the front matter's opening `---`.

| Label | When |
|---|---|
| `stale` | The line states a checkable fact (a version, tag, chart, name, namespace, host, port, path, schedule, resource, count or configured behaviour) that a non-doc file at that commit contradicts. Note the file and line in `source`. |
| `missing` | The line names a file, directory or resource that does not exist at that commit (a front-matter source line included). |
| `true` | The line states a checkable fact that a non-doc file at that commit confirms. |
| `not-a-claim` | The line has no checkable fact (rationale, history, opinion, headings, prose). Label it only when an agent might take it for a claim. |
| `uncertain` | Neither labeller can settle it from the repository (a chart default, an external fact). |

- Evidence never comes from documentation: another `.md` file, `docs/**` or a generated copy
  cannot make a line `true` or `stale`.
- One label per line. A claim that spans lines is labelled on each of its lines.
- Two labellers label independently; disagreements are adjudicated and recorded in
  `adjudicated_by`. Ari reviews every positive and every disagreement
  (`reviewed_by_ari`); until then the precision gate is provisional.

## Scoring

Every finding a run reports is scored: the main list, "needs a look" and findings carried
from memory. Matching is one-to-one and scoped by instance: a finding is a true positive when its line
range covers a `stale` or `missing` label of its own instance and its verdict is that label;
each label matches at most one finding (a maximum matching). An unmatched finding is a false
positive when a line it covers carries any other label (`true`, `not-a-claim`, the other
positive class, or a positive another finding already matched); it is excluded when its
labelled lines are all `uncertain`; and it goes to `to_adjudicate`, not to the false
positives, when none of its lines is labelled. An unmatched positive label is a false
negative. Precision is TP / (TP + FP), recall TP / (TP + FN), and cost per verified finding
is the workload cost divided by TP.
