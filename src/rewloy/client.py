"""The client: credentials, the request (headers, retries, timeouts, errors, deprecation notices), pagination and
streams. The operations themselves come from the generated ``RewloyMethods``, one method per operationId.
"""

from __future__ import annotations

import http
import json
import logging
import math
import platform
import random
import re
import sys
import threading
import time
import uuid
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from types import FrameType
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple, cast
from urllib.parse import quote

from ._version import __version__
from .common import ApiResponse, AuthKind, Headers, OperationMeta, Page
from .errors import RateLimitError, RewloyConnectionError, RewloyError, RewloyTimeoutError
from .generated.methods import RewloyMethods
from .generated.operations import ERROR_TITLES, OPERATION_IDS, OPERATIONS
from .sse import EventStream
from .transport import HttpRequest, HttpResponse, StreamResponse, Transport, TransportError, TransportTimeout, UrllibTransport

if TYPE_CHECKING:  # only annotations name it: the types module is big and importing the client does not load it
    from .generated.types import PageMeta

DEFAULT_BASE_URL = "https://app.rewloy.com"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_IDLE_TIMEOUT = 60.0
#: Backoff: 0.5 s, 1 s, 2 s… up to 8 s, each with jitter (between half and all of it).
BACKOFF_BASE = 0.5
BACKOFF_MAX = 8.0
#: A ``Retry-After`` longer than this is not waited for: the error goes to the caller.
MAX_RETRY_AFTER = 60.0
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})
#: 502–504 and Cloudflare's 520–524 (the origin unreachable or too slow).
GATEWAY_STATUSES = frozenset({502, 503, 504, 520, 521, 522, 523, 524})
#: How much of an error answer is read from a stream before giving up on the rest.
MAX_ERROR_BODY = 64 * 1024

_PREFIXES: Dict[str, Tuple[str, AuthKind]] = {
    "api_key": ("rwk_", "key"), "staff_session": ("rws_", "staff"), "holder_session": ("rwh_", "holder"),
}

_log = logging.getLogger("rewloy")
#: Operations already warned about: one warning per operation per process, whatever the number of clients.
_warned: set[str] = set()
_warned_lock = threading.Lock()


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """``Retry-After`` in seconds: delta-seconds or an HTTP date."""
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", v):
        return float(v)
    try:
        at = parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0.0, at.timestamp() - (time.time() if now is None else now))


def backoff(attempt: int, rand: Callable[[], float] = random.random) -> float:
    """Exponential backoff with jitter, in seconds, for the retry after attempt ``attempt`` (0-based)."""
    cap = min(BACKOFF_MAX, BACKOFF_BASE * 2.0**attempt)
    return cap / 2 + rand() * (cap / 2)


_LINK = re.compile(r"<([^>]*)>([^,]*)")
_REL_DEPRECATION = re.compile(r"""\brel\s*=\s*"?[^";]*\bdeprecation\b""", re.IGNORECASE)


def _deprecation_link(link: Optional[str]) -> Optional[str]:
    """The URL a ``Link`` header gives for ``rel="deprecation"`` (else its first)."""
    if not link:
        return None
    first: Optional[str] = None
    for m in _LINK.finditer(link):
        if first is None:
            first = m.group(1)
        if _REL_DEPRECATION.search(m.group(2)):
            return m.group(1)
    return first


def _warn(message: str) -> None:
    """A ``DeprecationWarning`` that points at the caller's own line (the first frame outside this package), so
    that Python's default filter, which shows it for ``__main__`` only, treats it as the caller's."""
    level = 1
    frame: Optional[FrameType] = sys._getframe(0)
    while frame is not None and re.match(r"rewloy(\.|$)", str(frame.f_globals.get("__name__", ""))):
        frame = frame.f_back
        level += 1
    try:
        warnings.warn(message, DeprecationWarning, stacklevel=level)
    except Warning:
        # `-W error` turns the warning into an exception here, after the server has acted: the answer to a call
        # that went through must not be lost for a notice. The notice goes to the log instead.
        _log.warning("DeprecationWarning: %s", message)


def _json_default(value: object) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _scalar(value: object, where: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Enum):
        return _scalar(value.value, where)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Rewloy: {where} is not a finite number")
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"Rewloy: {where} must be a string, number or boolean, not {type(value).__name__}")


def encode_query(query: Mapping[str, object]) -> str:
    """A query string: RFC 3986 (``%20``), booleans as ``true``/``false``, a list repeats its key, ``None`` leaves a
    parameter out."""
    pairs: List[str] = []
    for key, value in query.items():
        if value is None:
            continue
        for item in value if isinstance(value, (list, tuple, set, frozenset)) else [value]:
            if item is None:
                continue
            pairs.append(f"{quote(str(key), safe='')}={quote(_scalar(item, f'query.{key}'), safe='')}")
    return "&".join(pairs)


@dataclass(frozen=True)
class _Call:
    """What the caller gave: everything about one call that is not the operation itself."""

    path: Optional[Mapping[str, object]] = None
    query: Optional[Mapping[str, object]] = None
    body: object = None
    headers: Optional[Mapping[str, object]] = None
    merchant: Optional[str] = None
    idempotency_key: Optional[str] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    idle_timeout: Optional[float] = None


@dataclass(frozen=True)
class _Exchange:
    status: int
    headers: Headers
    data: Any
    meta: Optional[PageMeta]
    #: For a stream: the open answer, its body unread.
    stream: Optional[StreamResponse] = None


def _none_if_unlimited(seconds: float) -> Optional[float]:
    """0 or infinity mean no limit."""
    return None if seconds <= 0 or math.isinf(seconds) else seconds


class Rewloy(RewloyMethods):
    """A client of the Rewloy API (``https://app.rewloy.com/v1``).

    ::

        rewloy = Rewloy(api_key=os.environ["REWLOY_API_KEY"])
        card = rewloy.get_pass("ABCD-EFGH-JKLM")

    Every operation of the API is a method named by its operationId in snake_case. Path parameters are arguments;
    ``query``, ``body``, ``merchant``, ``idempotency_key``, ``timeout`` and ``max_retries`` follow as keywords.

    One credential, or none for the endpoints that need none (sign-in, joining a programme…):

    - ``api_key="rwk_…"``: an API key (a till, a shop, your own system);
    - ``staff_session="rws_…"``, with ``merchant`` when the person has seats in several businesses: a person's
      business app;
    - ``holder_session="rwh_…"``: a card holder's session (a Rewloy Cüzdan app).

    ``timeout`` is the seconds one attempt may take (0 or ``math.inf`` for none), ``max_retries`` the retries after
    a failed attempt when retrying is safe, ``transport`` replaces the HTTP layer (``HttpxTransport``, or a fake in
    tests), ``user_agent`` is added to the ``User-Agent`` this client sends (``"KasaPOS/4.2"``), and ``sleep``
    replaces the wait between retries and reconnections (it gets seconds).

    A client is safe to share between threads. Use it as a context manager, or call ``close()``, to release what its
    transport holds.
    """

    base_url: str
    timeout: float
    max_retries: int
    #: The kind of credential this client sends, or ``None`` for none.
    credential: Optional[AuthKind]
    #: The default ``Rewloy-Merchant`` of a staff session.
    merchant: Optional[str]

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        staff_session: Optional[str] = None,
        holder_session: Optional[str] = None,
        merchant: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: Optional[Transport] = None,
        user_agent: Optional[str] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        given = [(k, v) for k, v in (("api_key", api_key), ("staff_session", staff_session), ("holder_session", holder_session)) if v is not None]
        if len(given) > 1:
            raise ValueError(f"Rewloy: give one credential, not {' and '.join(k for k, _ in given)}")
        self._token: Optional[str] = None
        self.credential = None
        if given:
            which, token = given[0]
            prefix, kind = _PREFIXES[which]
            if not isinstance(token, str):
                raise TypeError(f"Rewloy: {which} must be a string")
            if not token.startswith(prefix):
                raise ValueError(f'Rewloy: {which} must start with "{prefix}"')
            self._token = token
            self.credential = kind
        if merchant is not None and staff_session is None:
            raise ValueError("Rewloy: `merchant` goes with a staff_session")
        self.merchant = merchant
        if not re.match(r"https?://", base_url, re.IGNORECASE):
            raise ValueError("Rewloy: base_url must start with http:// or https://")
        self.base_url = base_url.rstrip("/")
        if timeout < 0:
            raise ValueError("Rewloy: timeout cannot be negative")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._owns_transport = transport is None
        self._transport: Transport = transport if transport is not None else UrllibTransport()
        self._user_agent = " ".join(
            x for x in (f"rewloy-python/{__version__}", f"python/{platform.python_version()}", (user_agent or "").strip()) if x
        )
        self._user_sleep = sleep

    def __repr__(self) -> str:
        return f"Rewloy(base_url={self.base_url!r}, credential={self.credential!r})"

    def __enter__(self) -> "Rewloy":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Releases what the transport holds. A transport you passed in is yours to close."""
        if self._owns_transport:
            self._transport.close()

    # -- public calls

    def request(
        self,
        operation_id: str,
        *,
        path: Optional[Mapping[str, object]] = None,
        query: Optional[Mapping[str, object]] = None,
        body: object = None,
        headers: Optional[Mapping[str, object]] = None,
        merchant: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> ApiResponse[Any]:
        """Calls an operation and returns the whole answer: ``data``, ``meta`` on paged lists, the status, headers,
        ``request_id``, ``mode`` and ``replayed``.

        ``operation_id`` is the operationId (``sendCampaign``) or the method's name (``send_campaign``); ``path``
        holds the path parameters by their names in the API (``{"serial": "ABCD-EFGH-JKLM"}``). ``data`` is not
        typed here: ``typing.cast`` it, or call the method itself.

        ::

            res = rewloy.request("sendCampaign", body={"body": "Bu hafta kahveler 2 damga!"})
            res.status, res.replayed, res.mode, res.data["id"]
        """
        op = self._operation(operation_id)
        if op.stream:
            raise ValueError(f"Rewloy: {op.id} is a stream; use stream({op.id!r})")
        ex = self._exchange(op, _Call(path, query, body, headers, merchant, idempotency_key, timeout, max_retries))
        return ApiResponse(
            data=ex.data, meta=ex.meta, status=ex.status, headers=ex.headers,
            request_id=ex.headers.get("x-request-id"), mode=ex.headers.get("rewloy-mode"),
            replayed=ex.headers.get("idempotent-replayed") == "true",
        )

    def stream(
        self,
        operation_id: str,
        *,
        path: Optional[Mapping[str, object]] = None,
        query: Optional[Mapping[str, object]] = None,
        headers: Optional[Mapping[str, object]] = None,
        merchant: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        reconnect: bool = True,
        idle_timeout: Optional[float] = None,
    ) -> EventStream:
        """Opens a server-sent event stream (``liveFeed``, ``holderCardEvents``), the same as its method
        (``live_feed``, ``holder_card_events``)."""
        return self._open(
            operation_id, path=path, query=query, headers=headers, merchant=merchant, timeout=timeout,
            max_retries=max_retries, reconnect=reconnect, idle_timeout=idle_timeout,
        )

    # -- what the generated methods call

    def _call(
        self,
        operation_id: str,
        *,
        path: Optional[Mapping[str, object]] = None,
        query: Optional[Mapping[str, object]] = None,
        body: object = None,
        headers: Optional[Mapping[str, object]] = None,
        merchant: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> object:
        op = self._operation(operation_id)
        ex = self._exchange(op, _Call(path, query, body, headers, merchant, idempotency_key, timeout, max_retries))
        if op.paged:
            assert ex.meta is not None  # _read refuses a paged answer without it
            return Page(data=ex.data, meta=ex.meta)
        return ex.data

    def _open(
        self,
        operation_id: str,
        *,
        path: Optional[Mapping[str, object]] = None,
        query: Optional[Mapping[str, object]] = None,
        headers: Optional[Mapping[str, object]] = None,
        merchant: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        reconnect: bool = True,
        idle_timeout: Optional[float] = None,
    ) -> EventStream:
        op = self._operation(operation_id)
        if not op.stream:
            raise ValueError(f"Rewloy: {op.id} is not a stream; use request({op.id!r})")
        idle = _none_if_unlimited(DEFAULT_IDLE_TIMEOUT if idle_timeout is None else idle_timeout)
        call = _Call(path, query, None, headers, merchant, None, timeout, max_retries, idle if idle is not None else 0.0)

        def connect(last_event_id: str) -> StreamResponse:
            stream = self._exchange(op, call, last_event_id=last_event_id).stream
            assert stream is not None
            return stream

        return EventStream(operation=op.id, connect=connect, reconnect=reconnect, idle_timeout=idle, sleep=self._stream_sleep)

    def _paginate(
        self,
        operation_id: str,
        *,
        path: Optional[Mapping[str, object]] = None,
        query: Optional[Mapping[str, object]] = None,
        merchant: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Iterator[Any]:
        op = self._operation(operation_id)
        if not op.paged:
            raise ValueError(f"Rewloy: {op.id} is not a paged list")
        base: Dict[str, object] = dict(query or {})
        first = base.get("page", 1)
        start = int(first) if isinstance(first, (int, float, str)) and not isinstance(first, bool) else 1

        def pages() -> Iterator[Any]:
            page = start
            while True:
                ex = self._exchange(op, _Call(path, {**base, "page": page}, None, None, merchant, None, timeout, max_retries))
                items: List[Any] = ex.data if isinstance(ex.data, list) else []
                yield from items
                meta = ex.meta
                if (
                    meta is None or not items or len(items) < meta["pageSize"]
                    or meta["page"] * meta["pageSize"] >= meta["total"]
                ):
                    return
                page = meta["page"] + 1

        return pages()

    # -- the request

    def _operation(self, operation_id: str) -> OperationMeta:
        op = OPERATIONS.get(operation_id)
        if op is None and operation_id in OPERATION_IDS:
            op = OPERATIONS[OPERATION_IDS[operation_id]]
        if op is None:
            raise ValueError(f'Rewloy: unknown operation "{operation_id}"')
        return op

    def _url(self, op: OperationMeta, call: _Call) -> str:
        def fill(match: "re.Match[str]") -> str:
            name = match.group(1)
            value = (call.path or {}).get(name)
            if value is None or value == "":
                raise ValueError(f"Rewloy: {op.id} needs path[{name!r}]")
            return quote(_scalar(value, f"path.{name}"), safe="")

        url = self.base_url + re.sub(r"\{([^}]+)\}", fill, op.path)
        qs = encode_query(call.query or {})
        return f"{url}?{qs}" if qs else url

    def _headers(self, op: OperationMeta, call: _Call, last_event_id: Optional[str]) -> Dict[str, str]:
        h: Dict[str, str] = {}
        h["Accept"] = (
            "text/event-stream" if op.stream
            else "application/json" if op.response in ("json", "raw-json") else "*/*"
        )
        h["User-Agent"] = self._user_agent
        # An operation that takes no credential of this kind but works without one is called without it: the API
        # refuses a credential an operation does not accept (CREDENTIAL_NOT_ALLOWED).
        if self._token and self.credential and (self.credential in op.auth or "public" not in op.auth):
            h["Authorization"] = f"Bearer {self._token}"
        merchant = call.merchant if call.merchant is not None else (self.merchant if self.credential == "staff" else None)
        if op.merchant and merchant:
            h["Rewloy-Merchant"] = merchant
        if op.idempotency:
            h["Idempotency-Key"] = call.idempotency_key or str(uuid.uuid4())
        if op.body:
            h["Content-Type"] = "application/json"
        if op.stream:
            # As an EventSource asks, and so that no proxy holds events back.
            h["Cache-Control"] = "no-cache"
            h["Accept-Encoding"] = "identity"
        if last_event_id:
            h["Last-Event-ID"] = last_event_id
        for name, value in (call.headers or {}).items():
            if value is not None:
                h[name] = _scalar(value, f"headers.{name}")
        return h

    def _body(self, op: OperationMeta, call: _Call) -> Optional[bytes]:
        if not op.body:
            return None
        return json.dumps(
            {} if call.body is None else call.body, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_json_default
        ).encode("utf-8")

    def _notice(self, op: OperationMeta, headers: Headers) -> None:
        if "deprecation" not in headers:
            return
        with _warned_lock:
            if op.id in _warned:
                return
            _warned.add(op.id)
        sunset = headers.get("sunset")
        link = _deprecation_link(headers.get("link"))
        _warn(
            f"Rewloy API operation {op.id} ({op.http_method} {op.path}) is deprecated."
            f"{f' Sunset: {sunset}.' if sunset else ''}{f' See {link}' if link else ''}"
        )

    def _pause(self, seconds: float) -> None:
        (self._user_sleep or time.sleep)(seconds)

    def _stream_sleep(self, seconds: float, stop: threading.Event) -> None:
        """A wait that ``close()`` ends at once (unless the caller replaced sleeping)."""
        if self._user_sleep is not None:
            self._user_sleep(seconds)
        else:
            stop.wait(seconds)

    @staticmethod
    def _retry_status(status: int, code: str) -> bool:
        return status == 429 or status in GATEWAY_STATUSES or (status == 409 and code == "IDEMPOTENCY_IN_PROGRESS")

    def _exchange(self, op: OperationMeta, call: _Call, *, last_event_id: Optional[str] = None) -> _Exchange:
        """One call: attempts until an answer settles it. For a stream it returns once the headers are in, the body
        unread; otherwise with the body read."""
        url = self._url(op, call)
        headers = self._headers(op, call, last_event_id)
        body = self._body(op, call)
        retryable = op.http_method in IDEMPOTENT_METHODS or any(k.lower() == "idempotency-key" for k in headers)
        max_retries = max(0, call.max_retries if call.max_retries is not None else self.max_retries)
        timeout = _none_if_unlimited(self.timeout if call.timeout is None else call.timeout)
        idle = _none_if_unlimited(call.idle_timeout) if call.idle_timeout is not None else None
        request = HttpRequest(op.http_method, url, headers, body, timeout, idle)

        attempt = 0
        while True:
            transport_failure: Optional[RewloyError] = None
            cause: Optional[BaseException] = None
            answer: Optional[HttpResponse] = None
            opened: Optional[StreamResponse] = None
            try:
                if op.stream:
                    opened = self._transport.open_stream(request)
                else:
                    answer = self._transport.send(request)
            except TransportTimeout as err:
                transport_failure = RewloyTimeoutError(
                    detail=f"no answer within {timeout:g} s" if timeout is not None else str(err), operation=op.id
                )
                cause = err
            except TransportError as err:
                transport_failure = RewloyConnectionError(detail=str(err), operation=op.id)
                cause = err

            wait: Optional[float] = None
            if transport_failure is not None:
                if not retryable or attempt >= max_retries:
                    raise transport_failure from cause
                failure = transport_failure
            else:
                if opened is not None:
                    status, reason, response_headers = opened.status, opened.reason, opened.headers
                else:
                    assert answer is not None
                    status, reason, response_headers = answer.status, answer.reason, answer.headers
                self._notice(op, response_headers)
                if 200 <= status < 300:
                    if opened is not None:
                        return _Exchange(status, response_headers, None, None, opened)
                    assert answer is not None
                    data, meta = self._read(op, status, response_headers, answer.body)
                    return _Exchange(status, response_headers, data, meta)
                if opened is not None:
                    text = self._drain(opened)
                else:
                    assert answer is not None
                    text = answer.body.decode("utf-8", errors="replace")
                failure = self._failure(op, status, reason, response_headers, text)
                if not retryable or attempt >= max_retries or not self._retry_status(status, failure.code):
                    raise failure
                wait = parse_retry_after(response_headers.get("retry-after"))

            delay = wait if wait is not None else backoff(attempt)
            if delay > MAX_RETRY_AFTER:
                raise failure from cause
            self._pause(delay)
            attempt += 1

    @staticmethod
    def _drain(opened: StreamResponse) -> str:
        """The (error) body of an answer to a stream, bounded; the connection is closed."""
        parts: List[bytes] = []
        size = 0
        try:
            while size < MAX_ERROR_BODY:
                chunk = opened.read(8192)
                if not chunk:
                    break
                parts.append(chunk)
                size += len(chunk)
        except TransportError:
            pass
        finally:
            opened.close()
        return b"".join(parts).decode("utf-8", errors="replace")

    def _read(self, op: OperationMeta, status: int, headers: Headers, content: bytes) -> Tuple[Any, Optional[PageMeta]]:
        if op.response == "none" or status == 204:
            return None, None
        if op.response == "blob":
            return content, None
        text = content.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except ValueError:
            raise self._invalid(op, status, headers, text) from None
        if op.response == "raw-json":
            return parsed, None
        if not isinstance(parsed, dict) or "data" not in parsed:
            raise self._invalid(op, status, headers, parsed)
        meta = parsed.get("meta")
        if op.paged and not isinstance(meta, dict):
            raise self._invalid(op, status, headers, parsed)
        return parsed["data"], cast("Optional[PageMeta]", meta if isinstance(meta, dict) else None)

    @staticmethod
    def _invalid(op: OperationMeta, status: int, headers: Headers, body: object) -> RewloyError:
        return RewloyError(
            status=status, code="INVALID_RESPONSE",
            detail=f"the answer is not the JSON the API documents ({headers.get('content-type') or 'no content type'})",
            request_id=headers.get("x-request-id"), body=body, headers=headers, operation=op.id,
        )

    @staticmethod
    def _failure(op: OperationMeta, status: int, reason: str, headers: Headers, text: str) -> RewloyError:
        parsed: Any = text
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            pass  # not JSON: a proxy's page
        e = parsed.get("error") if isinstance(parsed, dict) else None
        e = e if isinstance(e, dict) else None
        code = e["code"] if e is not None and isinstance(e.get("code"), str) else f"HTTP_{status}"
        try:
            phrase = http.HTTPStatus(status).phrase
        except ValueError:
            phrase = f"HTTP {status}"
        fields: Dict[str, Any] = dict(
            status=status, code=code, title=ERROR_TITLES.get(code),
            detail=e["message"] if e is not None and isinstance(e.get("message"), str) else (reason or phrase),
            details=e.get("details") if e is not None else None,
            docs=e["docs"] if e is not None and isinstance(e.get("docs"), str) else None,
            request_id=headers.get("x-request-id") or (e["requestId"] if e is not None and isinstance(e.get("requestId"), str) else None),
            body=parsed, headers=headers, operation=op.id,
        )
        if status == 429:
            header = parse_retry_after(headers.get("retry-after"))
            from_body = fields["details"].get("retryAfterSec") if isinstance(fields["details"], dict) else None
            retry_after = math.ceil(header) if header is not None else (
                int(from_body) if isinstance(from_body, (int, float)) and not isinstance(from_body, bool) else None
            )
            return RateLimitError(retry_after=retry_after, **fields)
        return RewloyError(**fields)
