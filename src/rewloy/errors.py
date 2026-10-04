"""What the client raises.

Every failure to get an answer from Rewloy is a ``RewloyError``: an error answer from the API (with its stable
``code``), an answer that is not what the API documents, or no answer at all. A webhook that fails its signature is
a ``WebhookSignatureError`` (``rewloy.webhooks``), which is not one of these.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Type

from .common import Headers


def _restore(cls: Type[RewloyError], state: Dict[str, Any]) -> RewloyError:
    error = cls.__new__(cls)
    Exception.__init__(error, *state["args"])
    error.__dict__.update(state["fields"])
    return error


class RewloyError(Exception):
    """The API answered with an error, or the call failed on the way.

    Act on ``code``: it is stable, while ``detail`` is a human sentence in Turkish that may change. Besides the
    API's codes (https://rewloy.com/gelistiriciler/hatalar) the client uses:

    - ``CONNECTION_ERROR`` and ``TIMEOUT`` (status 0): no answer arrived;
    - ``INVALID_RESPONSE``: a 2xx answer that is not the documented JSON;
    - ``HTTP_<status>``: an error answer without Rewloy's error body (a proxy's 502 page).
    """

    #: The HTTP status; 0 when no answer arrived.
    status: int
    #: The API's stable machine code, e.g. ``INSUFFICIENT_BALANCE`` (``rewloy.types.ErrorCode`` lists them).
    code: str
    #: The code's one-line title in the catalogue, e.g. "Bakiye yetersiz".
    title: Optional[str]
    #: What happened, in the API's words (``error.message``).
    detail: str
    #: The API's ``error.details``, when it sent any: for ``VALIDATION`` a list of ``{field, rule, message}``, for
    #: others what the catalogue says (``left``, ``channels``, ``request``…).
    details: Any
    #: Where the catalogue explains the code (``error.docs``).
    docs: Optional[str]
    #: ``x-request-id``: quote it to Rewloy support.
    request_id: Optional[str]
    #: The parsed answer body (or its text, when it is not JSON).
    body: Any
    headers: Optional[Headers]
    #: The operationId of the call.
    operation: Optional[str]

    def __init__(
        self,
        *,
        status: int,
        code: str,
        detail: str,
        title: Optional[str] = None,
        details: Any = None,
        docs: Optional[str] = None,
        request_id: Optional[str] = None,
        body: Any = None,
        headers: Optional[Headers] = None,
        operation: Optional[str] = None,
    ) -> None:
        where = ", ".join(x for x in (operation, f"request_id {request_id}" if request_id else None) if x)
        super().__init__(f"{f'{status} ' if status else ''}{code}: {detail}{f' ({where})' if where else ''}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.details = details
        self.docs = docs
        self.request_id = request_id
        self.body = body
        self.headers = headers
        self.operation = operation

    def __reduce__(self) -> Tuple[Any, ...]:
        # Keyword-only constructors cannot be rebuilt from ``args``: copy and pickle the fields instead.
        return (_restore, (type(self), {"args": self.args, "fields": dict(self.__dict__)}))


class RateLimitError(RewloyError):
    """429 ``RATE_LIMITED``: too many requests for this credential or this action."""

    #: Seconds to wait before trying again (``Retry-After``), when the API said.
    retry_after: Optional[int]

    def __init__(self, *, retry_after: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.retry_after = retry_after


class RewloyConnectionError(RewloyError):
    """No answer arrived: the connection failed or broke (``CONNECTION_ERROR``)."""

    def __init__(
        self,
        *,
        detail: str,
        code: str = "CONNECTION_ERROR",
        operation: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(status=0, code=code, detail=detail, operation=operation, request_id=request_id)


class RewloyTimeoutError(RewloyConnectionError):
    """No answer within ``timeout`` (``TIMEOUT``), or a stream fell silent."""

    def __init__(self, *, detail: str, operation: Optional[str] = None, request_id: Optional[str] = None) -> None:
        super().__init__(detail=detail, code="TIMEOUT", operation=operation, request_id=request_id)
