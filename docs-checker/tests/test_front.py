"""docs_checker.front: answer the wake-up probe at once on a session's cold boot, hold A2A
connections until the server is up, wait for the server on the golden boot (capped), and
end with the server. The server here is a small stand-in child that listens where the
front tells it to (DOCS_CHECKER_LISTEN_A2A / _READY), after a delay."""

from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from docs_checker import front

FAKE_SERVER = textwrap.dedent("""
    import os, signal, socket, sys, threading, time

    def bind(spec):
        host, _, port = spec.rpartition(":")
        return socket.create_server((host, int(port)))

    time.sleep(float(sys.argv[1]))           # the server's imports
    if sys.argv[2] == "exit":
        sys.exit(3)
    ready, a2a = bind(os.environ["DOCS_CHECKER_LISTEN_READY"]), bind(os.environ["DOCS_CHECKER_LISTEN_A2A"])
    if sys.argv[2] == "never-ready":
        ready.close()

    def answer(sock):
        while True:
            conn, _ = sock.accept()
            with conn:
                conn.recv(1024)
                conn.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nOK")

    def echo(sock):
        while True:
            conn, _ = sock.accept()
            with conn:
                while data := conn.recv(1024):
                    conn.sendall(data.upper())

    if sys.argv[2] != "never-ready":
        threading.Thread(target=answer, args=(ready,), daemon=True).start()
    threading.Thread(target=echo, args=(a2a,), daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(1)
    """)


def free_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as probe:
        return probe.getsockname()[1]


def readyz(port: int) -> int:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
        conn.sendall(b"GET /readyz HTTP/1.1\r\n\r\n")
        return int(conn.recv(64).split()[1])


class Running:
    """``front.run`` in a thread, with the stand-in server as its child."""

    def __init__(self, tmp_path, *, golden: bool, delay: float, mode: str = "serve", **knobs):
        script = tmp_path / "server.py"
        script.write_text(FAKE_SERVER)
        self.a2a = front.listen(0, "127.0.0.1")
        self.ready = front.listen(0, "127.0.0.1")
        self.front = front.Front(
            golden=golden, backend_a2a_port=free_port(), backend_ready_port=free_port(), **knobs
        )
        self.handlers: dict[int, object] = {}
        self.status: int | None = None
        command = [sys.executable, str(script), str(delay), mode]

        def target():
            self.status = front.run(
                command,
                env={},
                a2a=self.a2a,
                ready=self.ready,
                front=self.front,
                on_signal=lambda signum, handler: self.handlers.__setitem__(signum, handler),
            )

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        while signal.SIGTERM not in self.handlers:
            time.sleep(0.01)

    @property
    def ready_port(self) -> int:
        return self.ready.getsockname()[1]

    @property
    def a2a_port(self) -> int:
        return self.a2a.getsockname()[1]

    def stop(self) -> int | None:
        self.handlers[signal.SIGTERM](signal.SIGTERM, None)
        self.thread.join(10)
        self.a2a.close()
        self.ready.close()
        return self.status


def test_a_session_boot_answers_ready_at_once_and_holds_a2a_until_the_server_is_up(tmp_path):
    running = Running(tmp_path, golden=False, delay=1.0)
    started = time.monotonic()
    assert readyz(running.ready_port) == 200  # before the server is up
    assert time.monotonic() - started < 0.5
    with socket.create_connection(("127.0.0.1", running.a2a_port), timeout=10) as conn:
        conn.sendall(b"ping")  # waits in the connection while the server boots
        assert conn.recv(16) == b"PING"
    assert time.monotonic() - started >= 0.9
    assert running.stop() == 0


def test_the_golden_boot_answers_ready_only_once_the_server_is(tmp_path):
    running = Running(tmp_path, golden=True, delay=1.0)
    assert readyz(running.ready_port) == 503
    assert running.front.ready.wait(10)
    assert readyz(running.ready_port) == 200
    running.stop()


def test_the_golden_boot_answers_after_its_cap_when_the_server_is_slow(tmp_path):
    running = Running(tmp_path, golden=True, delay=0.0, mode="never-ready", golden_cap_s=0.3)
    assert readyz(running.ready_port) == 503
    time.sleep(0.4)
    assert readyz(running.ready_port) == 200  # the snapshot is taken rather than failing
    running.stop()


def test_the_front_ends_with_the_servers_status(tmp_path):
    running = Running(tmp_path, golden=False, delay=0.0, mode="exit")
    running.thread.join(10)
    assert running.status == 3
    assert running.front.gone.is_set()
    assert readyz(running.ready_port) == 503  # never ready once the server is gone
    running.a2a.close()
    running.ready.close()


def test_the_runtime_port_comes_from_the_config():
    config = {"runtime": {"port": 8080}}
    assert front.a2a_port({"KAGENT_CONFIG_JSON": json.dumps(config)}) == 8080
    assert front.a2a_port({}) == 80
    assert front.a2a_port({"KAGENT_CONFIG_JSON": "{not json"}) == 80  # the server reports it


def test_the_golden_boot_is_read_from_the_projected_identity(tmp_path):
    atespace = tmp_path / "atespace"
    atespace.write_text("ate-golden\n")
    assert front.is_golden(str(atespace))
    atespace.write_text("kagent\n")
    assert not front.is_golden(str(atespace))
    assert front.is_golden(str(tmp_path / "missing"))  # outside Substrate: wait for the server


def test_the_front_imports_nothing_heavy():
    """It must start in well under the ~5 s a session restore allows, under gVisor."""
    probe = (
        "import sys, docs_checker.front; "
        "heavy = {'grpc', 'a2a', 'kagent', 'langgraph', 'langchain_core', 'anthropic', "
        "'pydantic', 'httpx', 'yaml'}; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in heavy))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


@pytest.mark.parametrize(
    ("spec", "expected"), [("", (None, 8081)), ("127.0.0.1:18081", ("127.0.0.1", 18081))]
)
def test_the_server_listens_where_the_front_says(spec, expected):
    import dataclasses

    from docs_checker.server import listen_ready
    from tests.fakes import fake_settings

    assert listen_ready(dataclasses.replace(fake_settings(), listen_ready=spec)) == expected
