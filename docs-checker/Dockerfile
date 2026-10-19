# docs-checker: a kagent 1.0 BYO runtime image. Not built or pushed by this repo yet
# (see docs/superpowers/plans/2026-10-18-docs-checker-plan.md).
#
# Two choices come from kagent's own BYO samples (python/samples/langgraph/*/Dockerfile
# at v1.0.0-alpha11): Substrate's gVisor checkpoint/restore segfaulted processes linked
# against Debian trixie's glibc 2.41, so the base is bookworm (glibc 2.36); and it
# segfaulted the base image's system CPython on restore, so uv installs a managed
# (python-build-standalone) interpreter instead. homelab-agent's python:3.14-slim base
# is trixie and would hit the first problem.
#
# Pin this base by digest when the image is first built (the Harness pins the result
# by digest too; the CRD rejects tags).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# git: kagent-proto is not on PyPI and installs from the kagent repo at a pinned commit.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN uv venv --python 3.13 /app/.venv \
    && uv pip install --python /app/.venv/bin/python ".[kagent]" \
    && uv cache clean

# The BYO contract: A2A gRPC on 80 (KAGENT_PORT), /readyz on 8081.
EXPOSE 80 8081

# The Harness must repeat this as spec.workload.command (required for byo).
CMD ["/app/.venv/bin/docs-checker"]
