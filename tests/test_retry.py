from __future__ import annotations

import time
from typing import Callable

import pytest

from rewloy import RateLimitError, RewloyConnectionError, RewloyError, RewloyTimeoutError
from rewloy.client import backoff, parse_retry_after

from .helpers import LOCATION, loose, SERIAL, Ctx, Sleeps, Stub, api_error, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]

ACTION = {"action": "earn-stamps", "locationId": LOCATION}


def test_backoff_doubles_from_half_a_second_up_to_eight_with_jitter_between_half_and_all_of_it() -> None:
    assert backoff(0, lambda: 0) == 0.25
    assert backoff(0, lambda: 1) == 0.5
    assert backoff(1, lambda: 1) == 1.0
    assert backoff(2, lambda: 0.5) == 1.5
    assert backoff(10, lambda: 1) == 8.0
    assert backoff(10, lambda: 0) == 4.0


def test_reads_retry_after_as_seconds_or_an_http_date() -> None:
    assert parse_retry_after("2") == 2
    assert parse_retry_after("1.5") == 1.5
    now = 1790000000.0  # 2026-09-21T14:13:20Z
    assert parse_retry_after("Mon, 21 Sep 2026 14:13:23 GMT", now) == 3
    assert parse_retry_after("Mon, 21 Sep 2026 14:12:00 GMT", now) == 0
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    assert parse_retry_after("") is None


def test_retries_a_get_on_502_503_504_with_backoff_then_succeeds(stub: StubFactory) -> None:
    statuses = [503, 502, 200]

    def handle(c: Ctx) -> None:
        status = statuses[c.n - 1]
        c.json(status, {"data": {"ok": c.n}} if status == 200 else api_error("INTERNAL", status, "x"))

    s = stub(handle)
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps)
    assert loose(c.get_pass(SERIAL)) == {"ok": 3}
    assert len(s.requests) == 3
    assert len(sleeps.seconds) == 2
    assert 0.25 <= sleeps.seconds[0] <= 0.5
    assert 0.5 <= sleeps.seconds[1] <= 1.0


@pytest.mark.parametrize("status", [502, 503, 504, 520, 521, 522, 523, 524, 429])
def test_retries_each_status_of_the_list(stub: StubFactory, status: int) -> None:
    s = stub(lambda c: c.json(status if c.n == 1 else 200, api_error("INTERNAL", status, "x") if c.n == 1 else {"data": {"ok": True}}))
    assert loose(make_client(s).get_pass(SERIAL)) == {"ok": True}
    assert len(s.requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 500, 501, 505, 519, 525])
def test_does_not_retry_the_other_statuses(stub: StubFactory, status: int) -> None:
    s = stub(lambda c: c.json(status, api_error("INTERNAL", status, "x")))
    with pytest.raises(RewloyError) as info:
        make_client(s).get_pass(SERIAL)
    assert info.value.status == status
    assert len(s.requests) == 1


def test_gives_up_after_max_retries_and_raises_the_last_answer(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(504, api_error("INTERNAL", 504, "gateway")))
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps)
    with pytest.raises(RewloyError) as info:
        c.get_pass(SERIAL)
    assert info.value.status == 504
    assert len(s.requests) == 3
    assert len(sleeps.seconds) == 2
    with pytest.raises(RewloyError):
        c.get_pass(SERIAL, max_retries=0)
    assert len(s.requests) == 4
    with pytest.raises(RewloyError):
        make_client(s, sleep=sleeps, max_retries=5).get_pass(SERIAL)
    assert len(s.requests) == 10


def test_honours_retry_after_on_429(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(429, api_error("RATE_LIMITED", 429, "Bu anahtarın dakikalık istek sınırı aşıldı", {"retryAfterSec": 2}), {"Retry-After": "2"}) if c.n == 1 else c.json(200, {"data": []}))
    sleeps = Sleeps()
    assert make_client(s, sleep=sleeps).list_programs() == []
    assert sleeps.seconds == [2.0]


def test_does_not_wait_out_a_long_retry_after_the_caller_gets_rate_limit_error(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(429, api_error("RATE_LIMITED", 429, "Çok fazla hatalı kod.", {"retryAfterSec": 900}), {"Retry-After": "900"}))
    sleeps = Sleeps()
    with pytest.raises(RateLimitError) as info:
        make_client(s, sleep=sleeps).list_programs()
    assert info.value.retry_after == 900
    assert len(s.requests) == 1
    assert sleeps.seconds == []


def test_a_retry_after_of_exactly_sixty_seconds_is_waited_for(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(503, api_error("INTERNAL", 503, "busy"), {"Retry-After": "60"}) if c.n == 1 else c.json(200, {"data": []}))
    sleeps = Sleeps()
    make_client(s, sleep=sleeps).list_programs()
    assert sleeps.seconds == [60.0]


def test_never_retries_a_post_without_an_idempotency_key_nor_a_patch(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(503, api_error("INTERNAL", 503, "busy")))
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps)
    with pytest.raises(RewloyError) as info:
        c.create_segment(body={"name": "Sabit müşteriler", "rule": {"minVisits": 3}})  # createSegment takes no key
    assert info.value.status == 503
    assert len(s.requests) == 1
    with pytest.raises(RewloyError):
        c.update_program(LOCATION, body={})
    assert len(s.requests) == 2
    assert sleeps.seconds == []


def test_retries_put_and_delete(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        if c.n % 2 == 1:
            c.json(503, api_error("INTERNAL", 503, "busy"))
        elif c.n == 2:
            c.json(200, {"data": {"hosts": []}})
        else:
            c.raw(204)

    s = stub(handle)
    c = make_client(s)
    c.set_embed_hosts(body={"hosts": []})
    c.unblock_email("abc")
    assert [r.method for r in s.requests] == ["PUT", "PUT", "DELETE", "DELETE"]


def test_retries_a_till_action_with_the_same_idempotency_key(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(503, api_error("INTERNAL", 503, "busy")) if c.n == 1 else c.json(200, {"data": {"balance": 3, "duplicate": False}}))
    c = make_client(s)
    assert c.pass_action(SERIAL, body=ACTION, idempotency_key="fis-42-0001") == {"balance": 3, "duplicate": False}  # type: ignore[arg-type,comparison-overlap]
    assert len(s.requests) == 2
    assert [r.headers["idempotency-key"] for r in s.requests] == ["fis-42-0001", "fis-42-0001"]


def test_waits_out_idempotency_in_progress_on_a_campaign_send_then_reads_the_replayed_answer(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(409, api_error("IDEMPOTENCY_IN_PROGRESS", 409, "Bu anahtarla gelen ilk istek hâlâ işleniyor")) if c.n == 1 else c.json(201, {"data": {"id": "c1"}}, {"Idempotent-Replayed": "true"}))
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps)
    res = c.request("sendCampaign", body={"body": "Merhaba"}, idempotency_key="kampanya-2026-10-03")
    assert res.replayed is True
    assert len(sleeps.seconds) == 1
    assert [r.headers["idempotency-key"] for r in s.requests] == ["kampanya-2026-10-03"] * 2


def test_another_409_is_not_retried(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(409, api_error("IDEMPOTENCY_KEY_REUSED", 409, "x")))
    with pytest.raises(RewloyError) as info:
        make_client(s).request("sendCampaign", body={"body": "Merhaba"}, idempotency_key="kampanya-0001")
    assert info.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert len(s.requests) == 1


def test_retries_when_the_connection_breaks_for_a_get_only(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        if c.n in (1, 3):
            c.drop()
        else:
            c.json(200, {"data": {"ok": True}})

    s = stub(handle)
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps)
    assert loose(c.get_pass(SERIAL)) == {"ok": True}
    assert len(sleeps.seconds) == 1
    with pytest.raises(RewloyConnectionError) as info:
        c.create_segment(body={"name": "Sabit müşteriler", "rule": {"minVisits": 3}})
    assert info.value.status == 0
    assert info.value.code == "CONNECTION_ERROR"
    assert len(s.requests) == 3


def test_times_out_a_silent_attempt_and_retries_it(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        if c.n == 1:
            c.hang()
        else:
            c.json(200, {"data": {"ok": True}})

    s = stub(handle)
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps, timeout=0.15)
    assert loose(c.get_pass(SERIAL)) == {"ok": True}
    assert len(s.requests) == 2
    assert len(sleeps.seconds) == 1


def test_raises_timeout_error_when_every_attempt_times_out(stub: StubFactory) -> None:
    s = stub(lambda c: c.hang())
    c = make_client(s, timeout=0.1, max_retries=1)
    with pytest.raises(RewloyTimeoutError) as info:
        c.get_pass(SERIAL)
    assert info.value.code == "TIMEOUT"
    assert isinstance(info.value, RewloyConnectionError)
    assert info.value.status == 0
    assert info.value.operation == "getPass"
    assert len(s.requests) == 2
    # A per-call timeout wins over the client's.
    with pytest.raises(RewloyTimeoutError):
        make_client(s, max_retries=0).get_pass(SERIAL, timeout=0.1)


def test_the_timeout_covers_the_whole_body_not_just_each_read(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        c._h.send_response(200)  # a body that trickles: one byte every 0.1 s, never idle for long
        c._h.send_header("Content-Type", "application/json")
        c._h.send_header("Content-Length", "60")
        c._h.end_headers()
        for _ in range(60):
            if not c.wait(0.1):
                return
            try:
                c._h.wfile.write(b" ")
                c._h.wfile.flush()
            except OSError:
                return

    s = stub(handle)
    started = time.monotonic()
    with pytest.raises(RewloyTimeoutError):
        make_client(s, timeout=0.5, max_retries=0).get_pass(SERIAL)
    assert time.monotonic() - started < 3


def test_a_connection_that_cannot_be_made_is_a_connection_error(stub: StubFactory) -> None:
    closed = stub(lambda c: c.raw(200))
    closed.close()
    c = make_client(closed, max_retries=0)
    with pytest.raises(RewloyConnectionError) as info:
        c.get_pass(SERIAL)
    assert info.value.code == "CONNECTION_ERROR"
    assert info.value.status == 0
    assert info.value.operation == "getPass"
    assert info.value.__cause__ is not None


def test_a_redirect_is_not_followed_it_is_an_error_answer(stub: StubFactory) -> None:
    target = stub(lambda c: c.json(200, {"data": {"leaked": True}}))
    s = stub(lambda c: c.raw(302, headers={"Location": target.url + "/elsewhere"}))
    with pytest.raises(RewloyError) as info:
        make_client(s, max_retries=0).get_pass(SERIAL)
    assert info.value.status == 302
    assert info.value.code == "HTTP_302"
    assert target.requests == []
