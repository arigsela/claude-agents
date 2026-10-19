#!/usr/bin/env bash
# The image smoke test: one real A2A task through the built docs-checker image, end to end,
# with no Anthropic key and no cluster.
#
#   bash docs-checker/scripts/smoke.sh                                # the current context
#   DOCKER_CONTEXT=colima-dcbuild bash docs-checker/scripts/smoke.sh  # another one
#
# The docker CLI reads DOCKER_CONTEXT, so every docker command here builds and runs in the
# context the caller names; the script never switches the current context, never pushes
# and never prunes. It builds docs-checker:dev (linux/amd64) and the image's build stage as
# a sidecar, then on a private docker network:
#
#   sidecar (tests/smoke_stack.py)                     agent (the image under test)
#     controller:8083      fake kagent TaskStore  <---  runtime.control_plane_url
#     agent-docs-mcp:8090  fake agent-docs MCP    <---  the four read tools
#     the client           GET /readyz, A2A SendMessage  --->  docs-checker:8081, :80
#
# The agent gets what kagent gives it: KAGENT_CONFIG_JSON (printed by the sidecar), the
# placeholder ANTHROPIC_API_KEY, and identity files under /run/kagent/identity. Its model
# calls replay tests/fixtures/cassettes-smoke through DOCS_CHECKER_REPLAY_DIR (replay only:
# a request with no recording fails, nothing is sent). Each check prints "ok: ..."; the last
# line is "smoke ok". Containers, the network and temp files are removed on exit.
#
# Environment:
#   DOCKER_CONTEXT  docker context to use (default: the current one)
#   SMOKE_IMAGE     test this image (e.g. the pushed digest) instead of building
#                   docs-checker:dev; the sidecar is still built from this checkout
#   SMOKE_TIMEOUT   seconds for each wait: the agent's /readyz, then the task (default 300)
#   SMOKE_BUILD_TIMEOUT  seconds for each image build (default 1800)
#
# Every docker command is bounded (a build by SMOKE_BUILD_TIMEOUT, any other by 120 s, the
# waits by SMOKE_TIMEOUT), so the script always ends: "smoke ok" or "smoke FAILED: <why>".
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${SMOKE_IMAGE:-docs-checker:dev}"
sidecar_image="docs-checker:smoke-sidecar"
timeout="${SMOKE_TIMEOUT:-300}"
build_timeout="${SMOKE_BUILD_TIMEOUT:-1800}"
run_id="$$-${RANDOM}"
net="docs-checker-smoke-${run_id}"
sidecar="docs-checker-smoke-sidecar-${run_id}"
agent="docs-checker-smoke-agent-${run_id}"
stage="$(mktemp -d)"

# bounded SECONDS CMD...: CMD, stopped after SECONDS (macOS has no timeout(1)). The
# watchdog polls, so it ends within a second of CMD and leaves no sleeper behind.
bounded() {
  local limit=$1 status=0
  shift
  "$@" &
  local pid=$!
  (
    for ((i = 0; i < limit; i++)); do
      sleep 1
      kill -0 "$pid" 2>/dev/null || exit 0
    done
    echo "smoke: '$*' ran past ${limit} s; stopping it" >&2
    kill -TERM "$pid" 2>/dev/null
  ) >/dev/null &
  local watchdog=$!
  wait "$pid" || status=$?
  kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  return "$status"
}
dk() { bounded 120 docker "$@"; }

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  kill $(jobs -p) 2>/dev/null || true
  dk rm -f "$agent" "$sidecar" >/dev/null 2>&1 || true
  dk network rm "$net" >/dev/null 2>&1 || true
  rm -rf "$stage"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

fail() {
  echo "smoke FAILED: $*" >&2
  for name in "$sidecar" "$agent"; do
    if dk inspect "$name" >/dev/null 2>&1; then
      echo "--- docker logs $name (last 60 lines)" >&2
      dk logs --tail 60 "$name" >&2 2>&1 || true
    fi
  done
  exit 1
}

running() { [ "$(dk inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }

echo "smoke: docker context ${DOCKER_CONTEXT:-$(dk context show)}"

# --- the images --------------------------------------------------------------------------
if [ -z "${SMOKE_IMAGE:-}" ]; then
  bounded "$build_timeout" docker build --quiet --load --platform linux/amd64 -t "$image" \
    "$here" >/dev/null || fail "docker build of $image failed"
  echo "ok: built $image (linux/amd64)"
fi
bounded "$build_timeout" docker build --quiet --load --platform linux/amd64 --target build \
  -t "$sidecar_image" "$here" >/dev/null || fail "docker build of the sidecar failed"
echo "ok: built $sidecar_image (the image's build stage, for the sidecar)"

user="$(dk image inspect -f '{{.Config.User}}' "$image")"
case "${user%%:*}" in
  "" | 0 | root) fail "the image's user is '${user}': it would run as root" ;;
esac
echo "ok: the image's user is ${user}"
entrypoint="$(dk image inspect -f '{{json .Config.Entrypoint}}' "$image")"
[ "$entrypoint" = '["/app/.venv/bin/docs-checker"]' ] || fail "the entrypoint is ${entrypoint}"
echo "ok: the entrypoint is ${entrypoint}"

# --- what each container gets ------------------------------------------------------------
mkdir -p "$stage/sidecar/tests/fixtures" "$stage/smoke" "$stage/kagent/identity"
cp "$here/tests/__init__.py" "$here/tests/fake_controller.py" "$here/tests/smoke_stack.py" \
  "$stage/sidecar/tests/"
cp -R "$here/tests/fixtures/smoke-repo" "$stage/sidecar/tests/fixtures/"
cp -R "$here/tests/fixtures/cassettes-smoke" "$stage/smoke/cassettes"
session="$( (uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid) | tr 'A-Z' 'a-z')"
printf 'session-%s\n' "$session" >"$stage/kagent/identity/name"
printf 'kagent\n' >"$stage/kagent/identity/atespace"
printf 'smoke-actor-uid\n' >"$stage/kagent/identity/uid"
identity="kagent/session-${session}/smoke-actor-uid"
# docker cp keeps these modes, and a non-root runtime must read them.
find "$stage" -type d -exec chmod 755 {} + && find "$stage" -type f -exec chmod 644 {} +

dk network create "$net" >/dev/null

# --- the sidecar: the fake controller, the fake agent-docs server, the client --------------
dk create --name "$sidecar" --network "$net" \
  --network-alias controller --network-alias agent-docs-mcp \
  --platform linux/amd64 --workdir /smoke --entrypoint /app/.venv/bin/python \
  "$sidecar_image" -m tests.smoke_stack sidecar \
  --agent docs-checker --identity "$identity" --timeout "$timeout" >/dev/null
# --workdir made /smoke already: copy into it, not under it.
dk cp "$stage/sidecar/." "$sidecar:/smoke" >/dev/null
dk start "$sidecar" >/dev/null
deadline=$((SECONDS + timeout))
# grep reads all its input (no -q): an early exit would fail the pipe under pipefail.
until dk logs "$sidecar" 2>&1 | grep '^sidecar: ' >/dev/null; do
  running "$sidecar" || fail "the sidecar exited before it served"
  [ "$SECONDS" -lt "$deadline" ] || fail "the sidecar did not start in ${timeout} s"
  sleep 1
done
dk logs "$sidecar" 2>&1 | grep '^sidecar: '
config="$(dk exec "$sidecar" /app/.venv/bin/python -m tests.smoke_stack config)" ||
  fail "the sidecar could not print the runtime's config"

# --- the agent: the image under test, configured the way kagent configures it -------------
dk create --name "$agent" --network "$net" --network-alias docs-checker \
  --platform linux/amd64 --cap-drop ALL --security-opt no-new-privileges \
  -e KAGENT_CONFIG_JSON="$config" \
  -e ANTHROPIC_API_KEY=kagent-credential-injected \
  -e DOCS_CHECKER_REPLAY_DIR=/smoke/cassettes \
  "$image" >/dev/null
dk cp "$stage/kagent" "$agent:/run/kagent" >/dev/null
dk cp "$stage/smoke" "$agent:/smoke" >/dev/null
dk start "$agent" >/dev/null

running "$agent" || fail "the agent exited at startup"
uid="$(dk exec "$agent" id -u)" || fail "id -u failed in the agent"
pid1_uid="$(dk exec "$agent" sh -c "sed -n 's/^Uid:[[:space:]]*\([0-9]*\).*/\1/p' /proc/1/status")" ||
  fail "could not read the agent's process uid"
[ "$uid" != 0 ] && [ "$pid1_uid" != 0 ] || fail "the agent runs as uid ${pid1_uid} (exec: ${uid})"
echo "ok: the agent runs as uid ${pid1_uid} (id -u in the container: ${uid})"
cmdline="$(dk exec "$agent" sh -c "tr '\0' ' ' </proc/1/cmdline")" ||
  fail "could not read the agent's command line"
case "$cmdline" in
  *"/app/.venv/bin/docs-checker"*) ;;
  *) fail "the agent's process is '${cmdline}'" ;;
esac
echo "ok: the agent's process is ${cmdline% }"
dk exec "$agent" /app/.venv/bin/python -c \
  'import docs_checker.server, kagent.core, kagent.runtime.v1.task_store_pb2' >/dev/null 2>&1 ||
  fail "/app/.venv/bin/python cannot import docs_checker and kagent as uid ${uid}"
echo "ok: /app/.venv/bin/python imports docs_checker and kagent as uid ${uid}"

# --- the task: the sidecar waits for /readyz, sends it and checks what the controller holds
deadline=$((SECONDS + 2 * timeout + 60))
while running "$sidecar"; do
  running "$agent" || fail "the agent exited during the task"
  [ "$SECONDS" -lt "$deadline" ] || fail "the sidecar ran past $((2 * timeout + 60)) s"
  sleep 1
done
code="$(dk inspect -f '{{.State.ExitCode}}' "$sidecar")"
[ "$code" = 0 ] || fail "the sidecar's checks failed (exit ${code})"
dk logs "$sidecar" 2>&1 | grep '^ok: '

replay="$(dk logs "$agent" 2>&1 |
  sed -n 's/.*\(model replay is active: every response comes from [^;]*\).*/\1/p')" || true
replay="${replay%%$'\n'*}"
[ -n "$replay" ] || fail "the agent did not log that model replay is active"
echo "ok: the agent logged: ${replay}"
echo "smoke ok"
