#!/usr/bin/env bash
# The AgentCore image smoke test: one real A2A JSON-RPC task through the built
# Dockerfile.agentcore image, end to end, with no AWS account and no key.
#
#   bash docs-checker/scripts/smoke_agentcore.sh
#   SMOKE_IMAGE=<uri>@sha256:<hex> bash docs-checker/scripts/smoke_agentcore.sh
#
# It builds docs-checker:agentcore (linux/arm64) and the image's build stage as a sidecar,
# then on a private --internal docker network:
#
#   sidecar (tests/smoke_stack.py agentcore-sidecar)       agent (the image under test)
#     agent-docs-mcp:8090  fake MCP, the four read tools  <---  DOCS_CHECKER_MCP_URL
#     the client: /ping, the card, SendMessage           --->  agent:9000
#
# The agent runs as AgentCore runs it (DOCS_CHECKER_RUNTIME=agentcore, session storage at
# /mnt/workspace) with static fake AWS credentials: its Gateway requests are SigV4 signed
# and the fake ignores the signature. Model calls replay tests/fixtures/cassettes-smoke
# (DOCS_CHECKER_REPLAY_DIR: nothing is sent). The last line is "smoke ok" or
# "smoke FAILED: <why>"; containers, the network and temp files are removed on exit.
#
# Environment:
#   SMOKE_IMAGE     test this image instead of building docs-checker:agentcore
#   SMOKE_TIMEOUT   seconds for each wait (default 300)
#   BUILDX          the buildx command (default: `docker buildx`, else colima's)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${SMOKE_IMAGE:-docs-checker:agentcore}"
sidecar_image="docs-checker:agentcore-smoke-sidecar"
timeout="${SMOKE_TIMEOUT:-300}"
run_id="$$-${RANDOM}"
net="docs-checker-agentcore-smoke-${run_id}"
sidecar="docs-checker-agentcore-smoke-sidecar-${run_id}"
agent="docs-checker-agentcore-smoke-agent-${run_id}"
stage="$(mktemp -d)"

if [ -z "${BUILDX:-}" ]; then
  if docker buildx version >/dev/null 2>&1; then
    BUILDX="docker buildx"
  elif colima ssh -- docker buildx version >/dev/null 2>&1; then
    BUILDX="colima ssh -- docker buildx" # colima's VM shares the daemon and $HOME
  else
    echo "smoke FAILED: no docker buildx (install docker-buildx, or set BUILDX)" >&2
    exit 1
  fi
fi

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  docker rm -f "$agent" "$sidecar" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -rf "$stage"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

fail() {
  echo "smoke FAILED: $*" >&2
  for name in "$sidecar" "$agent"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      echo "--- docker logs $name (last 60 lines)" >&2
      docker logs --tail 60 "$name" >&2 2>&1 || true
    fi
  done
  exit 1
}

# shellcheck disable=SC2086 # BUILDX is a command with arguments
build() { $BUILDX build --load --platform linux/arm64 --provenance=false -f "$here/Dockerfile.agentcore" "$@" "$here" >/dev/null; }

if [ -z "${SMOKE_IMAGE:-}" ]; then
  build -t "$image" || fail "docker build of $image failed"
  echo "ok: built $image (linux/arm64)"
fi
build --target build -t "$sidecar_image" || fail "docker build of the sidecar failed"
echo "ok: built $sidecar_image (the image's build stage)"

arch="$(docker image inspect -f '{{.Architecture}}' "$image")"
[ "$arch" = arm64 ] || fail "the image is $arch, not arm64"
entrypoint="$(docker image inspect -f '{{json .Config.Entrypoint}}' "$image")"
[ "$entrypoint" = '["/app/.venv/bin/docs-checker-agentcore"]' ] || fail "the entrypoint is $entrypoint"
echo "ok: arm64, entrypoint $entrypoint"

mkdir -p "$stage/sidecar/tests/fixtures" "$stage/smoke"
cp "$here/tests/__init__.py" "$here/tests/fake_controller.py" "$here/tests/smoke_stack.py" \
  "$stage/sidecar/tests/"
cp -R "$here/tests/fixtures/smoke-repo" "$stage/sidecar/tests/fixtures/"
cp -R "$here/tests/fixtures/cassettes-smoke" "$stage/smoke/cassettes"
find "$stage" -type d -exec chmod 755 {} + && find "$stage" -type f -exec chmod 644 {} +

docker network create --internal "$net" >/dev/null

docker create --name "$sidecar" --network "$net" --network-alias agent-docs-mcp \
  --platform linux/arm64 --workdir /smoke --entrypoint /app/.venv/bin/python \
  "$sidecar_image" -m tests.smoke_stack agentcore-sidecar --agent agent --timeout "$timeout" \
  >/dev/null
docker cp "$stage/sidecar/." "$sidecar:/smoke" >/dev/null

docker create --name "$agent" --network "$net" --network-alias agent --platform linux/arm64 \
  -e DOCS_CHECKER_RUNTIME=agentcore \
  -e DOCS_CHECKER_MCP_URL=http://agent-docs-mcp:8090/mcp \
  -e AWS_REGION=us-west-2 \
  -e AWS_ACCESS_KEY_ID=AKIDSMOKESMOKESMOKE0 \
  -e AWS_SECRET_ACCESS_KEY=smoke-not-a-secret \
  -e DOCS_CHECKER_REPLAY_DIR=/smoke/cassettes \
  -e ANTHROPIC_API_KEY=replay-only-never-sent \
  "$image" >/dev/null
docker cp "$stage/smoke/." "$agent:/smoke" >/dev/null

docker start "$sidecar" >/dev/null
started=$(date +%s)
docker start "$agent" >/dev/null
if ! docker wait "$sidecar" >/dev/null || [ "$(docker inspect -f '{{.State.ExitCode}}' "$sidecar")" != 0 ]; then
  fail "the sidecar's checks failed"
fi
docker logs "$sidecar" 2>&1 | grep -E '^(ok|sidecar):' || true
ping_line="$(docker logs "$agent" 2>&1 | grep -m1 'server.serve' || true)"
echo "ok: agent startup: ${ping_line:-no server.serve line} ($(($(date +%s) - started)) s wall to the end of the task)"
echo "smoke ok"
