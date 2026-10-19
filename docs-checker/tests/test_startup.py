"""Startup in a Substrate sandbox: stdout is the only log the sandbox keeps, and a
golden actor gets 30 s to answer /readyz. These pin that the process says it
started before its heavy imports, that a startup error lands on stdout, and that a
checkpoint db that cannot be opened (or blocks) does not keep the agent from serving.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sys
from contextlib import asynccontextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import docs_checker
from docs_checker import entry, server
from tests.fakes import fake_settings


@pytest.fixture
def root_logging():
    """``server.main`` reconfigures the root logger; put it back afterwards."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_entry_says_it_started_before_importing_the_server(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(server, "main", lambda: calls.append("served"))
    entry.main()
    out = capsys.readouterr().out
    assert out.startswith("docs-checker: starting (pid ")
    assert "docs-checker: imports done in " in out
    assert calls == ["served"]


def test_entry_prints_an_import_failure_on_stdout_and_exits_1(monkeypatch, capsys):
    monkeypatch.delattr(docs_checker, "server", raising=False)
    monkeypatch.setitem(sys.modules, "docs_checker.server", None)  # importing it now raises
    with pytest.raises(SystemExit) as exited:
        entry.main()
    assert exited.value.code == 1
    out = capsys.readouterr().out
    assert "docs-checker: importing the server failed" in out
    assert "Traceback (most recent call last)" in out


def test_main_logs_a_startup_error_with_its_traceback_on_stdout(monkeypatch, capsys, root_logging):
    async def broken_serve():
        raise RuntimeError("the config is not an ADKConfig")

    monkeypatch.setattr(server, "serve", broken_serve)
    with pytest.raises(SystemExit) as exited:
        server.main()
    assert exited.value.code == 1
    out = capsys.readouterr().out
    assert "docs-checker stopped on an error" in out
    assert "RuntimeError: the config is not an ADKConfig" in out


async def test_a_db_that_opens_is_used(tmp_path, caplog):
    settings = dataclasses.replace(fake_settings(), checkpoint_db=str(tmp_path / "d" / "c.sqlite"))
    caplog.set_level(logging.INFO, logger="docs_checker.server")
    async with server.open_executor(settings) as executor:
        assert isinstance(executor._graph.checkpointer, AsyncSqliteSaver)
    assert "checkpoints and paused tasks in" in caplog.text


async def test_an_unwritable_data_dir_leaves_checkpoints_in_memory(tmp_path, caplog):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the data dir should be")
    settings = dataclasses.replace(fake_settings(), checkpoint_db=str(blocker / "c.sqlite"))
    async with server.open_executor(settings) as executor:
        assert isinstance(executor._graph.checkpointer, InMemorySaver)
    assert "checkpoints stay in memory for this process" in caplog.text
    assert str(blocker / "c.sqlite") in caplog.text


async def test_a_db_that_blocks_leaves_checkpoints_in_memory_in_time(monkeypatch, tmp_path, caplog):
    @asynccontextmanager
    async def blocking(path):
        await asyncio.Event().wait()  # SQLite stuck on the sandbox's file system
        yield None

    monkeypatch.setattr(server, "open_checkpointer", blocking)
    monkeypatch.setattr(server, "CHECKPOINT_OPEN_TIMEOUT_S", 0.05)
    settings = dataclasses.replace(fake_settings(), checkpoint_db=str(tmp_path / "c.sqlite"))
    async with asyncio.timeout(5):
        async with server.open_executor(settings) as executor:
            assert isinstance(executor._graph.checkpointer, InMemorySaver)
    assert "TimeoutError" in caplog.text
