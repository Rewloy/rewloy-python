"""A local stub of the API for the tests: a real HTTP server on 127.0.0.1 that records every request and answers with
whatever the test says. No network beyond the loopback interface, no credential."""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

from rewloy import Rewloy, UrllibTransport

SERIAL = "ABCD-EFGH-JKLM"
LOCATION = "0192f7c1-8b2e-7a31-9c1d-2e4f5a6b7c8d"
MERCHANT = "0192f7c1-0000-7000-8000-000000000001"
KEY = "rwk_abcdefghij_secretpart"
STAFF = "rws_staffsessiontoken"
HOLDER = "rwh_holdersessiontoken"


@dataclass
class Seen:
    method: str
    url: str
    headers: Dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.body)


class Ctx:
    """What a handler gets for request number ``n`` (1-based), and how it answers."""

    def __init__(self, n: int, seen: Seen, handler: BaseHTTPRequestHandler, stop: threading.Event) -> None:
        self.n = n
        self.req = seen
        self._h = handler
        self._stop = stop

    def raw(self, status: int, body: bytes = b"", headers: Optional[Mapping[str, str]] = None) -> None:
        h = self._h
        h.send_response(status)
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        if status != 204:
            h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        if status != 204:
            h.wfile.write(body)
        h.wfile.flush()

    def json(self, status: int, payload: object, headers: Optional[Mapping[str, str]] = None) -> None:
        merged = {"Content-Type": "application/json; charset=utf-8", "X-Request-Id": "req-0001", **(headers or {})}
        self.raw(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), merged)

    def stream(self, chunked: bool = True, headers: Optional[Mapping[str, str]] = None) -> "Sse":
        h = self._h
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        h.send_header("X-Request-Id", "req-live")
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        if chunked:
            h.send_header("Transfer-Encoding", "chunked")
        h.end_headers()
        h.wfile.flush()
        return Sse(h, chunked)

    def drop(self) -> None:
        """Closes the connection without answering."""
        self._h.close_connection = True
        try:
            self._h.request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._h.request.close()

    def hang(self, seconds: float = 10.0) -> None:
        """Never answers (until the stub is closed)."""
        self._stop.wait(seconds)

    def wait(self, seconds: float) -> bool:
        """Sleeps, cut short when the stub is closed; True while it is still open."""
        return not self._stop.wait(seconds)


class Sse:
    def __init__(self, handler: BaseHTTPRequestHandler, chunked: bool) -> None:
        self._h = handler
        self._chunked = chunked

    def write(self, data: Union[bytes, str]) -> bool:
        """Writes a piece of the stream; False when the client is gone."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        try:
            if self._chunked:
                self._h.wfile.write(f"{len(raw):x}\r\n".encode("ascii") + raw + b"\r\n")
            else:
                self._h.wfile.write(raw)
            self._h.wfile.flush()
            return True
        except OSError:
            return False

    def end(self) -> None:
        try:
            if self._chunked:
                self._h.wfile.write(b"0\r\n\r\n")
            self._h.wfile.flush()
        except OSError:
            pass
        self._h.close_connection = True


Handler = Callable[[Ctx], None]


class Stub:
    def __init__(self, handler: Handler) -> None:
        self.requests: List[Seen] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def handle_one(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                seen = Seen(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body)
                with stub._lock:
                    stub.requests.append(seen)
                    n = len(stub.requests)
                try:
                    handler(Ctx(n, seen, self, stub._stop))
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_one

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 64

            def handle_error(self, request: Any, client_address: Any) -> None:
                return

        self._server = Server(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()

    @property
    def last(self) -> Seen:
        return self.requests[-1]

    def close(self) -> None:
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def api_error(code: str, status: int, message: str, details: object = None) -> Dict[str, Any]:
    """An error body as the API writes it."""
    error: Dict[str, Any] = {
        "code": code, "message": message, "requestId": "req-body", "status": status,
        "docs": f"https://rewloy.com/gelistiriciler/hatalar#{code}",
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


class Sleeps:
    """A sleep that only records how long it was asked to wait."""

    def __init__(self) -> None:
        self.seconds: List[float] = []

    def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def make_client(stub: Optional[Stub] = None, **kwargs: Any) -> Rewloy:
    """A client for the stub with no proxy, and (unless given) the API key and a recording sleep."""
    options: Dict[str, Any] = {"base_url": stub.url} if stub is not None else {}
    if not any(k in kwargs for k in ("api_key", "staff_session", "holder_session", "anonymous")):
        options["api_key"] = KEY
    kwargs.pop("anonymous", None)
    options["transport"] = UrllibTransport(proxies={})
    options.setdefault("sleep", Sleeps())
    options.update(kwargs)
    return Rewloy(**options)


def loose(value: object) -> Any:
    """A typed answer seen as plain JSON, for comparing it with what a stub sent."""
    return value


def eventually(check: Callable[[], bool], seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return check()
