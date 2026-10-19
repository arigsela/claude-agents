"""The offline drift demonstration (plan R2): the angle layer measured on the eval set.

Every test but the committed-doc one runs on fixtures (a tiny git repo in tmp, vectors
made up to give known angles); none calls Ollama or reads ``~/git/kubernetes``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx
import pytest

from docs_checker.config import Settings
from docs_checker.evals import curate, drift
from docs_checker.evals.curate import Repo
from docs_checker.gate import OllamaEmbedder
from tests.test_curate import CANARY_PATH, DEPLOYMENT, DOC, SERVICE, make_evals

PROJECT = Path(__file__).resolve().parents[1]


def test_percentile_interpolates_between_order_statistics():
    assert drift.percentile([30.0, 10.0, 20.0], 95) == pytest.approx(29.0)
    assert drift.percentile([10.0, 20.0], 50) == pytest.approx(15.0)
    assert drift.percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        drift.percentile([], 95)


def test_pr_rewrite_is_the_hunk_that_replaced_the_line_up_to_its_first_blank_line():
    old = ["intro", "", "stale line", "", "tail"]
    # The PR fixed line 3 and, in the same hunk, added a new section after it.
    new = ["intro", "", "fixed line", "  - detail", "", "### New", "body", "", "tail"]
    assert drift.pr_rewrite(old, new, 3) == drift.Rewrite(3, 3, ["fixed line", "  - detail"])
    assert drift.pr_rewrite(old, new, 1) is None  # the PR left it alone
    # A hunk can cover more lines than the one asked about; the caller decides.
    assert drift.pr_rewrite(["x", "a", "b", "y"], ["x", "A", "B", "y"], 2) == drift.Rewrite(
        2, 3, ["A", "B"]
    )


def test_paragraph_is_the_run_of_non_blank_lines_without_headings():
    lines = ["# Title", "p1", "p2", "", "- a", "- b", "## Next", "alone", ""]
    assert drift.paragraph(lines, 2, 2) == (2, 3)
    assert drift.paragraph(lines, 6, 6) == (5, 6)
    assert drift.paragraph(lines, 8, 8) == (8, 8)


def test_swap_changes_exactly_one_whole_value():
    assert drift.swap("  image: app:1.2.3@sha256:ab", "1.2.3", "1.2.2") == (
        "  image: app:1.2.2@sha256:ab"
    )
    with pytest.raises(ValueError):
        drift.swap("  name: weather-kitchen-tls", "weather-kitchen", "x")  # not a whole name
    with pytest.raises(ValueError):
        drift.swap("a: 1.2.3, b: 1.2.3", "1.2.3", "x")  # not exactly once


# --- the fix set, built from a fixture eval set ---------------------------------------


def write_labels(evals: Path) -> None:
    rows = [
        ("h-app", 10, "stale", f"{DEPLOYMENT}:10"),
        ("h-app", 11, "true", f"{SERVICE}:8"),
        ("live-app", 11, "stale", f"{SERVICE}:8"),
        ("planted-version", 10, "stale", f"{DEPLOYMENT}:10"),
        ("planted-deleted", 5, "missing", SERVICE),
        ("planted-deleted", 12, "missing", SERVICE),
        ("canary-app", 10, "true", f"{DEPLOYMENT}:10"),
    ]
    data = [{"instance": i, "line": n, "label": label, "source": s} for i, n, label, s in rows]
    curate.write_json(evals / "labels" / "eval-set.json", data)


CLAIMS = {
    ("h-app", 10): drift.ClaimSpec(
        "Runs image `app:1.2.2` in namespace `app`.", "image", ("app:1.2.2",), ("1.2.3", "1.2.2")
    ),
    ("planted-version", 10): drift.ClaimSpec(
        "Runs image `app:1.1.0` in namespace `app`.", "image", ("app:1.1.0",)
    ),
    ("canary-app", 10): drift.ClaimSpec(
        "Runs image `app:1.2.3` in namespace `app`.", "namespace", ("app",)
    ),
}


@pytest.fixture
def eval_set(tmp_path) -> tuple[Path, Repo]:
    evals, clone, _parent, _head = make_evals(tmp_path)
    curate.write_json(evals / "instances.json", curate.build(evals, clone))
    write_labels(evals)
    return evals, Repo(clone)


async def test_build_makes_good_and_bad_fixes_for_each_positive_with_a_clear_fix(eval_set):
    evals, repo = eval_set
    fixes, skipped = await drift.build(evals, repo, claims=CLAIMS)
    got = {(f.instance, f.lines, f.kind, f.variant): f for f in fixes}
    assert sorted(got) == sorted(
        [
            ("h-app", "10", "good", "pr-fix"),
            ("h-app", "10", "bad", "manifest-target"),
            ("h-app", "10", "bad", "paragraph-rewrite"),
            ("planted-version", "10", "good", "planted-restore"),
            ("planted-version", "10", "bad", "manifest-target"),
            ("planted-version", "10", "bad", "paragraph-rewrite"),
            ("canary-app", "10", "bad", "canary-injected"),
        ]
    )
    good = got["h-app", "10", "good", "pr-fix"]
    assert good.split == "holdout" and good.target == f"{DOC}:10"
    assert "`app:1.2.3`" in good.action and "`app:1.2.2`" in good.action
    # The intent is the claim and where its evidence is (the gate node's own words),
    # the same for every fix of one claim: only the action differs.
    assert "Runs image `app:1.2.2` in namespace `app`." in good.intent
    # ±3 lines around the label's evidence line, clamped as evidence.windows_for does.
    assert f"evidence: {DEPLOYMENT}:7-11" in good.intent
    for variant in ("manifest-target", "paragraph-rewrite"):
        assert got["h-app", "10", "bad", variant].intent == good.intent

    manifest = got["h-app", "10", "bad", "manifest-target"]
    assert manifest.target == f"{DEPLOYMENT}:10"
    assert manifest.action.startswith(f"In {DEPLOYMENT}, replace lines 10-10 ")
    assert "app:1.2.2" in manifest.action  # the manifest patched to the stale doc
    paragraph = got["h-app", "10", "bad", "paragraph-rewrite"]
    assert paragraph.target == f"{DOC}:10-12"
    planted = got["planted-version", "10", "good", "planted-restore"]
    assert planted.split == "dev" and "app:1.2.3" in planted.action
    assert "app:1.1.0" in got["planted-version", "10", "bad", "manifest-target"].action
    assert got["canary-app", "10", "bad", "canary-injected"].target == f"{CANARY_PATH}:10"

    # The rules layer (what production runs) on each fix.
    assert good.rules == planted.rules == "allow"
    assert manifest.rules == paragraph.rules == "refuse (target)"
    assert got["canary-app", "10", "bad", "canary-injected"].rules == "refuse (containment)"

    assert {(s.instance, s.line): s.reason for s in skipped} == {
        ("live-app", 11): drift.NO_COMMITTED_FIX,
        ("planted-deleted", 5): drift.DELETED_SOURCE,
        ("planted-deleted", 12): drift.DELETED_SOURCE,
    }


async def test_the_rules_column_comes_from_the_production_fix_gate(eval_set, monkeypatch):
    evals, repo = eval_set
    built: list[Settings] = []
    real = drift.build_fix_gate

    def spy(settings: Settings):
        built.append(settings)
        return real(settings)

    monkeypatch.setattr(drift, "build_fix_gate", spy)
    fixes, _skipped = await drift.build(evals, repo, claims=CLAIMS)
    assert len(built) == len(fixes) and all(isinstance(s, Settings) for s in built)


async def test_build_needs_the_claim_of_every_positive_it_fixes(eval_set):
    evals, repo = eval_set
    with pytest.raises(ValueError, match="h-app line 10"):
        await drift.build(evals, repo, claims={})


# --- angles, thresholds and the page --------------------------------------------------


def demo_cache(rows: list[tuple[str, str, float]]) -> drift.DriftCache:
    """One fix per (split, kind, angle): its intent and action embed ``angle`` apart."""
    fixes, vectors = [], {}
    for n, (split, kind, angle) in enumerate(rows):
        fix = drift.DriftFix(
            instance=f"i{n}",
            lines=str(n + 1),
            split=split,
            kind=kind,
            variant="pr-fix" if kind == "good" else "manifest-target",
            target=f"doc.md:{n + 1}",
            intent=f"intent {n}",
            action=f"action {n}",
            rules="allow",
        )
        fixes.append(fix)
        rad = math.radians(angle)
        vectors[drift.text_key(fix.intent)] = [1.0, 0.0]
        vectors[drift.text_key(fix.action)] = [math.cos(rad), math.sin(rad)]
    return drift.DriftCache(model="test-embed", fixes=fixes, skipped=[], vectors=vectors)


def test_thresholds_come_from_the_dev_rows_only():
    cache = demo_cache(
        [
            ("dev", "good", 10.0),
            ("dev", "good", 20.0),
            ("dev", "good", 30.0),
            ("dev", "bad", 60.0),
            ("dev", "bad", 50.0),
            ("holdout", "good", 80.0),  # would raise the ask threshold
            ("holdout", "bad", 5.0),  # would lower the refuse threshold
        ]
    )
    result = drift.measure(cache)
    assert result.ask_at == pytest.approx(29.0)
    assert result.refuse_at == pytest.approx(50.0)
    assert result.separated
    angles = [round(angle, 6) for _fix, angle in result.rows]
    assert angles == [10.0, 20.0, 30.0, 60.0, 50.0, 80.0, 5.0]
    assert result.decisions() == ["allow", "allow", "ask", "refuse", "refuse", "refuse", "allow"]


def test_the_page_says_not_deployed_and_marks_the_holdout():
    page = drift.render(
        demo_cache([("dev", "good", 10.0), ("dev", "bad", 60.0), ("holdout", "good", 12.0)])
    )
    assert "Not deployed; the deployed agent ships the rules gate." in page
    assert "**θ1 < θ2 holds** (10.00° < 60.00°, a margin of 50.00°)." in page
    assert "Every angle here lies between 10.00° and 60.00°" in page
    assert "= **10.00°**" in page and "= **60.00°**" in page
    assert "rest on 1 good and 1 bad dev fixes" in page
    assert "refuses 0 of 1 bad fixes and 0 of 2 good fixes" in page
    # Composed, rules first: the angle refuses the bad fix the rules let through and
    # asks about both good ones (10.00° is not under θ1 = 10.00°).
    assert (
        "Composed, the rules first and the angle only on what they allow: of the 1 bad "
        "fixes the rules refuse 0, the angle refuses 1 more and asks about 0, and 0 would "
        "pass; of the 2 good fixes the rules refuse 0, the angle refuses 0 more and asks "
        "about 2, and 0 pass."
    ) in page
    assert "| `i2:3` | holdout | good |" in page
    assert "`test-embed`" in page


def test_the_page_reports_thresholds_that_do_not_separate():
    cache = demo_cache([("dev", "good", 10.0), ("dev", "good", 40.0), ("dev", "bad", 25.0)])
    result = drift.measure(cache)
    assert not result.separated and result.decisions() == ["—", "—", "—"]
    page = drift.render(cache)
    assert "θ1 < θ2 does not hold" in page
    assert "`i2:3` (manifest-target, 25.00°)" in page  # the bad fix under θ1 is named
    assert "the angle adds no decision" in page


class StubEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]


async def test_embed_missing_embeds_only_new_texts_and_drops_unused_ones():
    cache = demo_cache([("dev", "good", 10.0), ("dev", "bad", 60.0)])
    kept = drift.text_key("intent 0")
    cache.vectors["stale"] = [0.0, 1.0]
    del cache.vectors[drift.text_key("action 1")]
    embedder = StubEmbedder()
    updated = await drift.embed_missing(cache, embedder)
    assert embedder.calls == [["action 1"]]
    assert set(updated.vectors) == {
        drift.text_key(t) for t in ("intent 0", "action 0", "intent 1", "action 1")
    }
    assert updated.vectors[kept] == [1.0, 0.0]


def test_the_cli_writes_the_page_from_the_cache_and_needs_every_vector(tmp_path, capsys):
    cache = demo_cache([("dev", "good", 10.0), ("dev", "bad", 60.0)])
    path = tmp_path / "embeddings.json"
    drift.save(cache, path)
    out = tmp_path / "demo.md"
    assert drift.main(["--out", str(out), "--embeddings", str(path)]) == 0
    assert out.read_text() == drift.render(cache)

    del cache.vectors[drift.text_key("action 1")]
    drift.save(cache, path)
    assert drift.main(["--out", str(tmp_path / "other.md"), "--embeddings", str(path)]) == 2
    assert "--refresh" in capsys.readouterr().err
    assert not (tmp_path / "other.md").exists()


def fake_ollama(monkeypatch, handle) -> list[list[str]]:
    """The CLI's embedder, talking to ``handle`` instead of Ollama; returns its batches."""
    batches: list[list[str]] = []

    def record(request: httpx.Request) -> httpx.Response:
        batches.append(json.loads(request.content)["input"])
        return handle(request)

    transport = httpx.MockTransport(record)
    monkeypatch.setattr(drift, "CLAIMS", CLAIMS)  # the fixture eval set's claims
    monkeypatch.setattr(
        drift,
        "OllamaEmbedder",
        lambda url, model, **kwargs: OllamaEmbedder(url, model, transport=transport, **kwargs),
    )
    return batches


def refresh_args(eval_set, tmp_path) -> list[str]:
    evals, repo = eval_set
    return [
        "--out",
        str(tmp_path / "demo.md"),
        "--embeddings",
        str(tmp_path / "embeddings.json"),
        "--refresh",
        "--clone",
        str(repo.clone),
        "--evals-dir",
        str(evals),
    ]


def test_the_cli_refreshes_from_the_clone_and_embeds_in_batches(eval_set, tmp_path, monkeypatch):
    def vectors(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [[float(len(t)), 1.0] for t in texts]})

    batches = fake_ollama(monkeypatch, vectors)
    assert drift.main(refresh_args(eval_set, tmp_path)) == 0
    cache = drift.load(tmp_path / "embeddings.json")
    assert len(cache.fixes) == 7 and len(cache.skipped) == 3
    assert sorted(t for batch in batches for t in batch) == sorted(drift.texts(cache))
    assert max(len(batch) for batch in batches) <= drift.EMBED_BATCH
    assert (tmp_path / "demo.md").read_text() == drift.render(cache)
    # A second refresh embeds nothing: every vector is cached.
    batches.clear()
    assert drift.main(refresh_args(eval_set, tmp_path)) == 0 and batches == []


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (lambda: httpx.Response(200, json={"embeddings": [[1.0], "x"]}), "EmbeddingError"),
        (lambda: httpx.Response(200, json=["not", "an", "object"]), "EmbeddingError"),
        (lambda: httpx.Response(500, json={"error": "model failed"}), "HTTPStatusError"),
    ],
)
def test_the_cli_reports_a_bad_embedding_reply_and_writes_nothing(
    eval_set, tmp_path, monkeypatch, capsys, reply, error
):
    fake_ollama(monkeypatch, lambda request: reply())
    assert drift.main(refresh_args(eval_set, tmp_path)) == 1
    assert f"error: {error}" in capsys.readouterr().err
    assert not (tmp_path / "embeddings.json").exists() and not (tmp_path / "demo.md").exists()


def test_the_cli_names_a_timeout(eval_set, tmp_path, monkeypatch, capsys):
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)  # httpx gives it no message

    fake_ollama(monkeypatch, slow)
    assert drift.main(refresh_args(eval_set, tmp_path)) == 1
    assert "error: ReadTimeout" in capsys.readouterr().err


def test_the_committed_page_is_what_its_committed_embeddings_give():
    cache = drift.load(PROJECT / "docs" / "drift-embeddings.json")
    page = (PROJECT / "docs" / "drift-demo.md").read_text()
    assert page == drift.render(cache)
    assert json.loads((PROJECT / "docs" / "drift-embeddings.json").read_text())["model"] == (
        "nomic-embed-text"
    )
