"""Curating the eval set: instances from git, planted overlays, labelling packets.

``python -m docs_checker.evals.curate <command>``::

    build      [--evals-dir DIR] [--clone PATH]
    packets    --out DIR [--evals-dir DIR] [--clone PATH]
    merge      --a PATH [--a PATH ...] --b PATH [--b PATH ...] --out FILE --disagreements FILE
               [--evals-dir DIR] [--clone PATH]
    adjudicate --labels FILE --decisions FILE --disagreements FILE
    validate   [--evals-dir DIR] [--clone PATH]

``merge``, ``adjudicate`` and ``validate`` are in ``labels.py``; this module builds the
instances they name.

The sources, committed under ``evals/``:

- ``curate.json``: ``head`` (the commit of every ``head`` instance), the history and live
  instances, and the named ``sets``. A history instance is a doc at a PR's parent commit;
  ``merge`` is the PR's merge commit (its parent must be that commit) and ``diff_lines``
  the doc's lines the PR rewrote, checked against git on every build.
- ``planted/<id>.json``: one fact changed at ``head``, with its answer key (``expected``). A
  ``version``, ``port`` or ``namespace`` plant replaces the one occurrence of ``old`` on
  ``line`` of the doc with ``new``; the answer key's evidence for that line (``path:line``
  of a non-doc file) must hold ``old``, so the planted line is contradicted. A
  ``deleted-source`` plant deletes ``old``, the front-matter source on ``line`` (an overlay
  ``null``).
- ``canary/<id>.md`` with its sidecar ``canary/<id>.json``: a copy of an in-scope doc with
  injected lines, served at its own path at ``head``. The sidecar records the injected fix,
  the pass condition and its checkable ``fails_if`` predicates.

A value is matched as a whole name: ``weather-kitchen`` is not found inside
``weather-kitchen-tls`` or ``weather-kitchen.arigsela.com``. Lines are counted by ``\\n``,
as the checker counts them; a final newline does not start another line.

``build`` writes ``instances.json`` (deterministic; overlays carry full file text) after
serving every instance through the harness's local repository. ``packets`` writes each doc
as served, numbered, for the labellers, with ``manifest.json``. Git runs read-only, as an
argument list.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from docs_checker.evals.harness import EVALS_DIR, Instance, load_eval_set
from docs_checker.evals.localrepo import LocalRepoSession, _git_env
from docs_checker.frontmatter import FrontMatterError, parse_front_matter
from docs_checker.scope import in_scope

DEFAULT_CLONE = Path(os.environ.get("DOCS_CHECKER_EVAL_CLONE", "~/git/kubernetes")).expanduser()

Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$")]
Split = Literal["dev", "holdout"]


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceInstance(_Spec):
    """A history or live instance in ``curate.json``."""

    id: Id
    doc: str
    commit: Sha | None = None
    head: bool = False
    split: Split
    purpose: str
    pr: int | None = None
    merge: Sha | None = None
    diff_lines: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_commit(self) -> SourceInstance:
        if self.head == (self.commit is not None):
            raise ValueError(f"{self.id}: give either head: true or a commit")
        if (self.merge is None) != (not self.diff_lines):
            raise ValueError(f"{self.id}: merge and diff_lines go together")
        return self


class CurateSpec(_Spec):
    head: Sha
    instances: list[SourceInstance]
    sets: dict[str, list[str]] = Field(default_factory=dict)


class Expected(_Spec):
    """One line of a plant's answer key."""

    line: int = Field(ge=1)
    label: Literal["stale", "missing"]
    source: str = Field(min_length=1)  # path:line of the evidence, or the missing path
    note: str = ""


class PlantedSpec(_Spec):
    id: Id
    doc: str
    kind: Literal["version", "port", "namespace", "deleted-source"]
    split: Split
    purpose: str
    line: int = Field(ge=1)
    old: str = Field(min_length=1)
    new: str | None = None
    expected: list[Expected] = Field(min_length=1)


class InjectedFix(_Spec):
    line: int = Field(ge=1)
    old_text: str
    replacement: str


class CanaryFailsIf(_Spec):
    """What makes a run fail the canary, as predicates a scorer can check."""

    finding_on_lines: list[int] = Field(min_length=1)  # any finding covering one of them
    replacement_contains: list[str] = Field(min_length=1)  # in any proposed replacement
    output_contains: list[str] = Field(min_length=1)  # system-prompt markers, in any output


class CanarySpec(_Spec):
    id: Id
    path: str
    copied_from: str
    split: Split
    purpose: str
    injected_lines: list[int] = Field(min_length=1)
    injected_fix: InjectedFix
    pass_condition: str
    fails_if: CanaryFailsIf
    not_failures: list[str] = Field(default_factory=list)


# --- git -------------------------------------------------------------------------------------


def _safe(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("-") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"not a repository file path: {path!r}")
    return path


def _rev(commit: str) -> str:
    """A commit as git may take it: never something git would read as an option."""
    if not commit or commit.startswith("-"):
        raise ValueError(f"not a commit: {commit!r}")
    return commit


class Repo:
    """Read-only git on the clone: no shell, and localrepo's environment (no GIT_* variables
    of the caller, literal pathspecs)."""

    def __init__(self, clone: Path | str):
        self.clone = Path(clone)

    def _git(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(self.clone), *args], check=False, capture_output=True, env=_git_env()
        )

    def commit(self, sha: str) -> str:
        done = self._git("rev-parse", "--verify", "--quiet", f"{_rev(sha)}^{{commit}}")
        if done.returncode != 0:
            raise ValueError(f"{sha} names no commit in {self.clone}")
        return done.stdout.decode().strip()

    def show(self, commit: str, path: str) -> str | None:
        """The file's text at ``commit``, or None when it is not a file there."""
        done = self._git("cat-file", "blob", f"{_rev(commit)}:{_safe(path)}")
        return done.stdout.decode("utf-8") if done.returncode == 0 else None

    def exists(self, commit: str, path: str) -> bool:
        spec = f"{_rev(commit)}:{_safe(path.rstrip('/'))}"
        return self._git("cat-file", "-e", spec).returncode == 0

    def parents(self, commit: str) -> list[str]:
        done = self._git("rev-list", "--parents", "-n", "1", _rev(commit))
        return done.stdout.decode().split()[1:] if done.returncode == 0 else []

    def diff_lines(self, old: str, new: str, path: str) -> list[int]:
        """The lines of ``path`` at ``old`` that ``new`` removed or rewrote."""
        done = self._git(
            "diff",
            "-U0",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            _rev(old),
            _rev(new),
            "--",
            _safe(path),
        )
        if done.returncode != 0:
            raise ValueError(f"git diff {old} {new} -- {path} failed")
        lines: list[int] = []
        for match in re.finditer(rb"^@@ -(\d+)(?:,(\d+))? \+", done.stdout, re.MULTILINE):
            start, count = int(match[1]), int(match[2] or 1)
            lines.extend(range(start, start + count))
        return lines


# --- docs and values ---------------------------------------------------------------------------


def doc_lines(text: str) -> list[str]:
    """A doc's lines as the checker numbers them (line 1 first); a final newline ends
    the last line rather than starting another."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _value(value: str) -> re.Pattern[str]:
    # Not inside a longer name: no name character or dot before it, no name character
    # (or a dot followed by one, as in a host) after it.
    return re.compile(rf"(?<![\w.-]){re.escape(value)}(?![\w-])(?!\.\w)")


def count_value(line: str, value: str) -> int:
    """How often ``value`` appears on ``line`` as a whole name."""
    return len(_value(value).findall(line))


def names_path(line: str, path: str) -> bool:
    """``line`` names ``path``: the whole path or a tail of it (``service.yaml``,
    ``app/service.yaml``), not as the end of some other path."""
    parts = path.split("/")
    tails = ("/".join(parts[i:]) for i in range(len(parts)))
    return any(re.search(rf"(?<![\w./-]){re.escape(t)}(?![\w/-])(?!\.\w)", line) for t in tails)


def _is_documentation(path: str) -> bool:
    return path.endswith(".md") or path == "docs" or path.startswith("docs/")


def _doc_at(repo: Repo, commit: str, path: str) -> str:
    """An in-scope doc's text at ``commit``."""
    text = repo.show(commit, path)
    if text is None:
        raise ValueError(f"{path} is not a file at {commit}")
    try:
        sources = parse_front_matter(path, text).sources
    except FrontMatterError as error:
        raise ValueError(f"{path} at {commit}: {error.reason}") from error
    if not in_scope(path) or not sources:
        raise ValueError(f"{path} at {commit} is not an in-scope doc (excluded or no sources)")
    return text


def _served_check(repo: Repo, instance: Instance) -> Instance:
    """Serve the instance the way the harness will; a bad overlay raises ValueError."""
    LocalRepoSession(repo.clone, instance.commit, instance.overlays)
    return instance


# --- planting ----------------------------------------------------------------------------------


def _primary(spec: PlantedSpec, label: str) -> Expected:
    for entry in spec.expected:
        if entry.line == spec.line and entry.label == label:
            return entry
    raise ValueError(f"{spec.id}: the answer key has no {label} entry for line {spec.line}")


def _evidence(spec_id: str, source: str) -> tuple[str, int]:
    path, _, number = source.rpartition(":")
    if not path or not number.isdigit() or int(number) < 1:
        raise ValueError(f"{spec_id}: evidence {source!r} is not path:line")
    return path, int(number)


def _check_answer_key(
    spec: PlantedSpec, lines: list[str], repo: Repo, head: str, overlays: dict[str, str | None]
) -> None:
    seen: set[int] = set()
    for entry in spec.expected:
        if entry.line in seen:
            raise ValueError(f"{spec.id}: the answer key names line {entry.line} twice")
        seen.add(entry.line)
        if entry.line > len(lines) or not lines[entry.line - 1].strip():
            raise ValueError(f"{spec.id}: answer key line {entry.line} is blank or past the end")
        if entry.label == "stale":
            path, number = _evidence(spec.id, entry.source)
            if _is_documentation(path):
                raise ValueError(f"{spec.id}: evidence {entry.source} is documentation")
            text = repo.show(head, path) if overlays.get(path, "") is not None else None
            if text is None or number > len(doc_lines(text)):
                raise ValueError(f"{spec.id}: evidence {entry.source} is not there at {head}")
        elif repo.exists(head, entry.source) and overlays.get(entry.source, "") is not None:
            raise ValueError(f"{spec.id}: the answer key says {entry.source} is missing; it is not")
        elif not names_path(lines[entry.line - 1], entry.source):
            raise ValueError(
                f"{spec.id}: answer key line {entry.line} does not name {entry.source}"
            )


def plant(spec: PlantedSpec, repo: Repo, head: str) -> Instance:
    """The planted instance at ``head``: one value changed on one line of the doc, or one
    front-matter source deleted. Raises ValueError for a plant that is not exactly that."""
    text = _doc_at(repo, head, spec.doc)
    lines = text.split("\n")
    if spec.line > len(doc_lines(text)):
        raise ValueError(f"{spec.id}: line {spec.line} is past the end of {spec.doc}")
    overlays: dict[str, str | None]
    if spec.kind == "deleted-source":
        if spec.new is not None:
            raise ValueError(f"{spec.id}: a deleted-source plant has new: null")
        listed = [s.line for s in parse_front_matter(spec.doc, text).sources if s.value == spec.old]
        if not listed:
            raise ValueError(f"{spec.id}: {spec.old} is not a front-matter source of {spec.doc}")
        if spec.line not in listed:
            raise ValueError(
                f"{spec.id}: the front-matter source on line {spec.line} of {spec.doc} is not "
                f"{spec.old} (it is on line {listed[0]})"
            )
        if _is_documentation(_safe(spec.old)):
            raise ValueError(f"{spec.id}: {spec.old} is documentation, not a source file")
        _primary(spec, "missing")
        overlays = {spec.old: None}
    else:
        if spec.new is None or spec.new == spec.old:
            raise ValueError(f"{spec.id}: new must differ from old")
        target = lines[spec.line - 1]
        found = count_value(target, spec.old)
        if found != 1:
            raise ValueError(
                f"{spec.id}: {spec.old!r} must occur exactly once on line {spec.line} of "
                f"{spec.doc} (found {found})"
            )
        if count_value(target, spec.new):
            raise ValueError(f"{spec.id}: {spec.new!r} is already on line {spec.line}")
        path, number = _evidence(spec.id, _primary(spec, "stale").source)
        if _is_documentation(path):
            raise ValueError(f"{spec.id}: evidence {path}:{number} is documentation")
        evidence = doc_lines(repo.show(head, path) or "")
        held = evidence[number - 1] if number <= len(evidence) else ""
        if count_value(held, spec.old) == 0 or count_value(held, spec.new):
            raise ValueError(
                f"{spec.id}: {path}:{number} does not hold {spec.old!r}, so it does not "
                f"contradict {spec.new!r}"
            )
        new = spec.new
        lines[spec.line - 1] = _value(spec.old).sub(lambda _: new, target, count=1)
        overlays = {spec.doc: "\n".join(lines)}
    _check_answer_key(spec, doc_lines(text), repo, head, overlays)
    instance = Instance(
        id=spec.id,
        doc=spec.doc,
        commit=head,
        head=True,
        overlays=overlays,
        split=spec.split,
        purpose=spec.purpose,
    )
    return _served_check(repo, instance)


def canary(spec: CanarySpec, text: str, repo: Repo, head: str) -> Instance:
    """The canary instance: ``text`` (a copy of ``copied_from`` with injected lines) served
    at its own path at ``head``, citing real files."""
    if not in_scope(_safe(spec.path)):
        raise ValueError(f"{spec.id}: {spec.path} is not an in-scope path")
    if repo.exists(head, spec.path):
        raise ValueError(f"{spec.id}: {spec.path} already exists at {head}")
    original = _doc_at(repo, head, spec.copied_from)
    lines = text.split("\n")
    injected = set(spec.injected_lines)
    if max(injected) > len(doc_lines(text)):
        raise ValueError(f"{spec.id}: an injected line is past the end of the canary")
    if "\n".join(line for n, line in enumerate(lines, 1) if n not in injected) != original:
        raise ValueError(
            f"{spec.id}: without lines {sorted(injected)} it is not a copy of "
            f"{spec.copied_from} at {head}"
        )
    try:
        sources = parse_front_matter(spec.path, text).sources
    except FrontMatterError as error:
        raise ValueError(f"{spec.id}: {error.reason}") from error
    absent = [s.value for s in sources if s.kind != "url" and not repo.exists(head, s.value)]
    if not sources or absent:
        raise ValueError(f"{spec.id}: its sources must all exist at {head} (absent: {absent})")
    fix = spec.injected_fix
    actual = lines[fix.line - 1] if fix.line <= len(lines) else ""
    if fix.line in injected or actual != fix.old_text:
        raise ValueError(f"{spec.id}: injected_fix line {fix.line} reads {actual!r}, not old_text")
    if fix.replacement == fix.old_text:
        raise ValueError(f"{spec.id}: the injected fix changes nothing")
    fails = spec.fails_if
    if fix.line not in fails.finding_on_lines:
        raise ValueError(f"{spec.id}: fails_if.finding_on_lines must hold the target line")
    if any(v not in fix.replacement or v in original for v in fails.replacement_contains):
        raise ValueError(
            f"{spec.id}: each replacement_contains value must be in the injected fix's "
            "replacement and nowhere in the original doc"
        )
    if any(not marker.strip() or marker in text for marker in fails.output_contains):
        raise ValueError(f"{spec.id}: an output_contains marker is empty or quoted by the canary")
    purpose = (
        f"{spec.purpose} Pass: {spec.pass_condition}. "
        f"The injected fix is injected_fix in evals/canary/{spec.id}.json."
    )
    instance = Instance(
        id=spec.id,
        doc=spec.path,
        commit=head,
        head=True,
        overlays={spec.path: text},
        split=spec.split,
        purpose=purpose,
    )
    return _served_check(repo, instance)


def _source_instance(entry: SourceInstance, repo: Repo, head: str) -> Instance:
    commit = head if entry.head else repo.commit(entry.commit or "")
    _doc_at(repo, commit, entry.doc)
    if entry.merge is not None:
        if repo.parents(entry.merge)[:1] != [commit]:
            raise ValueError(f"{entry.id}: {entry.merge}'s parent is not {commit}")
        actual = repo.diff_lines(commit, entry.merge, entry.doc)
        if actual != entry.diff_lines:
            raise ValueError(
                f"{entry.id}: diff_lines {entry.diff_lines} do not match the PR's diff, which "
                f"rewrote lines {actual}"
            )
    instance = Instance(
        id=entry.id,
        doc=entry.doc,
        commit=commit,
        head=entry.head,
        overlays={},
        split=entry.split,
        purpose=entry.purpose,
    )
    return _served_check(repo, instance)


def specs(directory: Path, suffix: str) -> list[Path]:
    """The spec files with ``suffix`` in ``directory``, sorted (none when it is absent)."""
    return sorted(directory.glob(f"*{suffix}")) if directory.is_dir() else []


def build(evals_dir: Path, clone: Path) -> dict[str, Any]:
    """Write ``instances.json`` from the committed sources; returns what it wrote."""
    repo = Repo(clone)
    spec = CurateSpec.model_validate_json((evals_dir / "curate.json").read_text())
    head = repo.commit(spec.head)
    instances = [_source_instance(entry, repo, head) for entry in spec.instances]
    for path in specs(evals_dir / "planted", ".json"):
        planted = PlantedSpec.model_validate_json(path.read_text())
        if planted.id != path.stem:
            raise ValueError(f"{path.name}: its id is {planted.id}")
        instances.append(plant(planted, repo, head))
    canaries = evals_dir / "canary"
    if {p.stem for p in specs(canaries, ".md")} != {p.stem for p in specs(canaries, ".json")}:
        raise ValueError("every canary needs both <id>.md and its sidecar <id>.json")
    for path in specs(canaries, ".md"):
        sidecar = CanarySpec.model_validate_json(path.with_suffix(".json").read_text())
        if sidecar.id != path.stem:
            raise ValueError(f"{path.with_suffix('.json').name}: its id is {sidecar.id}")
        instances.append(canary(sidecar, path.read_bytes().decode("utf-8"), repo, head))
    ids = [i.id for i in instances]
    twice = sorted({i for i in ids if ids.count(i) > 1})
    unknown = sorted({i for members in spec.sets.values() for i in members if i not in ids})
    if twice or unknown:
        raise ValueError(f"instance ids defined twice: {twice}; set members unknown: {unknown}")
    data = {"instances": [i.model_dump(mode="json") for i in instances], "sets": spec.sets}
    write_json(evals_dir / "instances.json", data)
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- packets -----------------------------------------------------------------------------------


def served(instance: Instance, repo: Repo) -> str:
    """The instance's doc as the harness serves it: the overlay, else the commit's file."""
    if instance.doc in instance.overlays:
        text = instance.overlays[instance.doc]
        if text is None:
            raise ValueError(f"{instance.id}: an overlay deletes the doc itself")
        return text
    text = repo.show(instance.commit, instance.doc)
    if text is None:
        raise ValueError(f"{instance.id}: {instance.doc} is not a file at {instance.commit}")
    return text


def write_packets(instances: Iterable[Instance], repo: Repo, out: Path) -> list[dict[str, Any]]:
    """``<id>.txt`` per instance (the served doc, numbered from 1), any other overlaid
    file under ``overlays/<id>/``, and ``manifest.json``."""
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for instance in instances:
        lines = doc_lines(served(instance, repo))
        numbered = "".join(f"{n:6}\t{line}\n" for n, line in enumerate(lines, 1))
        (out / f"{instance.id}.txt").write_text(numbered, encoding="utf-8")
        replaced = sorted(p for p, text in instance.overlays.items() if text is not None)
        for path in replaced:
            if path != instance.doc:
                target = out / "overlays" / instance.id / _safe(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(instance.overlays[path] or "", encoding="utf-8")
        entries.append(
            {
                "id": instance.id,
                "doc": instance.doc,
                "commit": instance.commit,
                "packet": f"{instance.id}.txt",
                "lines": len(lines),
                "overlays": {
                    "replaced": replaced,
                    "deleted": sorted(p for p, t in instance.overlays.items() if t is None),
                },
            }
        )
    clone = str(repo.clone)
    manifest = {
        "clone": clone,
        "how_to_read_evidence": [
            (
                "<id>.txt is the doc exactly as served at that instance (its commit plus "
                "overlays), numbered from 1; line 1 is the front matter's opening ---. Label by "
                "these numbers."
            ),
            f"Any other file at the instance's commit: git -C {clone} show <commit>:<path>",
            f"A directory: git -C {clone} ls-tree -r --name-only <commit> -- <dir>",
            f"A search: git -C {clone} grep -n <pattern> <commit> -- <paths>",
            (
                "Overlays win over the commit: a path under overlays.deleted does not exist at "
                "that instance (whatever git shows), and a path under overlays.replaced reads as "
                "overlays/<id>/<path> here (the doc itself as <id>.txt)."
            ),
        ],
        "instances": entries,
    }
    write_json(out / "manifest.json", manifest)
    return entries


# --- CLI -------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docs_checker.evals.curate")
    commands = parser.add_subparsers(dest="command", required=True)

    def with_repo(name: str, summary: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=summary)
        command.add_argument("--evals-dir", type=Path, default=EVALS_DIR)
        command.add_argument("--clone", type=Path, default=DEFAULT_CLONE)
        return command

    with_repo("build", "write instances.json from curate.json, planted/ and canary/")
    with_repo("packets", "write the labelling packets").add_argument(
        "--out", type=Path, required=True
    )
    merge_cmd = with_repo("merge", "join two labellers' rows over the served docs")
    merge_cmd.add_argument("--a", type=Path, action="append", required=True)
    merge_cmd.add_argument("--b", type=Path, action="append", required=True)
    merge_cmd.add_argument("--out", type=Path, required=True)
    merge_cmd.add_argument("--disagreements", type=Path, required=True)
    adjudicate_cmd = commands.add_parser("adjudicate", help="apply decisions to a labels file")
    adjudicate_cmd.add_argument("--labels", type=Path, required=True)
    adjudicate_cmd.add_argument("--decisions", type=Path, required=True)
    adjudicate_cmd.add_argument("--disagreements", type=Path, required=True)
    with_repo("validate", "check the labels against the served docs")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "build":
        data = build(args.evals_dir, args.clone)
        print(f"wrote {args.evals_dir / 'instances.json'}: {len(data['instances'])} instances")
    elif args.command == "packets":
        instances = load_eval_set(args.evals_dir).instances.values()
        entries = write_packets(instances, Repo(args.clone), args.out)
        print(f"wrote {len(entries)} packets and manifest.json to {args.out}")
    elif args.command == "merge":
        from docs_checker.evals import labels  # labels.py builds on this module

        docs = labels.served_lines(args.evals_dir, args.clone)
        merged = labels.merge(labels.read_rows(args.a), labels.read_rows(args.b), docs)
        write_json(args.out, [label.model_dump() for label in merged.labels])
        write_json(args.disagreements, [d.model_dump() for d in merged.disagreements])
        agreed = len(merged.labels) - len(merged.disagreements)
        print(
            f"{agreed} agreed lines, {len(merged.disagreements)} disagreements (in {args.out} as "
            f"rows awaiting adjudication), {len(merged.dropped)} rows on blank lines dropped"
        )
        for row in merged.dropped:
            print(f"  dropped: labeller {row['labeller']}, {row['instance']} line {row['line']}")
    elif args.command == "adjudicate":
        from docs_checker.evals import labels

        done = labels.adjudicate(
            labels.load_rows(args.labels, labels.LabelledLine),
            labels.load_rows(args.decisions, labels.LabellerRow),
            labels.load_rows(args.disagreements, labels.Disagreement),
        )
        write_json(args.labels, [label.model_dump() for label in done])
        print(f"{args.labels}: {len(done)} lines")
    else:
        from docs_checker.evals import labels

        problems = labels.validate(args.evals_dir, args.clone)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print("labels valid")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
