# docs-checker: a kagent 1.0 BYO runtime image (kagent v1.0.0-alpha14).
#
#   docker build --platform linux/amd64 -t docs-checker:dev docs-checker
#   bash docs-checker/scripts/smoke.sh     # one real A2A task, end to end
#
# Two choices come from kagent's own BYO samples (python/samples/langgraph/*/Dockerfile)
# and its runtime image (python/Dockerfile) at v1.0.0-alpha14: Substrate's gVisor
# checkpoint/restore segfaulted processes linked against Debian trixie's glibc 2.41, so
# the base is bookworm (glibc 2.36); and it segfaulted the base image's system CPython on
# restore, so uv installs a managed (python-build-standalone) interpreter instead.
# homelab-agent's python:3.14-slim base is trixie and would hit the first problem.
#
# Two stages, the layout of kagent's runtime image: the build stage has git (kagent-proto
# is not on PyPI and installs from the kagent repo at a pinned commit) and uv; the final
# stage gets only the managed interpreter (/python) and the venv (/app/.venv), at the
# same paths, so the venv's interpreter link still resolves. Neither git nor uv ships.
#
# Bases are pinned by digest (the multi-arch index, resolved by a pull on 2026-10-19);
# the Harness pins the result by digest too (the CRD rejects tags).

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv-bin

FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS build
COPY --from=uv-bin /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# A managed 3.13 only (never a system Python), installed under /python; bytecode
# compiled at install time, so the read-only venv starts without writing .pyc files.
ENV UV_PYTHON=3.13 \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

WORKDIR /app
# Dependencies first (their layer survives a source change), then the project itself,
# installed as a wheel (--no-editable): the final stage has no /app/src.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra kagent --no-editable --no-install-project
COPY README.md ./
COPY src/ ./src/
# uv's own lock and scratch files under /python (the lock is world-writable) stay behind.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra kagent --no-editable \
    && rm -rf /python/.lock /python/.temp

FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 docs-checker \
    && useradd --uid 65532 --gid 65532 --create-home --home-dir /home/docs-checker \
        --shell /usr/sbin/nologin docs-checker \
    && mkdir -p /data/docs-checker \
    && chown -R 65532:65532 /data
COPY --from=build /python /python
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

# The uid kagent's own runtime image uses. /data is where Substrate mounts the durable
# directory it snapshots (the checkpoint db lives there); the image's own /data, owned
# by this user, serves a plain `docker run`.
USER 65532:65532
WORKDIR /home/docs-checker

# The BYO contract: A2A gRPC on 80 (runtime.port), /readyz on 8081.
EXPOSE 80 8081

# The Harness repeats this as spec.workload.command (required for byo).
ENTRYPOINT ["/app/.venv/bin/docs-checker"]
