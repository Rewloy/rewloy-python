"""Server-sent events (``text/event-stream``), as the HTML standard parses them
(https://html.spec.whatwg.org/multipage/server-sent-events.html), and the stream the client opens on ``live_feed``
and ``holder_card_events``.

The API's streams start with ``retry: 5000``, send ``: hb`` every 25 seconds and events as ``event: <type>`` +
``data: <text>``; they carry no ``id:`` today.
"""

from __future__ import annotations

import codecs
import json
import re
import threading
from dataclasses import dataclass
from types import TracebackType
from collections import deque
from typing import Any, Callable, Deque, List, Optional, Type

from .errors import RewloyConnectionError, RewloyError, RewloyTimeoutError
from .transport import StreamResponse, TransportError, TransportTimeout

DEFAULT_RETRY = 3.0
MAX_RECONNECT = 30.0
_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class ServerSentEvent:
    """One event of a stream."""

    #: The type: the ``event:`` field, ``message`` when the event had none.
    event: str
    #: The ``data:`` lines, joined with "\n".
    data: str
    #: The last event ID: the latest ``id:`` field the stream has sent (``""`` if none).
    id: str

    def json(self) -> Any:
        """``data`` parsed as JSON."""
        return json.loads(self.data)


class SseParser:
    """The standard's parser, fed text in pieces of any size: a line, an event or a CRLF may be split anywhere
    between two pieces."""

    #: The reconnection time the stream asked for (``retry:``), in milliseconds.
    retry: Optional[int]
    #: The last event ID: set from the ``id:`` buffer at every blank line, kept from one event to the next, as the
    #: standard says.
    last_event_id: str

    def __init__(self, last_event_id: str = "") -> None:
        self.retry = None
        self.last_event_id = last_event_id
        self._id = last_event_id
        self._line = ""
        self._data = ""
        self._event = ""
        self._after_cr = False
        self._started = False

    def push(self, text: str) -> List[ServerSentEvent]:
        """Feeds decoded text; returns the events it completed."""
        out: List[ServerSentEvent] = []
        i = 0
        if not self._started and text:
            self._started = True
            if text[0] == "﻿":
                i = 1
        # A CR ended the previous piece: an LF right after it belongs to the same line ending.
        if self._after_cr and i < len(text):
            if text[i] == "\n":
                i += 1
            self._after_cr = False
        n = len(text)
        while i < n:
            j = i
            while j < n and text[j] != "\n" and text[j] != "\r":
                j += 1
            if j == n:
                self._line += text[i:]
                break
            line = self._line + text[i:j]
            self._line = ""
            if text[j] == "\r":
                if j + 1 < n:
                    if text[j + 1] == "\n":
                        j += 1
                else:
                    self._after_cr = True
            i = j + 1
            self._take(line, out)
        return out

    def end(self) -> None:
        """The stream ended: an event without its blank line is dropped, as the standard says."""
        self._line = ""
        self._data = ""
        self._event = ""
        self._after_cr = False

    def _take(self, line: str, out: List[ServerSentEvent]) -> None:
        if line == "":
            self.last_event_id = self._id
            if self._data == "":
                self._event = ""
                return
            data = self._data[:-1] if self._data.endswith("\n") else self._data
            out.append(ServerSentEvent(self._event or "message", data, self.last_event_id))
            self._data = ""
            self._event = ""
            return
        if line.startswith(":"):
            return
        colon = line.find(":")
        name = line if colon == -1 else line[:colon]
        value = "" if colon == -1 else line[colon + 1 :]
        if value.startswith(" "):
            value = value[1:]
        if name == "event":
            self._event = value
        elif name == "data":
            self._data += value + "\n"
        elif name == "id":
            if "\0" not in value:
                self._id = value
        elif name == "retry":
            if _DIGITS.fullmatch(value):
                self.retry = int(value)


def _transient(err: BaseException) -> bool:
    """Errors a new connection may fix."""
    if isinstance(err, RewloyConnectionError):
        return True
    return isinstance(err, RewloyError) and (err.status in (429, 502, 503, 504) or 520 <= err.status <= 524)


class EventStream:
    """A live stream of server-sent events: iterate it with ``for``. It ends when you ``break``, on ``close()`` (from
    any thread), or with a ``RewloyError`` that a reconnection cannot fix; with ``reconnect=False`` also when the
    connection ends. Use it as a context manager to close it for sure.

    Nothing is sent until the first event is asked for. A stream is its own iterator: it can be iterated once.

    The connection is closed when you call ``close()``, leave the ``with`` block, or drop the last reference to the
    stream (a ``break`` out of ``for event in rewloy.live_feed():`` does the last, at once in CPython).
    """

    #: The last event ID seen; sent as ``Last-Event-ID`` when reconnecting.
    last_event_id: str
    #: The wait before reconnecting, in seconds: the server's ``retry:`` once it sent one.
    retry: float
    #: ``x-request-id`` of the current connection.
    request_id: Optional[str]
    #: ``Rewloy-Mode`` of the current connection (see ``ApiResponse.mode``).
    mode: Optional[str]

    def __init__(
        self,
        *,
        operation: str,
        connect: Callable[[str], StreamResponse],
        reconnect: bool,
        idle_timeout: Optional[float],
        sleep: Callable[[float, threading.Event], None],
    ) -> None:
        self.last_event_id = ""
        self.retry = DEFAULT_RETRY
        self.request_id = None
        self.mode = None
        self._operation = operation
        self._connect = connect
        self._reconnect = reconnect
        self._idle_timeout = idle_timeout
        self._sleep = sleep
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._current: Optional[StreamResponse] = None
        self._parser = SseParser()
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending: Deque[ServerSentEvent] = deque()
        self._failures = 0
        self._wait_before_connect: Optional[float] = None
        self._done = False

    # The stream is a state machine, not a generator: a generator's frame would hold the stream, and the two would
    # keep each other alive until the garbage collector ran, with the connection open.

    def __iter__(self) -> "EventStream":
        return self

    def __next__(self) -> ServerSentEvent:
        while True:
            if self._pending:
                return self._pending.popleft()
            if self._done or self._stopped():
                self._finish()
                raise StopIteration
            self._advance()

    def __enter__(self) -> "EventStream":
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 (a finalizer must not raise)
            pass

    def close(self) -> None:
        """Closes the connection and ends the iteration. Safe to call from another thread."""
        self._stop.set()
        with self._lock:
            current = self._current
        if current is not None:
            current.close()

    def _stopped(self) -> bool:
        return self._stop.is_set()

    def _finish(self) -> None:
        self._done = True
        self._release()

    def _release(self) -> None:
        with self._lock:
            current, self._current = self._current, None
        if current is not None:
            current.close()

    def _wait(self, seconds: float) -> bool:
        """Waits before a reconnection; ``False`` when the stream was stopped meanwhile."""
        self._sleep(seconds, self._stop)
        return not self._stopped()

    def _advance(self) -> None:
        """One step: wait, connect, or read a piece of the body (queueing the events in it)."""
        if self._wait_before_connect is not None:
            delay, self._wait_before_connect = self._wait_before_connect, None
            if not self._wait(delay):
                self._finish()
            return
        with self._lock:
            response = self._current
        if response is None:
            self._open_connection()
        else:
            self._read(response)

    def _open_connection(self) -> None:
        try:
            response = self._connect(self.last_event_id)
        except RewloyError as err:
            if self._stopped():
                self._finish()
                return
            if not self._reconnect or not _transient(err):
                self._finish()
                raise
            self._failures += 1
            self._wait_before_connect = max(self.retry, min(MAX_RECONNECT, 2.0**self._failures))
            return
        with self._lock:
            self._current = response
        if self._stopped():  # close() came while connecting
            self._finish()
            return
        self.request_id = response.headers.get("x-request-id")
        self.mode = response.headers.get("rewloy-mode")
        self._parser = SseParser(self.last_event_id)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def _read(self, response: StreamResponse) -> None:
        dropped: Optional[RewloyError] = None
        try:
            chunk = response.read(8192)
            text = self._decoder.decode(chunk, final=not chunk)
            for event in self._parser.push(text):
                self.last_event_id = event.id
                self._failures = 0
                self._pending.append(event)
            self.last_event_id = self._parser.last_event_id
            if self._parser.retry is not None:
                self.retry = self._parser.retry / 1000
            if chunk:
                return
            self._parser.end()
        except TransportTimeout:
            if self._stopped():
                self._finish()
                return
            dropped = RewloyTimeoutError(
                detail=f"no data for {self._idle_timeout:g} s" if self._idle_timeout else "the connection timed out",
                operation=self._operation, request_id=self.request_id,
            )
        except TransportError as err:
            if self._stopped():
                self._finish()
                return
            dropped = RewloyConnectionError(detail=str(err), operation=self._operation, request_id=self.request_id)
            dropped.__cause__ = err
        # The connection is over, with an error or at its end.
        self._release()
        if self._stopped():
            self._finish()
            return
        if not self._reconnect:
            self._done = True
            if dropped is not None:
                raise dropped
            return
        if dropped is not None:
            self._failures += 1
            self._wait_before_connect = max(self.retry, min(MAX_RECONNECT, 2.0**self._failures))
        else:
            self._wait_before_connect = self.retry
