import json
import logging

from docs_checker.frontmatter import DocMeta, SourceRef
from docs_checker.memory import (
    CHECKER_KEY,
    MAX_SNAPSHOT_BYTES,
    UNKNOWN,
    SnapshotStore,
    fingerprint,
    skip_unchanged,
)
from docs_checker.state import Decision

META = DocMeta(
    "docs/a.md", [SourceRef("path", "app/x.yaml", 3), SourceRef("url", "http://u", 4)], None, 6
)


class Reader:
    def __init__(self, commits):
        self.commits = commits

    async def latest_commit(self, path, **_):
        return self.commits.get(path)


def decision(reason="r"):
    return Decision(verdict="stale", confidence=0.9, reason=reason, judged_by="haiku")


COMMITS = {"docs/a.md": "a" * 40, "app/x.yaml": "b" * 40, "app/e.yaml": "c" * 40}


async def test_fingerprint_covers_doc_sources_evidence_and_checker():
    fp = await fingerprint(META, Reader(COMMITS), ["app/e.yaml"], "chk")
    assert fp == {**COMMITS, CHECKER_KEY: "chk"}  # url sources are not fingerprinted


def loaded(fp, status="checked"):
    s = SnapshotStore()
    s.put_doc("docs/a.md", status=status, fingerprint=fp, checker="chk", open_findings=[])
    return s.get_doc("docs/a.md")


async def test_skip_when_everything_matches():
    fp = await fingerprint(META, Reader(COMMITS), ["app/e.yaml"], "chk")
    assert skip_unchanged(META, loaded(fp), dict(fp))


async def test_incomplete_docs_are_never_skipped():
    fp = await fingerprint(META, Reader(COMMITS), [], "chk")
    for status in ("incomplete", "failed", "skipped-budget", "unchanged"):
        assert not skip_unchanged(META, loaded(fp, status), dict(fp))
    assert not skip_unchanged(META, None, fp)


async def test_a_new_evidence_path_change_invalidates_the_skip():
    fp = await fingerprint(META, Reader(COMMITS), ["app/e.yaml"], "chk")
    stored = loaded(fp)
    changed = await fingerprint(
        META, Reader({**COMMITS, "app/e.yaml": "d" * 40}), ["app/e.yaml"], "chk"
    )
    assert not skip_unchanged(META, stored, changed)
    # a newly used evidence path is also a difference
    extra = await fingerprint(META, Reader(COMMITS), ["app/e.yaml", "app/n.yaml"], "chk")
    assert not skip_unchanged(META, stored, extra)


async def test_checker_version_change_invalidates_everything():
    fp = await fingerprint(META, Reader(COMMITS), [], "chk")
    new = await fingerprint(META, Reader(COMMITS), [], "chk2")
    assert not skip_unchanged(META, loaded(fp), new)


async def test_an_unknown_commit_never_allows_a_skip():
    broken = {k: v for k, v in COMMITS.items() if k != "app/x.yaml"}
    fp = await fingerprint(META, Reader(broken), [], "chk")
    assert fp["app/x.yaml"] == UNKNOWN
    assert not skip_unchanged(META, loaded(fp), dict(fp))


def test_an_all_unchanged_run_returns_the_full_snapshot():
    s = SnapshotStore()
    s.run = 3
    s.put_doc("docs/a.md", status="checked", fingerprint={"x": "1"}, checker="c", open_findings=[])
    s.put_decision("k1", decision())
    first = s.snapshot({"docs/a.md"})
    again = SnapshotStore.from_snapshot(json.loads(json.dumps(first)))
    second = again.snapshot({"docs/a.md"})
    assert second["docs"] == first["docs"]
    assert second["decisions"] == first["decisions"]
    assert second["run"] == first["run"] + 1


def test_pruning_out_of_scope_docs_and_stale_decisions():
    s = SnapshotStore()
    s.run = 1
    s.put_doc("gone.md", status="checked", fingerprint={}, checker="c", open_findings=[])
    s.put_doc("here.md", status="checked", fingerprint={}, checker="c", open_findings=[])
    s.put_decision("old", decision())
    s.run = 5
    s.put_decision("new", decision())
    snap = s.snapshot({"here.md"})
    assert set(snap["docs"]) == {"here.md"}
    assert set(snap["decisions"]) == {"new"}  # "old" was last used 4 runs ago


def test_reading_a_decision_keeps_it_alive():
    s = SnapshotStore()
    s.run = 1
    s.put_decision("k", decision())
    s.run = 4
    assert s.get_decision("k") is not None
    assert "k" in s.snapshot(set())["decisions"]


def test_snapshot_stays_under_512_kib():
    s = SnapshotStore()
    s.run = 2
    for i in range(3000):
        s.put_decision(f"k{i:05d}", decision("x" * 280))
    snap = s.snapshot(set())
    size = len(json.dumps(snap, separators=(",", ":")).encode())
    assert size <= MAX_SNAPSHOT_BYTES
    assert 0 < len(snap["decisions"]) < 3000


def test_oldest_decisions_are_dropped_first():
    s = SnapshotStore()
    s.run = 1
    for i in range(1500):
        s.put_decision(f"old{i}", decision("x" * 280))
    s.run = 2
    s.put_decision("fresh", decision("x" * 280))
    snap = s.snapshot(set())
    assert "fresh" in snap["decisions"]
    assert len(snap["decisions"]) < 1501


def test_docs_over_the_cap_are_kept_with_a_warning(caplog):
    s = SnapshotStore()
    s.put_doc(
        "big.md",
        status="checked",
        fingerprint={},
        checker="c",
        open_findings=[{"t": "x" * MAX_SNAPSHOT_BYTES}],
    )
    s.put_decision("k", decision())
    with caplog.at_level(logging.WARNING):
        snap = s.snapshot({"big.md"})
    assert "big.md" in snap["docs"] and not snap["decisions"]
    assert "exceed" in caplog.text


def test_memory_ignored_in_interactive_mode():
    s = SnapshotStore()
    s.put_doc("docs/a.md", status="checked", fingerprint={}, checker="c", open_findings=[])
    snap = s.snapshot({"docs/a.md"})
    assert SnapshotStore.from_snapshot(snap, mode="interactive").get_doc("docs/a.md") is None
    assert SnapshotStore.from_snapshot(snap, mode="scheduled").get_doc("docs/a.md") is not None


def test_garbage_and_version_mismatch_are_ignored(caplog):
    good = SnapshotStore().snapshot(set())
    for bad in ("junk", {**good, "version": 99}, {"version": 1}, {**good, "docs": {"a": 1}}):
        with caplog.at_level(logging.WARNING):
            store = SnapshotStore.from_snapshot(bad)
        assert store.run == 1 and store.get_doc("a") is None
    assert "ignoring memory snapshot" in caplog.text
