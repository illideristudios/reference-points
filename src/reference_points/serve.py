"""A long-lived engine for the mod: the CLI behind a Unix socket.

Starting Python and importing the engine costs about 0.1s, the labeling itself
about 0.01s, and the mod makes a call per prompt and per streamed block. Serving
the same ``main`` from one process leaves the request. One process is also what
lets ``__main__`` remember a transcript between calls and decode only what was
appended to it. There is no second
implementation to drift from the first: a request is an argv and some stdin, and
the answer is what the CLI would have printed.

I/O lives here and in ``__main__`` only; the callable that runs a request is
passed in, so this module knows nothing of the grammar.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import socketserver
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

IDLE_SECONDS = 1800.0  # a server nobody calls for half an hour stops
REQUEST_SECONDS = 5.0  # a client that connects and says nothing must not hold the server
_MAX_PATH = 100  # sun_path is 104 bytes on macOS, 108 on Linux


def socket_path(root: Path) -> Path:
    """Per user and per checkout, so two checkouts never share an engine (the other's
    code would answer) and a path stays short enough for the OS."""
    name = hashlib.sha256(str(root).encode()).hexdigest()[:10]
    return Path(tempfile.gettempdir()) / f"reference-points-{os.getuid()}" / f"{name}.sock"


def _private_dir(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError(
            f"{directory} is not private to you; remove it or chmod 700 it, "
            "because anyone who can reach the socket can make the engine read files as you"
        )


def answers(path: Path) -> bool:
    """A live server is listening there. A leftover socket file, as a crash leaves, is not."""
    probe = socket.socket(socket.AF_UNIX)
    try:
        probe.connect(str(path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


class _Handler(BaseHTTPRequestHandler):
    timeout = REQUEST_SECONDS

    def do_POST(self) -> None:
        engine = cast("Engine", self.server)
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            argv = [str(a) for a in request["argv"]]
            stdin = str(request.get("stdin", ""))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            self._reply(400, {"error": f"a request is JSON with an 'argv' list: {exc!r}"})
            return
        if engine.code_version() != engine.started_as:
            # Answering from the old code would be a silent wrong answer; refuse, and
            # let the caller run the CLI itself and start a fresh server.
            self._reply(503, {"error": "the engine changed on disk; this server is stopping"})
            engine.done = True
            return
        try:
            code, out, err = engine.runner(argv, stdin)
        except Exception as exc:
            # Say what broke; dropping the connection leaves the caller guessing.
            self._reply(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._reply(200, {"exitCode": code, "stdout": out, "stderr": err})

    def _reply(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Silent: a daemon has nowhere to write, and a request holds a prompt."""


class Engine(socketserver.UnixStreamServer):
    """Binds on construction. One request at a time: they are short, and the runner
    swaps process-wide streams, which concurrent requests would trample."""

    def __init__(
        self,
        path: Path,
        runner: Callable[[list[str], str], tuple[int, str, str]],
        code_version: Callable[[], int],
    ) -> None:
        _private_dir(path.parent)
        if len(os.fsencode(path)) > _MAX_PATH:
            raise OSError(f"socket path {path} is too long for the OS ({_MAX_PATH} bytes at most)")
        path.unlink(missing_ok=True)
        super().__init__(str(path), _Handler)
        path.chmod(0o600)
        self.path = path
        self.inode = path.stat().st_ino
        self.runner = runner
        self.code_version = code_version
        self.started_as = code_version()
        self.done = False

    def handle_timeout(self) -> None:
        self.done = True

    def release(self) -> None:
        """Stop listening and remove the socket file, unless a newer server has since
        bound the same path: that file is its, not ours."""
        self.server_close()
        try:
            if self.path.stat().st_ino == self.inode:
                self.path.unlink()
        except FileNotFoundError:
            pass

    def run(self, idle: float = IDLE_SECONDS) -> None:
        """Serve until the code changes or nothing arrives for ``idle`` seconds."""
        self.timeout = idle
        while not self.done:
            self.handle_request()


def serve(
    path: Path,
    runner: Callable[[list[str], str], tuple[int, str, str]],
    code_version: Callable[[], int],
    *,
    daemon: bool,
) -> None:
    """Returns at once when a server already answers, or, for a daemon, in the
    parent once the child is listening; otherwise serves until it stops."""
    if answers(path):
        return
    engine = Engine(path, runner, code_version)
    if daemon:
        if os.fork():
            engine.server_close()  # the child holds the listening socket now
            return
        os.setsid()
        os.chdir("/")
        null = os.open(os.devnull, os.O_RDWR)
        for stream in (0, 1, 2):
            os.dup2(null, stream)
    try:
        engine.run()
    finally:
        engine.release()
        if daemon:
            os._exit(0)  # the child must not fall back into the parent's CLI
