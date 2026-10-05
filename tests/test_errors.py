from __future__ import annotations

import copy
import pickle
from typing import Callable

import pytest

from rewloy import ERROR_TITLES, Headers, RateLimitError, RewloyConnectionError, RewloyError, RewloyTimeoutError

from .helpers import LOCATION, SERIAL, Ctx, Stub, api_error, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]


def test_maps_an_api_error_body(stub: StubFactory) -> None:
    body = api_error("INSUFFICIENT_BALANCE", 409, "bakiye yetersiz: 40,00 ₺ var")
    s = stub(lambda c: c.json(409, body, {"X-Request-Id": "0192f7c1-8b2e-7a31-9c1d-000000000009"}))
    with pytest.raises(RewloyError) as info:
        make_client(s, max_retries=0).pass_action(SERIAL, body={"action": "spend", "locationId": LOCATION, "amountMinor": 5000}, idempotency_key="fis-000123")
    err = info.value
    assert type(err) is RewloyError
    assert not isinstance(err, RateLimitError)
    assert err.status == 409
    assert err.code == "INSUFFICIENT_BALANCE"
    assert err.title == "Bakiye yetersiz"
    assert err.title == ERROR_TITLES["INSUFFICIENT_BALANCE"]
    assert err.detail == "bakiye yetersiz: 40,00 ₺ var"
    assert err.docs == "https://rewloy.com/gelistiriciler/hatalar#INSUFFICIENT_BALANCE"
    assert err.request_id == "0192f7c1-8b2e-7a31-9c1d-000000000009", "the header wins over the body"
    assert err.operation == "passAction"
    assert err.body == body
    assert isinstance(err.headers, Headers)
    assert str(err) == "409 INSUFFICIENT_BALANCE: bakiye yetersiz: 40,00 ₺ var (passAction, request_id 0192f7c1-8b2e-7a31-9c1d-000000000009)"
    assert isinstance(err, Exception)


def test_keeps_the_validation_details(stub: StubFactory) -> None:
    details = [{"field": "body", "rule": "maxLength", "message": "en fazla 180 karakter olmalı"}]
    s = stub(lambda c: c.json(400, api_error("VALIDATION", 400, "Gönderilen bilgiler geçersiz (gövde): body en fazla 180 karakter olmalı", details)))
    with pytest.raises(RewloyError) as info:
        make_client(s).send_campaign(body={"body": "x" * 200}, idempotency_key="kampanya-0001")
    assert info.value.code == "VALIDATION"
    assert info.value.details == details
    assert info.value.title == "Gönderilen bilgiler geçersiz"


def test_makes_429_a_rate_limit_error_with_retry_after_from_the_header_else_from_the_details(stub: StubFactory) -> None:
    answers = {
        "header": ({"Retry-After": "7"}, api_error("RATE_LIMITED", 429, "sınır", {"retryAfterSec": 12})),
        "details": ({}, api_error("RATE_LIMITED", 429, "çok fazla canlı bağlantı", {"retryAfterSec": 12})),
        "none": ({}, api_error("RATE_LIMITED", 429, "çok fazla canlı bağlantı")),
    }
    expected = {"header": 7, "details": 12, "none": None}
    for name, (headers, body) in answers.items():
        s = stub(lambda c, h=headers, b=body: c.json(429, b, h))  # type: ignore[misc]
        with pytest.raises(RateLimitError) as info:
            make_client(s, max_retries=0).list_programs()
        assert info.value.retry_after == expected[name], name
        assert isinstance(info.value, RewloyError)


def test_names_an_answer_that_is_not_rewloys_by_its_status(stub: StubFactory) -> None:
    s = stub(lambda c: c.raw(502, b"<html><body>Bad gateway</body></html>", {"Content-Type": "text/html"}))
    with pytest.raises(RewloyError) as info:
        make_client(s, max_retries=0).get_pass(SERIAL)
    err = info.value
    assert err.status == 502
    assert err.code == "HTTP_502"
    assert err.detail == "Bad Gateway"
    assert err.title is None
    assert err.request_id is None
    assert err.body == "<html><body>Bad gateway</body></html>"


def test_refuses_a_2xx_answer_that_is_not_the_documented_json(stub: StubFactory) -> None:
    html = stub(lambda c: c.raw(200, b"<html>captive portal</html>", {"Content-Type": "text/html"}))
    with pytest.raises(RewloyError) as info:
        make_client(html).get_pass(SERIAL)
    assert info.value.code == "INVALID_RESPONSE"
    assert info.value.status == 200
    assert len(html.requests) == 1  # never retried
    no_envelope = stub(lambda c: c.json(200, {"serial": SERIAL}))
    with pytest.raises(RewloyError) as info2:
        make_client(no_envelope).get_pass(SERIAL)
    assert info2.value.code == "INVALID_RESPONSE"
    no_meta = stub(lambda c: c.json(200, {"data": []}))
    with pytest.raises(RewloyError) as info3:
        make_client(no_meta).list_customers()
    assert info3.value.code == "INVALID_RESPONSE"
    bad_bytes = stub(lambda c: c.raw(200, b"\xff\xfe", {"Content-Type": "application/json"}))
    with pytest.raises(RewloyError) as info4:
        make_client(bad_bytes).get_pass(SERIAL)
    assert info4.value.code == "INVALID_RESPONSE"


def test_the_error_classes_say_what_they_are() -> None:
    timeout = RewloyTimeoutError(detail="no answer within 60 s", operation="getPass")
    assert isinstance(timeout, RewloyConnectionError) and isinstance(timeout, RewloyError)
    assert (timeout.status, timeout.code) == (0, "TIMEOUT")
    connection = RewloyConnectionError(detail="refused")
    assert (connection.status, connection.code) == (0, "CONNECTION_ERROR")
    assert str(connection) == "CONNECTION_ERROR: refused"


def test_errors_survive_pickle_and_copy() -> None:
    err = RateLimitError(status=429, code="RATE_LIMITED", detail="sınır", retry_after=7, request_id="r1", operation="listPrograms", details={"retryAfterSec": 7})
    for clone in (pickle.loads(pickle.dumps(err)), copy.copy(err), copy.deepcopy(err)):
        assert type(clone) is RateLimitError
        assert clone.retry_after == 7
        assert clone.request_id == "r1"
        assert clone.details == {"retryAfterSec": 7}
        assert str(clone) == str(err)
    timeout = pickle.loads(pickle.dumps(RewloyTimeoutError(detail="x", operation="getPass")))
    assert type(timeout) is RewloyTimeoutError and timeout.code == "TIMEOUT"
