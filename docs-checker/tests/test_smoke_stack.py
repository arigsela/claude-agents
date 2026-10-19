"""The image smoke test's task, in process (``tests/smoke_stack.py``).

The runtime as ``main`` builds it, on the fake controller and the agent-docs fake, with
every model response replayed from the committed cassettes through
``DOCS_CHECKER_REPLAY_DIR``. ``scripts/smoke.sh`` runs the same task against the built
image; this runs it in every test run, so a change that alters a model request fails here
first. Re-record with ``python -m tests.smoke_stack record`` (no API, no key).
"""

import asyncio

import pytest

from tests.smoke_stack import CASSETTES, SmokeFailure, run_in_process, wait_ready


async def test_the_smoke_task_completes_on_the_committed_cassettes(tmp_path):
    lines = await run_in_process(tmp_path, env={"DOCS_CHECKER_REPLAY_DIR": str(CASSETTES)})
    assert any("COMPLETED" in line for line in lines)
    assert any("stale, fixed to 0.7.1" in line for line in lines)
    assert any("all replayed (cash $0" in line for line in lines)


async def test_without_its_recordings_the_smoke_task_does_not_pass(tmp_path):
    # Every model call misses and fails; nothing falls through to the API.
    empty = tmp_path / "no-cassettes"
    empty.mkdir()
    with pytest.raises(SmokeFailure, match="did not check the doc: failed"):
        await run_in_process(tmp_path / "run", env={"DOCS_CHECKER_REPLAY_DIR": str(empty)})
    assert list(empty.iterdir()) == []


async def test_waiting_for_readyz_ends_when_a_listener_never_answers():
    # A listener that accepts and stays silent must not hold the smoke past its timeout.
    async def silent(reader, writer):
        await asyncio.sleep(60)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with asyncio.timeout(5):  # well past the 0.5 s it is given
            with pytest.raises(SmokeFailure, match="did not answer 200 in 0.5 s"):
                await wait_ready("127.0.0.1", port, 0.5)
    finally:
        server.close()
