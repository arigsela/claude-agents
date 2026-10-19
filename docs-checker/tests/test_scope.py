"""Discovery and source expansion, through the real reader, belt and local git fake."""

import pytest

from docs_checker.frontmatter import parse_front_matter
from docs_checker.repo import ReadResult, RepoReader
from docs_checker.scope import DiscoveryError, discover, expand_sources, in_scope
from tests.test_repo import git, local_belt

DOC = "---\ntitle: t\nsources:\n  - {src}\n---\nbody\n"


def commit_all(repo):
    git("-c", "core.autocrlf=false", "add", "-A", cwd=repo)
    git(
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "-c", "commit.gpgsign=false", "commit", "-qm", "one", cwd=repo,
    )  # fmt: skip
    return git("rev-parse", "HEAD", cwd=repo).strip()


def make_tree(root, files: dict[str, str | bytes]):
    repo = root / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return repo, commit_all(repo)


def reader_of(repo, commit):
    return RepoReader(local_belt(commit, clone=repo), commit)


def test_exclusions():
    assert in_scope("base-apps/postgresql/runbook.md")
    assert in_scope("docs/guide.md")
    assert in_scope("recovery/restore.md")
    for path in (
        "SPEC.md",
        "base-apps/x/SPEC.md",
        "docs/superpowers/specs/a.md",
        "base-apps/x/docs/index.md",
        "base-apps/x/docs/runbook.md",
        "templates/app/docs.md",
        "base-apps/x/deployment.yaml",
    ):
        assert not in_scope(path), path
    assert in_scope("base-apps/x/docs/other.md")
    assert in_scope("base-apps/x/runbook.md")


async def test_discovery_finds_docs_with_sources_and_skips_the_rest(tmp_path):
    repo, commit = make_tree(
        tmp_path,
        {
            "base-apps/a/docs.md": DOC.format(src="base-apps/a/d.yaml"),
            "base-apps/a/notes.md": "no front matter\n",
            "base-apps/a/nosrc.md": "---\ntitle: t\n---\nbody\n",
            "base-apps/a/broken.md": "---\nsources: [a\n---\n",
            "base-apps/a/docs/index.md": DOC.format(src="x"),
            "base-apps/a/nested/deep/more.md": DOC.format(src="x.yaml"),
            "docs/superpowers/p.md": DOC.format(src="x"),
            "templates/t.md": DOC.format(src="x"),
            "other/outside.md": DOC.format(src="x"),
        },
    )
    docs, truncated = await discover(reader_of(repo, commit), max_docs=10)
    assert docs == [
        "base-apps/a/broken.md",  # malformed front matter is kept, to be reported
        "base-apps/a/docs.md",
        "base-apps/a/nested/deep/more.md",
    ]
    assert truncated is False


async def test_discovery_stops_at_max_docs_and_says_so(tmp_path):
    repo, commit = make_tree(
        tmp_path, {f"base-apps/a/d{i}.md": DOC.format(src="x.yaml") for i in range(5)}
    )
    reader = reader_of(repo, commit)
    docs, truncated = await discover(reader, max_docs=3)
    assert (len(docs), truncated) == (3, True)
    docs, truncated = await discover(reader, max_docs=5)  # exactly full is not truncated
    assert (len(docs), truncated) == (5, False)


async def test_discovery_reports_a_listing_it_cannot_read(tmp_path):
    repo, commit = make_tree(tmp_path, {"base-apps/a.md": "x\n"})
    reader = reader_of(repo, commit)
    # a root that is a file, not a directory, is an error and not an empty scope
    with pytest.raises(DiscoveryError):
        await discover(reader, roots=("base-apps/a.md",), max_docs=5)
    with pytest.raises(DiscoveryError):  # the only root is absent: wrong roots, not an empty scope
        await discover(reader, roots=("recovery",), max_docs=5)


async def test_expand_reads_paths_maps_and_dirs_and_never_urls(tmp_path):
    repo, commit = make_tree(
        tmp_path,
        {
            "a.yaml": "a: 1\n",
            "b.yaml": "b: 2\n",
            "dir/c.yaml": "c: 3\n",
            "dir/sub/d.yaml": "d: 4\n",
        },
    )
    text = (
        "---\nsources:\n  - a.yaml\n  - {id: b, resource: b.yaml, title: B}\n  - dir/\n"
        "  - missing.yaml\n  - https://example.com/x\n---\n"
    )
    meta = parse_front_matter("docs/x.md", text)
    read, skipped = await expand_sources(
        reader_of(repo, commit), meta, max_dir_files=50, max_file_bytes=1000
    )
    assert {p: r.status for p, r in read.items()} == {
        "a.yaml": "found",
        "b.yaml": "found",
        "dir/c.yaml": "found",
        "missing.yaml": "absent",
    }
    assert read["dir/c.yaml"].text == "c: 3\n"
    assert skipped == ["dir/sub: subdirectory", "https://example.com/x: url"]


async def test_sources_are_keyed_by_their_one_spelling(tmp_path):
    # Review M2: a source written ./dir/, /dir/ or ./a.yaml is keyed as the reader names
    # it, so the load stage finds an absent directory's listing under the same key.
    repo, commit = make_tree(tmp_path, {"a.yaml": "a: 1\n", "dir/c.yaml": "c: 3\n"})
    text = "---\nsources:\n  - ./a.yaml\n  - /dir/\n  - ./nothere/\n  - /gone.yaml\n---\n"
    meta = parse_front_matter("docs/x.md", text)
    read, skipped = await expand_sources(
        reader_of(repo, commit), meta, max_dir_files=50, max_file_bytes=1000
    )
    assert {p: r.status for p, r in read.items()} == {
        "a.yaml": "found",
        "dir/c.yaml": "found",
        "nothere": "absent",
        "gone.yaml": "absent",
    }
    assert skipped == []


async def test_dir_source_overflow_is_reported_not_read(tmp_path):
    repo, commit = make_tree(tmp_path, {f"dir/f{i}.yaml": f"v: {i}\n" for i in range(5)})
    belt = local_belt(commit, clone=repo)
    reader = RepoReader(belt, commit)
    meta = parse_front_matter("x.md", "---\nsources:\n  - dir/\n---\n")
    read, skipped = await expand_sources(reader, meta, max_dir_files=2, max_file_bytes=1000)
    assert sorted(read) == ["dir/f0.yaml", "dir/f1.yaml"]
    assert skipped == [f"dir/f{i}.yaml: over 2 files in the directory" for i in (2, 3, 4)]


async def test_oversize_file_is_skipped_not_returned(tmp_path):
    repo, commit = make_tree(tmp_path, {"big.yaml": "x" * 100, "ok.yaml": "y\n"})
    meta = parse_front_matter("x.md", "---\nsources:\n  - big.yaml\n  - ok.yaml\n---\n")
    read, skipped = await expand_sources(
        reader_of(repo, commit), meta, max_dir_files=50, max_file_bytes=50
    )
    assert list(read) == ["ok.yaml"]
    assert skipped == ["big.yaml: over 50 bytes"]


class ScriptedReader:
    """list_dir and read answer from per-path scripts (the last answer repeats)."""

    def __init__(self, listings: dict, files: dict):
        self.listings, self.files, self.calls = listings, files, []

    def _next(self, script: dict, path: str, kind: str):
        self.calls.append((kind, path))
        answers = script[path]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, str) and answer in ("transient", "denied", "error", "absent"):
            return ReadResult(path, answer, None, None)
        return ReadResult(path, "found", answer, None if kind == "list" else "0" * 40)

    async def list_dir(self, path, *, node="load", events=None):
        return self._next(self.listings, path, "list")

    async def read(self, path, *, node="load", events=None):
        return self._next(self.files, path, "read")


GOOD = DOC.format(src="x.yaml")


async def test_transient_file_read_is_retried_once():
    reader = ScriptedReader(
        {"base-apps": ["base-apps/a.md"]}, {"base-apps/a.md": ["transient", GOOD]}
    )
    assert await discover(reader, roots=("base-apps",), max_docs=5) == (["base-apps/a.md"], False)
    assert reader.calls.count(("read", "base-apps/a.md")) == 2


@pytest.mark.parametrize("status", ["transient", "denied", "error"])
async def test_unreadable_file_is_kept_so_the_load_stage_reports_it(status):
    reader = ScriptedReader(
        {"base-apps": ["base-apps/a.md\nbase-apps/b.md"]},
        {"base-apps/a.md": [status], "base-apps/b.md": [GOOD]},
    )
    docs, truncated = await discover(reader, roots=("base-apps",), max_docs=5)
    assert (docs, truncated) == (["base-apps/a.md", "base-apps/b.md"], False)
    assert reader.calls.count(("read", "base-apps/a.md")) == (2 if status == "transient" else 1)


async def test_listed_file_absent_at_the_commit_raises():
    reader = ScriptedReader({"base-apps": ["base-apps/a.md"]}, {"base-apps/a.md": ["absent"]})
    with pytest.raises(DiscoveryError):
        await discover(reader, roots=("base-apps",), max_docs=5)


async def test_failed_listings_are_all_named_after_trying_every_root():
    reader = ScriptedReader(
        {
            "base-apps": ["transient"],
            "docs": ["base-apps/never.md"],  # a stub answer: docs lists fine
            "recovery": ["denied"],
        },
        {"base-apps/never.md": [GOOD]},
    )
    with pytest.raises(DiscoveryError) as err:
        await discover(reader, max_docs=5)
    assert {f.path: f.status for f in err.value.failures} == {
        "base-apps": "transient",
        "recovery": "denied",
    }
    assert "base-apps" in str(err.value) and "recovery" in str(err.value)
    assert reader.calls.count(("list", "base-apps")) == 2  # transient: retried once
    assert reader.calls.count(("list", "recovery")) == 1
    assert ("list", "docs") in reader.calls  # the other roots were still tried


async def test_transient_listing_succeeds_on_retry():
    reader = ScriptedReader(
        {"base-apps": ["transient", "base-apps/a.md"]}, {"base-apps/a.md": [GOOD]}
    )
    assert (await discover(reader, roots=("base-apps",), max_docs=5))[0] == ["base-apps/a.md"]


async def test_every_root_absent_raises_but_one_missing_root_is_fine(tmp_path):
    repo, commit = make_tree(tmp_path, {"base-apps/a/d.md": GOOD})
    reader = reader_of(repo, commit)
    with pytest.raises(DiscoveryError):
        await discover(reader, roots=("base-app", "doc"), max_docs=5)
    docs, _ = await discover(reader, roots=("base-apps", "recovery"), max_docs=5)
    assert docs == ["base-apps/a/d.md"]


async def test_exclusions_match_whole_path_segments(tmp_path):
    for path in ("templates-old/t.md", "docs/superpowers-x/p.md"):
        assert in_scope(path), path
    assert not in_scope("docs/superpowers/p.md") and not in_scope("templates/t.md")
    repo, commit = make_tree(
        tmp_path,
        {
            "docs/superpowers-x/p.md": GOOD,
            "docs/superpowers/q.md": GOOD,
            "docs/ok.md": GOOD,
            "templates-old/t.md": GOOD,
            "templates/t.md": GOOD,
        },
    )
    docs, _ = await discover(
        reader_of(repo, commit), roots=("docs", "templates-old", "templates"), max_docs=10
    )
    assert docs == ["docs/ok.md", "docs/superpowers-x/p.md", "templates-old/t.md"]
