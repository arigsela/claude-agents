"""The ``docs-checker`` process in a kagent Substrate sandbox: a standard-library-only
front that answers the wake-up probe at once and passes A2A connections through to the
real server (``docs_checker.entry``), which it runs as a child on loopback ports.

Why it exists: kagent 1.0.0-alpha14 checkpoints a session with only /data after each
turn (snapshot scope ``data``), so the next turn in the same session starts the process
from scratch, and Substrate gives that restore about 5 s, wake-up probe included. The
server's imports (gRPC, a2a, kagent-core, LangGraph, the Anthropic SDK) take far longer
than that under gVisor. This module imports nothing outside the standard library and
starts in well under a second: it answers ``GET /readyz`` on the probe port, accepts A2A
connections on the runtime port, and splices each one, byte for byte (HTTP/2 included), to
the server once the server answers its own /readyz on loopback. The caller's request
waits in the connection meanwhile.

The golden boot is different: the snapshot every new session restores is taken as soon
as /readyz answers, so there the front answers only once the server is ready (a warm
snapshot, new sessions answer in seconds), or after ``GOLDEN_READY_CAP_S`` if the server
is slower, so that the snapshot is still taken rather than the template failing. The
golden actor is the one whose projected identity says atespace ``ate-golden``; with no
identity (outside Substrate) the front also waits for the server.

The front exits with the server's exit status, so a server that dies still ends the actor
visibly; SIGTERM and SIGINT are passed on to the server.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

DEFAULT_A2A_PORT = 80
READY_PORT = 8081
BACKEND_A2A_PORT = 18080
BACKEND_READY_PORT = 18081
GOLDEN_READY_CAP_S = 25.0  # inside the golden actor's 30 s wake-up probe
HOLD_S = 300.0  # how long an A2A connection waits for the server to come up
ATESPACE_FILE = "/run/kagent/identity/atespace"
GOLDEN_ATESPACE = "ate-golden"
LOOPBACK = "127.0.0.1"


def log(message: str) -> None:
    print(f"docs-checker front: {message}", flush=True)


def a2a_port(env: Mapping[str, str]) -> int:
    """The runtime port from ``KAGENT_CONFIG_JSON`` (``runtime.port``), else 80. A config
    the front cannot read is left for the server to report."""
    try:
        runtime = json.loads(env.get("KAGENT_CONFIG_JSON") or "{}").get("runtime") or {}
        return int(runtime.get("port") or DEFAULT_A2A_PORT)
    except (ValueError, TypeError, AttributeError):
        return DEFAULT_A2A_PORT


def is_golden(path: str = ATESPACE_FILE) -> bool:
    try:
        with open(path, encoding="utf-8") as identity:
            return identity.read().strip() == GOLDEN_ATESPACE
    except OSError:
        return True  # no Substrate identity: wait for the server, as a golden boot does


def listen(port: int, host: str | None = None) -> socket.socket:
    if host is None and socket.has_dualstack_ipv6():
        return socket.create_server(("::", port), family=socket.AF_INET6, dualstack_ipv6=True)
    return socket.create_server((host or "0.0.0.0", port))


def server_ready(port: int, timeout: float = 1.0) -> bool:
    """Whether the server's own /readyz answers 200 on loopback."""
    try:
        with socket.create_connection((LOOPBACK, port), timeout=timeout) as probe:
            probe.sendall(b"GET /readyz HTTP/1.1\r\nHost: localhost\r\n\r\n")
            return probe.recv(64).startswith(b"HTTP/1.1 200")
    except OSError:
        return False


@dataclass
class Front:
    golden: bool
    backend_a2a_port: int = BACKEND_A2A_PORT
    backend_ready_port: int = BACKEND_READY_PORT
    golden_cap_s: float = GOLDEN_READY_CAP_S
    hold_s: float = HOLD_S
    started: float = field(default_factory=time.monotonic)
    ready: threading.Event = field(default_factory=threading.Event)
    gone: threading.Event = field(default_factory=threading.Event)

    def answers_ready(self) -> bool:
        if self.gone.is_set():
            return False
        if not self.golden or self.ready.is_set():
            return True
        return time.monotonic() - self.started >= self.golden_cap_s

    def watch(self) -> None:
        """Poll the server's /readyz until it answers or the server is gone."""
        while not self.gone.is_set():
            if server_ready(self.backend_ready_port):
                self.ready.set()
                log(f"the server is ready after {time.monotonic() - self.started:.1f}s")
                return
            time.sleep(0.1)

    def serve_ready(self, sock: socket.socket) -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            threading.Thread(target=self._answer_ready, args=(conn,), daemon=True).start()

    def _answer_ready(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(5)
            try:
                line = conn.recv(1024).split(b"\r\n", 1)[0]
                if not line.startswith(b"GET /readyz "):
                    status = b"404 Not Found"
                else:
                    status = b"200 OK" if self.answers_ready() else b"503 Service Unavailable"
                conn.sendall(
                    b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                return

    def serve_a2a(self, sock: socket.socket) -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            threading.Thread(target=self._pass_through, args=(conn,), daemon=True).start()

    def _pass_through(self, client: socket.socket) -> None:
        with client:
            if not self.ready.wait(self.hold_s) or self.gone.is_set():
                return
            try:
                upstream = socket.create_connection((LOOPBACK, self.backend_a2a_port), timeout=10)
            except OSError:
                return
            with upstream:
                upstream.settimeout(None)
                client.settimeout(None)
                back = threading.Thread(target=_pump, args=(upstream, client), daemon=True)
                back.start()
                _pump(client, upstream)
                back.join()


def _pump(source: socket.socket, sink: socket.socket) -> None:
    """Copy until ``source`` ends, then end ``sink``'s write side (half-close)."""
    try:
        while data := source.recv(65536):
            sink.sendall(data)
    except OSError:
        pass
    finally:
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def run(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    a2a: socket.socket,
    ready: socket.socket,
    front: Front,
    on_signal: Callable[[int, Callable[[int, object], None]], object] = signal.signal,
) -> int:
    """Serve the probe and the A2A port, run the server, and return its exit status."""
    child_env = {
        **env,
        "DOCS_CHECKER_LISTEN_A2A": f"{LOOPBACK}:{front.backend_a2a_port}",
        "DOCS_CHECKER_LISTEN_READY": f"{LOOPBACK}:{front.backend_ready_port}",
    }
    child = subprocess.Popen(list(command), env=child_env)
    for signum in (signal.SIGTERM, signal.SIGINT):
        on_signal(signum, lambda received, _frame: child.send_signal(received))
    for target, args in (
        (front.serve_ready, (ready,)),
        (front.serve_a2a, (a2a,)),
        (front.watch, ()),
    ):
        threading.Thread(target=target, args=args, daemon=True).start()
    status = child.wait()
    front.gone.set()
    log(f"the server exited ({status})")
    return status if status >= 0 else 128 - status


def main() -> None:
    started = time.monotonic()
    env = dict(os.environ)
    golden = is_golden()
    port = a2a_port(env)
    log(f"starting (pid {os.getpid()}, golden boot: {golden}, A2A port {port})")
    a2a = listen(port)
    ready = listen(READY_PORT)
    front = Front(golden=golden, started=started)
    log(f"listening after {time.monotonic() - started:.2f}s")
    command = [sys.executable, "-m", "docs_checker.entry"]
    sys.exit(run(command, env=env, a2a=a2a, ready=ready, front=front))
