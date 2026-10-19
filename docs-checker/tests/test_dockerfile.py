"""The image's invariants, pinned without docker: a later edit to the Dockerfile or the
.dockerignore cannot quietly drop one. ``scripts/smoke.sh`` checks the built image itself.

- every base is pinned by digest (the Harness pins the image by digest; a tag can move);
- the install is the locked one, ``uv sync --locked --no-dev --extra kagent``;
- the final stage runs as a non-root user and starts ``/app/.venv/bin/docs-checker`` in
  exec form (the command a byo Harness repeats);
- the build context never holds .env files, the venv, the eval spend ledger, raw
  cassettes or caches (read with docker's own .dockerignore rules).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def instructions(text: str) -> list[tuple[str, str]]:
    """(INSTRUCTION, arguments) per instruction, continuation lines joined, comments out."""
    joined = re.sub(
        r"\\\n",
        " ",
        "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")),
    )
    found = []
    for line in joined.splitlines():
        if line.strip():
            keyword, _, rest = line.strip().partition(" ")
            found.append((keyword.upper(), " ".join(rest.split())))
    return found


def stages(text: str) -> list[list[tuple[str, str]]]:
    result: list[list[tuple[str, str]]] = []
    for keyword, args in instructions(text):
        if keyword == "FROM":
            result.append([])
        if result:
            result[-1].append((keyword, args))
    return result


DOCKER = instructions(DOCKERFILE.read_text())
FINAL = stages(DOCKERFILE.read_text())[-1]


def test_every_base_image_is_pinned_by_digest():
    named = {args.split()[-1] for k, args in DOCKER if k == "FROM" and " AS " in f" {args} "}
    bases = [args.split()[0] for k, args in DOCKER if k == "FROM"]
    external = [b for b in bases if b not in named]
    assert external
    for base in external:
        assert re.search(r"@sha256:[0-9a-f]{64}$", base), f"{base} is not pinned by digest"
    copied = [a for k, a in DOCKER if k == "COPY" and "--from=" in a]
    for args in copied:
        source = re.search(r"--from=(\S+)", args).group(1)
        assert source in named, f"COPY --from={source} names an image, not a pinned stage"


def test_the_install_is_the_locked_one_with_the_kagent_extra_and_no_dev():
    runs = [args for k, args in DOCKER if k == "RUN"]
    syncs = [sync.strip() for run in runs for sync in re.findall(r"uv sync[^&;]*", run)]
    assert syncs, "no uv sync"
    for sync in syncs:
        assert sync.startswith("uv sync --locked --no-dev --extra kagent"), sync
    assert "--no-install-project" not in syncs[-1]  # the project itself is installed
    assert not any("pip install" in run for run in runs)


def test_the_final_stage_runs_as_a_non_root_user():
    users = [args for k, args in FINAL if k == "USER"]
    assert users, "the final stage sets no USER (it would run as root)"
    user, _, group = users[-1].partition(":")
    assert user not in ("0", "root") and group not in ("0", "root"), users[-1]


def test_the_entrypoint_is_the_runtime_in_exec_form():
    entrypoints = [args for k, args in FINAL if k == "ENTRYPOINT"]
    assert entrypoints == ['["/app/.venv/bin/docs-checker"]']
    assert not [args for k, args in FINAL if k == "CMD"]  # no arguments added to it


# --- .dockerignore, with docker's rules ---------------------------------------------


def _regex(pattern: str) -> re.Pattern[str]:
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def excluded(path: str, ignore: str) -> bool:
    """Whether docker leaves ``path`` out of the context: patterns in order, ``!``
    re-includes, the last match wins, and a pattern matches a path or any of its parent
    directories (BuildKit's MatchesOrParentMatches)."""
    parts = path.split("/")
    candidates = ["/".join(parts[: n + 1]) for n in range(len(parts))]
    result = False
    for raw in ignore.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pattern = line[1:] if negate else line
        pattern = pattern.strip("/")
        if any(_regex(pattern).match(c) for c in candidates):
            result = not negate
    return result


IGNORE = DOCKERIGNORE.read_text()


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "src/docs_checker/.env",
        "src/docs_checker/prod.env",
        ".venv/bin/python",
        "src/.venv/lib/x.py",
        "evals/.spend.json",
        "evals/.spend.lock",
        "src/docs_checker/evals/.spend.json",
        "evals/cassettes-raw/abc.json",
        "src/docs_checker/evals/cassettes-raw/abc.json",
        "evals/cassettes/abc.json",
        "tests/fixtures/cassettes-smoke/abc.json",
        "tests/test_server.py",
        ".pytest_cache/v/cache/lastfailed",
        ".ruff_cache/0.8/x",
        "src/docs_checker/__pycache__/server.cpython-313.pyc",
        "src/docs_checker.egg-info/PKG-INFO",
    ],
)
def test_the_build_context_leaves_out(path):
    assert excluded(path, IGNORE), f"{path} would enter the build context"


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "src/docs_checker/server.py",
        "src/docs_checker/evals/replay.py",
    ],
)
def test_the_build_context_keeps_what_the_image_needs(path):
    assert not excluded(path, IGNORE)


def test_the_dockerignore_reader_follows_docker_rules():
    rules = "*\n!src/\n**/__pycache__\n"
    assert excluded("a.txt", rules) and excluded("dir/a.txt", rules)
    assert not excluded("src/a.py", rules) and not excluded("src/deep/a.py", rules)
    assert excluded("src/__pycache__/a.pyc", rules)
    assert not excluded("x/a", "x/*/b") and excluded("x/a/b/c", "x/*/b")


# --- Dockerfile.agentcore -------------------------------------------------------------

AGENTCORE_TEXT = (ROOT / "Dockerfile.agentcore").read_text()
AGENTCORE = instructions(AGENTCORE_TEXT)
AGENTCORE_FINAL = stages(AGENTCORE_TEXT)[-1]


def test_agentcore_dockerfile_arm64():
    assert "docker build --platform linux/arm64" in AGENTCORE_TEXT
    assert not any("amd64" in args for _, args in AGENTCORE)


def test_agentcore_dockerfile_port_9000():
    assert [args for k, args in AGENTCORE_FINAL if k == "EXPOSE"] == ["9000"]


def test_agentcore_entrypoint():
    entrypoints = [args for k, args in AGENTCORE_FINAL if k == "ENTRYPOINT"]
    assert entrypoints == ['["/app/.venv/bin/docs-checker-agentcore"]']
    assert not [args for k, args in AGENTCORE_FINAL if k == "CMD"]
    user = [args for k, args in AGENTCORE_FINAL if k == "USER"][-1]
    assert user == "65532:65532"


def test_agentcore_install_is_locked_with_its_extras():
    runs = [args for k, args in AGENTCORE if k == "RUN"]
    syncs = [s.strip() for run in runs for s in re.findall(r"uv sync[^&;]*", run)]
    assert syncs
    for sync in syncs:
        assert sync.startswith("uv sync --locked --no-dev --extra agentcore --extra kagent"), sync
    assert "--invalidation-mode unchecked-hash" in " ".join(runs)
    assert ("COPY", "profiles/ /app/profiles/") in AGENTCORE_FINAL


def test_agentcore_base_images_pinned_by_digest():
    named = {args.split()[-1] for k, args in AGENTCORE if k == "FROM" and " AS " in f" {args} "}
    for base in [args.split()[0] for k, args in AGENTCORE if k == "FROM"]:
        if base not in named:
            assert re.search(r"@sha256:[0-9a-f]{64}$", base), base


def test_agentcore_entrypoint_is_a_project_script():
    import tomllib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["docs-checker-agentcore"] == "docs_checker.agentcore:main"
