"""Webhook signatures, exactly as the platform signs a delivery::

    Rewloy-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>

The key is the whole secret as shown once when the webhook was created (``whsec_…``, prefix included); the message is
the timestamp, a dot and the body's bytes as they arrived. Each delivery attempt is signed anew, so a retry carries a
fresh ``t``.

Every delivery also carries ``Rewloy-Event`` (the event type, as ``type`` in the body) and ``Rewloy-Delivery`` (the
delivery's id: the same on every retry of one delivery; deliveries are at least once, so skip an id already handled).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional, Sequence, TypedDict, Union, cast

PayloadLike = Union[str, bytes, bytearray, memoryview]


class PassEventData(TypedDict, total=False):
    """What a webhook's ``data`` holds for the ``pass.*`` events (only business facts, never contact details). New
    keys may appear without notice."""

    #: What happened on the card: ``join``, ``earn``, ``redeem``, ``spend``, ``visit_credit``, ``load``, ``void``…
    kind: str
    #: The card's serial number, XXXX-XXXX-XXXX.
    card: Optional[str]
    program_id: Optional[str]
    location_id: Optional[str]
    customer_id: Optional[str]
    #: What ``delta`` counts: ``stamp``, ``point``, ``try_minor`` (kuruş)…
    unit: str
    delta: int
    reward: Any
    use: Any
    reason: str


class PassEvent(TypedDict):
    """A ``pass.issued``, ``pass.activity`` or ``pass.voided`` delivery."""

    #: The event's id.
    id: str
    type: Literal["pass.issued", "pass.activity", "pass.voided"]
    created_at: str
    data: PassEventData


class WebhookTestData(TypedDict):
    message: str


class WebhookTestEvent(TypedDict):
    """The panel's or ``test_webhook``'s test delivery: no event behind it (and no ``id``)."""

    type: Literal["webhook.test"]
    created_at: str
    data: WebhookTestData


#: A webhook delivery's body. Read the person behind ``customer_id`` from the API; new event types may appear, so keep
#: a default branch.
WebhookEvent = Union[PassEvent, WebhookTestEvent]

#: Why a delivery was refused.
WebhookSignatureReason = Literal["missing", "malformed", "expired", "mismatch", "payload"]

_V1 = re.compile(r"[0-9a-fA-F]{64}")
_DIGITS = re.compile(r"[0-9]+")


class WebhookSignatureError(Exception):
    """The delivery is not a genuine one: answer it with 400 and do not act on it."""

    reason: WebhookSignatureReason

    def __init__(self, reason: WebhookSignatureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _bytes_of(payload: object) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    raise TypeError("verify_webhook: `payload` must be the raw body (str or bytes), not a parsed object")


def _signature(secret: str, t: str, body: bytes) -> bytes:
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(f"{t}.".encode("ascii"))
    mac.update(body)
    return mac.digest()


def _seconds(now: Union[int, float, datetime, None]) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        return (now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)).timestamp()
    return float(now)


def verify_webhook(
    payload: PayloadLike,
    header: Union[str, Sequence[str], None],
    secret: Union[str, Sequence[str]],
    *,
    tolerance: float = 300,
    now: Union[int, float, datetime, None] = None,
) -> WebhookEvent:
    """Checks a delivery's ``Rewloy-Signature`` and returns its parsed body.

    ``payload`` is the body exactly as it arrived: ``str`` or ``bytes``, never a parsed object (parsing and
    re-serializing changes the bytes the signature covers: in Flask use ``request.get_data()``, in Django
    ``request.body``). ``header`` is the ``Rewloy-Signature`` header (several values are joined). ``secret`` is the
    webhook's secret (``whsec_…``); a list of them while you move from one webhook to another. ``tolerance`` is how
    far ``t`` may be from ``now``, in seconds; ``now`` is Unix seconds or a ``datetime`` (for tests).

    Raises ``WebhookSignatureError`` (``reason``: ``missing``, ``malformed``, ``expired``, ``mismatch`` or
    ``payload``) when the header is missing or malformed, ``t`` is further than ``tolerance`` seconds from now, no
    ``v1`` matches, or the signed body is not a JSON object. The comparison takes constant time. A wrong *type* of
    ``payload``, or an empty ``secret``, is a ``TypeError`` or ``ValueError``: a programming error, not a refusal.
    """
    body = _bytes_of(payload)
    secrets = [secret] if isinstance(secret, str) else list(secret)
    secrets = [s for s in secrets if s != ""]
    if not secrets:
        raise ValueError("verify_webhook: `secret` is empty")

    if isinstance(header, str):
        value = header
    elif header is None:
        value = ""
    else:
        value = ",".join(header)
    if not value.strip():
        raise WebhookSignatureError("missing", "No Rewloy-Signature header")
    t: Optional[str] = None
    candidates: List[bytes] = []
    for part in value.split(","):
        eq = part.find("=")
        if eq == -1:
            continue
        key = part[:eq].strip()
        val = part[eq + 1 :].strip()
        if key == "t" and t is None:
            t = val
        elif key == "v1" and _V1.fullmatch(val):
            candidates.append(bytes.fromhex(val))
    if t is None or not _DIGITS.fullmatch(t) or not candidates:
        raise WebhookSignatureError("malformed", 'Rewloy-Signature is not "t=<unix seconds>,v1=<hex>"')

    if abs(_seconds(now) - int(t)) > tolerance:
        raise WebhookSignatureError("expired", f"The signature's time (t={t}) is more than {tolerance:g} seconds from now")

    match = False
    for s in secrets:
        expected = _signature(s, t, body)
        for candidate in candidates:
            # Every pair is compared, in constant time, whether or not one matched already.
            match = hmac.compare_digest(candidate, expected) or match
    if not match:
        raise WebhookSignatureError("mismatch", "No v1 signature matches the body and the secret")

    try:
        event: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise WebhookSignatureError("payload", "The signed body is not JSON") from err
    if not isinstance(event, dict):
        raise WebhookSignatureError("payload", "The signed body is not a JSON object")
    return cast(WebhookEvent, event)


def sign_webhook(payload: PayloadLike, secret: str, *, timestamp: Optional[int] = None) -> str:
    """The ``Rewloy-Signature`` header the platform would send for this body: for testing your own webhook handler.
    ``timestamp`` is Unix seconds; default now."""
    t = str(int(time.time()) if timestamp is None else int(timestamp))
    return f"t={t},v1={_signature(secret, t, _bytes_of(payload)).hex()}"


__all__ = [
    "PassEvent", "PassEventData", "WebhookTestEvent", "WebhookTestData", "WebhookEvent", "WebhookSignatureError",
    "WebhookSignatureReason", "sign_webhook", "verify_webhook",
]
