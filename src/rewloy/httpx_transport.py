"""An optional transport on ``httpx``: connection pooling and keep-alive, HTTP/2 (``httpx.Client(http2=True)``),
proxies, and everything else ``httpx`` configures.

    pip install "rewloy[httpx]"

    import httpx
    from rewloy import Rewloy
    from rewloy.httpx_transport import HttpxTransport

    rewloy = Rewloy(api_key=..., transport=HttpxTransport(httpx.Client(http2=True)))

Nothing imports this module unless you do, so the library itself needs no dependency.
"""

from __future__ import annotations

import socket
import time
from typing import Iterator, List, Optional

import httpx

from .common import Headers
from .transport import CHUNK, HttpRequest, HttpResponse, StreamResponse, TransportError, TransportTimeout


def _describe(err: BaseException) -> str:
    text = str(err)
    return f"{type(err).__name__}: {text}" if text else type(err).__name__


def _timeout(connect: Optional[float], read: Optional[float]) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=connect, pool=connect)


class HttpxTransport:
    """The transport on an ``httpx.Client``. Given one, it is yours to close; left out, the transport makes its own
    (and closes it on ``close()``). Redirects are never followed: the API does not redirect, and one could carry the
    token elsewhere."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _build(self, request: HttpRequest, read_timeout: Optional[float]) -> httpx.Request:
        return self._client.build_request(
            request.method, request.url, headers=dict(request.headers), content=request.body,
            timeout=_timeout(request.timeout, read_timeout),
        )

    def send(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        try:
            response = self._client.send(self._build(request, request.timeout), stream=True, follow_redirects=False)
        except httpx.TimeoutException as err:
            raise TransportTimeout(_describe(err)) from err
        except httpx.HTTPError as err:
            raise TransportError(_describe(err)) from err
        try:
            deadline = None if request.timeout is None else started + request.timeout
            chunks: List[bytes] = []
            try:
                for chunk in response.iter_bytes(CHUNK):
                    chunks.append(chunk)
                    # The attempt's time covers the whole body, as with the default transport.
                    if deadline is not None and time.monotonic() > deadline:
                        raise TransportTimeout("the answer did not arrive in time")
            except httpx.TimeoutException as err:
                raise TransportTimeout(_describe(err)) from err
            except httpx.HTTPError as err:
                raise TransportError(_describe(err)) from err
            return HttpResponse(
                response.status_code, response.reason_phrase, Headers(response.headers.multi_items()), b"".join(chunks)
            )
        finally:
            response.close()

    def open_stream(self, request: HttpRequest) -> StreamResponse:
        try:
            response = self._client.send(self._build(request, request.idle_timeout), stream=True, follow_redirects=False)
        except httpx.TimeoutException as err:
            raise TransportTimeout(_describe(err)) from err
        except httpx.HTTPError as err:
            raise TransportError(_describe(err)) from err
        return _HttpxStream(response)


class _HttpxStream:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self._chunks: Optional[Iterator[bytes]] = None
        self.status: int = response.status_code
        self.reason: str = response.reason_phrase
        self.headers = Headers(response.headers.multi_items())

    def read(self, size: int = 8192) -> bytes:
        try:
            if self._chunks is None:
                self._chunks = self._response.iter_bytes()
            return next(self._chunks, b"")
        except httpx.TimeoutException as err:
            raise TransportTimeout(_describe(err)) from err
        except (httpx.HTTPError, RuntimeError, OSError, ValueError) as err:
            # RuntimeError: httpx's "stream closed" when another thread called close() under a read.
            raise TransportError(_describe(err)) from err

    def close(self) -> None:
        # Closing the response does not wake a read that another thread is blocked in; shutting the socket down does.
        try:
            network = self._response.extensions.get("network_stream")
            sock = network.get_extra_info("socket") if network is not None else None
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except Exception as err:  # noqa: BLE001 (closing must never raise)
            _ = err
        try:
            self._response.close()
        except Exception as err:  # noqa: BLE001
            _ = err


__all__ = ["HttpxTransport"]
