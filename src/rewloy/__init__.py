"""The official Python library for the Rewloy API.

    from rewloy import Rewloy

    rewloy = Rewloy(api_key=os.environ["REWLOY_API_KEY"])
    card = rewloy.get_pass("ABCD-EFGH-JKLM")

Every operation of the API is a method of ``Rewloy``, named by its operationId in snake_case and typed from the
OpenAPI document. The types are in ``rewloy.types``.
"""

from ._version import __version__
from .client import DEFAULT_BASE_URL, Rewloy
from .common import ApiResponse, AuthKind, Deprecation, Headers, HttpMethod, OperationMeta, Page, RateLimit, ResponseKind, parse_rate_limit
from .errors import RateLimitError, RewloyConnectionError, RewloyError, RewloyTimeoutError
from .generated.operations import API_VERSION, ERROR_TITLES, METHOD_NAMES, OPERATION_IDS, OPERATIONS
from .sse import EventStream, ServerSentEvent, SseParser
from .transport import HttpRequest, HttpResponse, StreamResponse, Transport, TransportError, TransportTimeout, UrllibTransport
from .webhooks import (
    PassEvent,
    PassEventData,
    WebhookEvent,
    WebhookSignatureError,
    WebhookTestEvent,
    sign_webhook,
    verify_webhook,
)

VERSION = __version__

__all__ = [
    "API_VERSION", "ApiResponse", "AuthKind", "DEFAULT_BASE_URL", "Deprecation", "ERROR_TITLES", "EventStream",
    "Headers", "HttpMethod", "HttpRequest", "HttpResponse", "METHOD_NAMES", "OPERATIONS", "OPERATION_IDS",
    "OperationMeta", "Page", "PassEvent", "PassEventData", "RateLimit", "RateLimitError", "ResponseKind", "Rewloy",
    "RewloyConnectionError", "RewloyError", "RewloyTimeoutError", "ServerSentEvent", "SseParser", "StreamResponse",
    "Transport", "TransportError", "TransportTimeout", "UrllibTransport", "VERSION", "WebhookEvent",
    "WebhookSignatureError", "WebhookTestEvent", "__version__", "parse_rate_limit", "sign_webhook", "verify_webhook",
]
