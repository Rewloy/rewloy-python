"""How the client talks HTTP.

The client needs two things from a transport: send a request and hand back the whole answer (``send``), and open a
request whose body is read piece by piece (``open_stream``, for server-sent events). ``UrllibTransport``, the
default, does both with the standard library only. ``rewloy.httpx_transport`` has one on ``httpx`` (connection
pooling, HTTP/2, proxies), and anything with these methods works: a fake for tests, an instrumented session.

A transport never retries, never follows a redirect and never raises for an HTTP status: an error answer is an
answer. It raises ``TransportTimeout`` when the time ran out and ``TransportError`` when there was no answer.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Protocol

from .common import Headers

#: How much of an answer is read at a time.
CHUNK = 64 * 1024


class TransportError(Exception):
    """No answer arrived: the connection could not be made, or broke."""


class TransportTimeout(TransportError):
    """No answer arrived in time."""


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: Optional[bytes]
    #: Seconds allowed for this attempt. For ``send``: from the start until the whole answer has arrived. For
    #: ``open_stream``: until the answer's headers have. ``None``: no limit.
    timeout: Optional[float]
    #: ``open_stream`` only: seconds of silence after which the connection counts as dead. ``None``: no limit.
    idle_timeout: Optional[float] = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    reason: str
    headers: Headers
    body: bytes


class StreamResponse(Protocol):
    """An answer whose body is still to be read."""

    @property
    def status(self) -> int: ...

    @property
    def reason(self) -> str: ...

    @property
    def headers(self) -> Headers: ...

    def read(self, size: int = ...) -> bytes:
        """The next piece of the body (at least one byte, at most ``size``); ``b""`` at its end. Raises
        ``TransportTimeout`` after ``idle_timeout`` seconds without a byte, ``TransportError`` when the connection
        breaks."""
        ...

    def close(self) -> None:
        """Closes the connection. Safe to call from another thread, which makes a blocked ``read`` return or raise."""
        ...


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...

    def open_stream(self, request: HttpRequest) -> StreamResponse: ...

    def close(self) -> None: ...


def _socket_of(response: Any) -> Optional[socket.socket]:
    """The socket under an ``http.client`` response, when the standard library keeps it where it does today."""
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    return sock if isinstance(sock, socket.socket) else None


def _set_timeout(response: Any, seconds: Optional[float]) -> None:
    """Best effort: ``urllib`` fixes the socket's timeout when it connects. Moving it makes the time left in an
    attempt, or an idle limit, apply to every read. Without this, every read keeps the attempt's own timeout."""
    sock = _socket_of(response)
    if sock is not None:
        try:
            sock.settimeout(seconds)
        except OSError:
            pass


def _describe(err: BaseException) -> str:
    if isinstance(err, urllib.error.URLError):
        reason = err.reason
        return reason if isinstance(reason, str) else _describe(reason)
    text = str(err)
    return f"{type(err).__name__}: {text}" if text else type(err).__name__


def _build_opener(proxies: Optional[Mapping[str, str]], context: Optional[ssl.SSLContext]) -> urllib.request.OpenerDirector:
    """An opener with what the API needs and nothing else: no redirects (the API does not redirect, and one could
    carry the token elsewhere), no ``file:`` or ``ftp:``, and no error processor, so that every status is an answer."""
    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.ProxyHandler(dict(proxies) if proxies is not None else None))
    opener.add_handler(urllib.request.UnknownHandler())
    opener.add_handler(urllib.request.HTTPHandler())
    if hasattr(http.client, "HTTPSConnection"):
        opener.add_handler(urllib.request.HTTPSHandler(context=context))
    opener.addheaders = []  # no "Python-urllib" User-Agent: the client sends its own
    return opener


class UrllibTransport:
    """The default transport, on ``urllib.request``: no dependency.

    ``proxies`` is a ``{scheme: url}`` mapping; left out, the proxy settings of the environment apply
    (``HTTPS_PROXY``, ``NO_PROXY``), and ``{}`` means none. ``ssl_context`` replaces the default one (a private
    certificate authority, say). A connection serves one request: for pooling use ``HttpxTransport``.
    """

    def __init__(self, *, proxies: Optional[Mapping[str, str]] = None, ssl_context: Optional[ssl.SSLContext] = None) -> None:
        self._opener = _build_opener(proxies, ssl_context)

    def close(self) -> None:
        return None

    def _open(self, request: HttpRequest) -> Any:
        message = urllib.request.Request(request.url, data=request.body, headers=dict(request.headers), method=request.method)
        try:
            return self._opener.open(message, timeout=request.timeout)
        except socket.timeout as err:
            raise TransportTimeout(_describe(err)) from err
        except urllib.error.URLError as err:
            if isinstance(err.reason, socket.timeout):
                raise TransportTimeout(_describe(err)) from err
            raise TransportError(_describe(err)) from err
        except (http.client.HTTPException, OSError) as err:
            raise TransportError(_describe(err)) from err

    def send(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        response = self._open(request)
        try:
            deadline = None if request.timeout is None else started + request.timeout
            chunks: List[bytes] = []
            while True:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TransportTimeout("the answer did not arrive in time")
                    _set_timeout(response, remaining)
                try:
                    chunk: bytes = response.read1(CHUNK)  # read1: one read, so the deadline is looked at between pieces
                except socket.timeout as err:
                    raise TransportTimeout(_describe(err)) from err
                except (http.client.HTTPException, OSError) as err:
                    raise TransportError(_describe(err)) from err
                if not chunk:
                    break
                chunks.append(chunk)
            return HttpResponse(response.status, response.reason or "", Headers(response.getheaders()), b"".join(chunks))
        finally:
            response.close()

    def open_stream(self, request: HttpRequest) -> StreamResponse:
        response = self._open(request)
        # After the headers, the limit is the idle one.
        _set_timeout(response, request.idle_timeout)
        return _UrllibStream(response)


class _UrllibStream:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.status: int = response.status
        self.reason: str = response.reason or ""
        self.headers = Headers(response.getheaders())

    def read(self, size: int = 8192) -> bytes:
        try:
            chunk: bytes = self._response.read1(size)
            return chunk
        except socket.timeout as err:
            raise TransportTimeout(_describe(err)) from err
        except (http.client.HTTPException, OSError, ValueError, AttributeError) as err:
            # ValueError and AttributeError: a read that another thread's close() cut in half (http.client drops
            # its file object while the read is under way).
            raise TransportError(_describe(err)) from err

    def close(self) -> None:
        # shutdown first: it wakes a read that another thread is blocked in, which close alone does not.
        sock = _socket_of(self._response)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            self._response.close()
        except Exception:  # noqa: BLE001 (closing must never raise)
            pass
