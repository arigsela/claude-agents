import hashlib
from pathlib import Path

import pytest

from docs_checker import prompts
from docs_checker.config import load_settings
from docs_checker.profile import PROFILE_SOURCE_LINE, doc_meta, load_profile, parse_profile
from docs_checker.scope import discover
from tests.test_scope import make_tree, reader_of

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
REPO = "chghealthcare/chg-infra-opentofu-bedrock"
PROFILE_TEXT = f"""\
repo: {REPO}
domain: an OpenTofu module
docs:
  docs/USAGE.md:
    - path: variables.tf
    - dir: .github/workflows
  docs/BEDROCK-DEVELOPER-RUNBOOK.md:
    - path: iam.tf
"""


def profile():
    return parse_profile(PROFILE_TEXT, repo=REPO)


def test_profile_sources_replace_front_matter():
    meta = doc_meta("docs/USAGE.md", "# no front matter\n", profile())
    assert [(s.kind, s.value) for s in meta.sources] == [
        ("path", "variables.tf"),
        ("dir", ".github/workflows"),
    ]
    assert meta.sources[0].line == PROFILE_SOURCE_LINE
    assert meta.body_start == 1


def test_a_doc_outside_the_profile_keeps_its_front_matter():
    text = "---\nsources:\n  - main.tf\n---\nbody\n"
    meta = doc_meta("README.md", text, profile())
    assert [s.value for s in meta.sources] == ["main.tf"]


@pytest.mark.parametrize(
    "bad, match",
    [
        ("docs/README.md", "documentation"),
        ("CHANGELOG.md", "documentation"),
    ],
)
def test_profile_rejects_doc_as_source(bad, match):
    text = PROFILE_TEXT.replace("path: iam.tf", f"path: {bad}")
    with pytest.raises(ValueError, match=match):
        parse_profile(text, repo=REPO)


def test_profile_rejects_another_repo_and_empty_sources():
    with pytest.raises(ValueError, match="DOCS_CHECKER_REPO"):
        parse_profile(PROFILE_TEXT, repo="arigsela/kubernetes")
    with pytest.raises(ValueError, match="lists no sources"):
        parse_profile(PROFILE_TEXT.replace("    - path: iam.tf\n", "    []\n"), repo=REPO)


async def test_discover_uses_profile_docs(tmp_path):
    repo, commit = make_tree(tmp_path, {"variables.tf": "x\n"})
    docs, truncated = await discover(reader_of(repo, commit), max_docs=10, profile=profile())
    assert docs == ["docs/USAGE.md", "docs/BEDROCK-DEVELOPER-RUNBOOK.md"]
    assert truncated is False


async def test_discover_with_a_profile_honours_max_docs(tmp_path):
    repo, commit = make_tree(tmp_path, {"variables.tf": "x\n"})
    docs, truncated = await discover(reader_of(repo, commit), max_docs=1, profile=profile())
    assert docs == ["docs/USAGE.md"] and truncated is True


GOLDEN = {
    "intake": "8a5a1a385529887714bc7f49770b64f30340f388cc6889cd77ea74582e7be4d4",
    "extract": "c3775939d6b39487b31528efa1f04adbf7f01390f8d05e7d9279f7c37a370b2b",
    "judge": "623585cf182f250f7790e7c605590591f91b3333a9f883c8734e1aacf1dafdd8",
    "fix": "5cec361ff8e79d1e2355ed09be4c6b658840a5d4865748be07260fe51497ada7",
    "report": "82ccc2683d080374f3b6b621961af8b5f2ad3eef1ac0047bca615140b1b35ca4",
}


def test_prompts_unchanged_without_profile():
    for node, digest in GOLDEN.items():
        assert hashlib.sha256(prompts.system_text(node, None).encode()).hexdigest() == digest


def test_profile_prompts_name_the_repo_and_domain():
    p = profile()
    extract = prompts.system_text("extract", p)
    assert REPO in extract and "an OpenTofu module or another configuration file" in extract
    for node in ("intake", "extract", "judge"):
        text = prompts.system_text(node, p)
        assert "arigsela/kubernetes" not in text and "Kubernetes manifest" not in text, node


@pytest.mark.parametrize("name", ["chg-infra-opentofu-bedrock", "chg-infra-opentofu-opensearch"])
def test_shipped_profiles_load(name):
    loaded = load_profile(str(PROFILES / f"{name}.yaml"), repo=f"chghealthcare/{name}")
    assert loaded.docs and all(loaded.docs.values())


def test_settings_load_the_profile():
    settings = load_settings(
        {
            "DOCS_CHECKER_REPO": "chghealthcare/chg-infra-opentofu-bedrock",
            "DOCS_CHECKER_PROFILE": str(PROFILES / "chg-infra-opentofu-bedrock.yaml"),
        }
    )
    assert "docs/USAGE.md" in settings.profile.docs
    assert load_settings({}).profile is None


def test_refusal_names_the_profile_repo():
    from docs_checker.graph import REFUSAL, refusal_text

    assert refusal_text(None) == REFUSAL  # byte-identical without a profile
    text = refusal_text(profile())
    assert REPO in text and "arigsela/kubernetes" not in text and "manifests" not in text
