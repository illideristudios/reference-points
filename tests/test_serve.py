"""The long-lived engine: the CLI behind a Unix socket, so a call costs a request
instead of a Python start."""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from reference_points.serve import Engine, answers, socket_path

if TYPE_CHECKING:
    from collections.abc import Iterator


class _Unix(http.client.HTTPConnection):
    def __init__(self, path: Path) -> None:
        super().__init__("reference-points")
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(str(self._path))


def _post(path: Path, body: object) -> tuple[int, dict[str, object]]:
    conn = _Unix(path)
    conn.request("POST", "/", body=json.dumps(body))
    response = conn.getresponse()
    return response.status, json.loads(response.read())


@pytest.fixture
def private_dir() -> Iterator[Path]:
    # Not tmp_path: a socket path is capped near 100 bytes and pytest's is longer.
    directory = Path(tempfile.mkdtemp(dir="/tmp", prefix="rp"))
    directory.chmod(0o700)
    yield directory
    shutil.rmtree(directory)


def _run(argv: list[str], stdin: str) -> tuple[int, str, str]:
    return 0, f"ran {argv} on {stdin!r}", "warn"


def test_a_request_is_answered_with_the_cli_exit_code_and_output(private_dir: Path) -> None:
    path = private_dir / "a.sock"
    engine = Engine(path, _run, lambda: 0)
    thread = threading.Thread(target=engine.run, args=(5.0,))
    thread.start()
    try:
        status, body = _post(path, {"argv": ["turns", "t.jsonl"], "stdin": "hi"})
        assert status == 200
        assert body == {
            "exitCode": 0,
            "stdout": "ran ['turns', 't.jsonl'] on 'hi'",
            "stderr": "warn",
        }
    finally:
        engine.done = True
        _post(path, {"argv": []})  # wake the loop so it sees `done`
        thread.join()
        engine.server_close()


def test_a_malformed_request_is_refused_not_guessed_at(private_dir: Path) -> None:
    path = private_dir / "b.sock"
    engine = Engine(path, _run, lambda: 0)
    thread = threading.Thread(target=engine.run, args=(5.0,))
    thread.start()
    try:
        status, body = _post(path, {"stdin": "no argv"})
        assert status == 400
        assert "argv" in str(body["error"])
    finally:
        engine.done = True
        _post(path, {"argv": []})
        thread.join()
        engine.server_close()


def test_a_server_whose_code_changed_refuses_and_stops(private_dir: Path) -> None:
    path = private_dir / "c.sock"
    version = [1]
    engine = Engine(path, _run, lambda: version[0])
    thread = threading.Thread(target=engine.run, args=(5.0,))
    thread.start()
    try:
        assert _post(path, {"argv": ["x"]})[0] == 200
        version[0] = 2  # the engine's source was edited or updated
        status, body = _post(path, {"argv": ["x"]})
        assert status == 503
        assert "changed" in str(body["error"])
    finally:
        thread.join(timeout=5)
        engine.server_close()
    assert not thread.is_alive()  # it stopped by itself: the caller falls back, then restarts it


def test_an_idle_server_stops(private_dir: Path) -> None:
    engine = Engine(private_dir / "d.sock", _run, lambda: 0)
    engine.run(0.05)  # returns on its own once nothing arrives
    engine.server_close()
    assert engine.done


def test_answers_tells_a_live_server_from_a_stale_socket_file(private_dir: Path) -> None:
    path = private_dir / "e.sock"
    assert not answers(path)  # nothing there
    engine = Engine(path, _run, lambda: 0)
    assert answers(path)
    engine.server_close()
    assert path.exists()  # closing leaves the file behind, as a crash would
    assert not answers(path)
    Engine(path, _run, lambda: 0).server_close()  # and a new server simply replaces it


def test_a_directory_others_can_use_is_refused(private_dir: Path) -> None:
    private_dir.chmod(0o770)
    with pytest.raises(PermissionError, match="not private"):
        Engine(private_dir / "f.sock", _run, lambda: 0)


def test_a_socket_path_too_long_for_the_os_says_so(private_dir: Path) -> None:
    long_dir = private_dir / ("x" * 120)
    long_dir.mkdir(mode=0o700)
    with pytest.raises(OSError, match="too long"):
        Engine(long_dir / "g.sock", _run, lambda: 0)


def test_the_socket_path_is_short_private_and_stable_per_checkout() -> None:
    first = socket_path(Path("/some/checkout"))
    assert first == socket_path(Path("/some/checkout"))
    assert first != socket_path(Path("/another/checkout"))
    assert len(str(first)) < 100
