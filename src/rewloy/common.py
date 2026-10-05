"""Hand-written types shared by the client and the generated code (``rewloy.generated``), which imports them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Generic, Iterable, Iterator, List, Literal, Mapping, NamedTuple, Optional, Tuple, TypeVar

if TYPE_CHECKING:  # the types module is big: only annotations name it, so importing the library does not load it
    from .generated.types import PageMeta

T = TypeVar("T")

#: A credential kind of the Rewloy API, as the OpenAPI document's ``x-credentials`` names them:
#: ``key`` an API key (``rwk_…``), ``staff`` a staff session (``rws_…``), ``holder`` a card holder's session
#: (``rwh_…``), ``public`` no credential.
AuthKind = Literal["key", "staff", "holder", "public"]

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

#: How a successful answer is read: ``json`` the ``{ data }`` envelope (with ``meta`` on paged lists), ``none`` a 204,
#: ``blob`` a file (image, CSV, pass) as ``bytes``, ``raw-json`` JSON without the envelope (the OpenAPI document
#: itself), ``stream`` server-sent events.
ResponseKind = Literal["json", "none", "blob", "raw-json", "stream"]


class Deprecation(NamedTuple):
    """An operation marked for removal."""

    #: The last day it works (``YYYY-MM-DD``), when the document says so.
    sunset: Optional[str]
    #: The operationId that replaces it, when the document says so.
    use: Optional[str]


class OperationMeta(NamedTuple):
    """One row of the metadata table (``OPERATIONS``): what the client needs to call an operation."""

    #: The operationId (``passAction``).
    id: str
    #: The method on the client (``pass_action``).
    method_name: str
    http_method: HttpMethod
    #: The path with ``{name}`` placeholders, ``/v1`` included.
    path: str
    #: The credential kinds the operation accepts.
    auth: Tuple[AuthKind, ...]
    #: Takes the ``Rewloy-Merchant`` header (staff sessions with seats in several businesses).
    merchant: bool
    #: Takes an ``Idempotency-Key`` header: ``required``, ``optional``, or not at all.
    idempotency: Optional[Literal["required", "optional"]]
    #: Has a JSON request body.
    body: bool
    response: ResponseKind
    #: A paged list: ``page``/``limit`` in, ``meta`` out.
    paged: bool
    #: Answers with server-sent events.
    stream: bool
    deprecated: Optional[Deprecation]


class Headers(Mapping[str, str]):
    """Response headers: case-insensitive, read-only. A header sent several times is one value, joined with ", "."""

    def __init__(self, pairs: Iterable[Tuple[str, str]] = ()) -> None:
        self._names: Dict[str, str] = {}
        self._values: Dict[str, str] = {}
        for name, value in pairs:
            key = name.lower()
            if key in self._values:
                self._values[key] = f"{self._values[key]}, {value}"
            else:
                self._names[key] = name
                self._values[key] = value

    def __getitem__(self, name: str) -> str:
        return self._values[name.lower()]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.lower() in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._names.values())

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Headers({dict(self.items())!r})"


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a paged list, as the API answers it."""

    data: List[T]
    meta: PageMeta


@dataclass(frozen=True)
class RateLimit:
    """The request budget the API reports on every answer to an authenticated call (``RateLimit-Limit``,
    ``RateLimit-Remaining``, ``RateLimit-Reset``)."""

    #: ``RateLimit-Limit``: requests allowed per minute.
    limit: int
    #: ``RateLimit-Remaining``: requests left in this minute.
    remaining: int
    #: ``RateLimit-Reset``: seconds until the limit renews.
    reset: int


def parse_rate_limit(headers: Optional[Mapping[str, str]]) -> Optional[RateLimit]:
    """The ``RateLimit-*`` headers as a :class:`RateLimit`; ``None`` unless all three are whole numbers."""
    if headers is None:
        return None
    values: List[int] = []
    for name in ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"):
        raw = headers.get(name)
        text = raw.strip() if raw is not None else ""
        if not text.isascii() or not text.isdigit():
            return None
        values.append(int(text))
    return RateLimit(limit=values[0], remaining=values[1], reset=values[2])


@dataclass(frozen=True)
class ApiResponse(Generic[T]):
    """The whole answer to a call (``Rewloy.request``)."""

    #: What ``data`` held (``bytes`` for files, ``None`` for 204).
    data: T
    #: Paging, on paged lists.
    meta: Optional[PageMeta]
    #: The HTTP status: 200, 201, 202 or 204. Some operations answer 200 when they found what they would have created.
    status: int
    headers: Headers
    #: ``x-request-id``: quote it to Rewloy support.
    request_id: Optional[str]
    #: ``Rewloy-Mode``: which mode answered (``test`` for test keys, once the platform has test mode); ``None`` when
    #: the answer does not say.
    mode: Optional[str]
    #: ``Idempotent-Replayed: true``: the API replayed the first answer to this ``Idempotency-Key``.
    replayed: bool
    #: The ``RateLimit-*`` headers; ``None`` when the answer carries none (anonymous calls).
    rate_limit: Optional[RateLimit] = None
