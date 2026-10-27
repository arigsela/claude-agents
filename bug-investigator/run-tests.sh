#!/usr/bin/env bash
# Run the app's tests in a throwaway container, never on the runner itself.
#
# The container gets a copy of the checkout without .git (mounted read-only), no network, no
# environment from the runner (so no tokens or API keys), no capabilities, user nobody, a read-only
# root and a small tmpfs /tmp. The copy is deleted afterwards. This is the only command the fix agent
# may run besides `git diff` / `git status`, and fix-check runs the tests through it too.
#
#   run-tests.sh <app-dir> <test command...>     run the tests; exit code = the tests' exit code
#   run-tests.sh --pull                         pull the pinned image (before Claude starts)
#   run-tests.sh --dry-run <app-dir> <cmd...>   print the docker command and run nothing
set -euo pipefail

IMAGE="python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f"
TIMEOUT=300

if [ "${1:-}" = --pull ]; then
  docker pull --quiet "$IMAGE" >/dev/null
  echo "pulled $IMAGE"
  exit 0
fi
dry=0
if [ "${1:-}" = --dry-run ]; then dry=1; shift; fi
if [ $# -lt 2 ]; then
  echo "usage: run-tests.sh [--dry-run] <app-dir> <test command...>" >&2
  exit 64
fi
app="$1"
shift
name="bug-investigator-tests-$$-$RANDOM"

if [ "$dry" = 1 ]; then
  copy="<copy>"
else
  [ -d "$app" ] || { echo "run-tests.sh: no such directory: $app" >&2; exit 64; }
  copy="$(mktemp -d "${TMPDIR:-/tmp}/bug-investigator-tests.XXXXXX")"
  cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    rm -rf "$copy"
  }
  trap cleanup EXIT
  # Everything but git internals and the deploy checkout, readable by the container's user.
  tar -C "$app" --exclude=.git --exclude=./.bug-investigator-deploy -cf - . | tar -C "$copy" -xf -
  chmod -R a+rX "$copy"
fi

cmd=(docker run --rm --name "$name" --pull never --network none --read-only
  --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 --cap-drop ALL --security-opt no-new-privileges
  --user 65534:65534 --env-file /dev/null -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp
  --memory 2g --pids-limit 512 -v "$copy:/w:ro" -w /w "$IMAGE" "$@")

if [ "$dry" = 1 ]; then
  printf '%q ' "${cmd[@]}"
  echo
  exit 0
fi

status=0
timeout --kill-after=15 "$TIMEOUT" "${cmd[@]}" || status=$?
if [ "$status" = 124 ]; then echo "run-tests.sh: the tests timed out after ${TIMEOUT}s" >&2; fi
exit "$status"
