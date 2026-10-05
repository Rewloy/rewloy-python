from __future__ import annotations

import socket
import threading
import time
from typing import Any, Callable, Iterator

import pytest

from rewloy import HttpRequest, Rewloy, RewloyConnectionError, RewloyError, UrllibTransport

from .helpers import KEY, SERIAL, Ctx, Stub, api_error, loose, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]


@pytest.fixture(params=["urllib", "httpx"])
def transport(request: pytest.FixtureRequest) -> Iterator[Any]:
    if request.param == "httpx":
        httpx = pytest.importorskip("httpx")
        from rewloy.httpx_transport import HttpxTransport

        t: Any = HttpxTransport(httpx.Client(trust_env=False))
    else:
        t = UrllibTransport(proxies={})
    yield t
    t.close()


def test_a_json_answer_and_the_headers_a_request_sends(stub: StubFactory, transport: Any) -> None:
    s = stub(lambda c: c.json(200, {"data": {"serial": SERIAL}}, {"Rewloy-Mode": "test"}))
    c = Rewloy(api_key=KEY, base_url=s.url, transport=transport, user_agent="x/1")
    res = c.request("getPass", path={"serial": SERIAL})
    assert loose(res.data) == {"serial": SERIAL}
    assert res.mode == "test"
    assert res.request_id == "req-0001"
    assert s.last.headers["authorization"] == f"Bearer {KEY}"
    assert "x/1" in s.last.headers["user-agent"]
    assert "python-urllib" not in s.last.headers["user-agent"].lower()
    assert "httpx" not in s.last.headers["user-agent"].lower()


def test_a_body_a_204_and_a_blob(stub: StubFactory, transport: Any) -> None:
    def handle(c: Ctx) -> None:
        if c.req.method == "DELETE":
            c.raw(204)
        elif c.req.url.endswith("/map.png"):
            c.raw(200, b"\x89PNG\r\n", {"Content-Type": "image/png"})
        else:
            c.json(201, {"data": {"id": "c1", "echo": c.req.json()}})

    s = stub(handle)
    c = Rewloy(api_key=KEY, base_url=s.url, transport=transport)
    res = c.request("sendCampaign", body={"body": "Merhaba ğüşıöç"}, idempotency_key="kampanya-0001")
    assert res.status == 201
    assert res.data["echo"] == {"body": "Merhaba ğüşıöç"}
    c.revoke_api_key("k1")
    assert c.location_map("l1") == b"\x89PNG\r\n"


def test_no_redirect_is_followed(stub: StubFactory, transport: Any) -> None:
    target = stub(lambda c: c.json(200, {"data": {}}))
    s = stub(lambda c: c.raw(301, headers={"Location": target.url}))
    with pytest.raises(RewloyError) as info:
        Rewloy(api_key=KEY, base_url=s.url, transport=transport, max_retries=0).get_pass(SERIAL)
    assert info.value.code == "HTTP_301"
    assert target.requests == []


def test_a_refused_connection_is_a_connection_error(stub: StubFactory, transport: Any) -> None:
    s = stub(lambda c: c.raw(200))
    s.close()
    with pytest.raises(RewloyConnectionError):
        Rewloy(api_key=KEY, base_url=s.url, transport=transport, max_retries=0).get_pass(SERIAL)


def test_a_stream_arrives_piece_by_piece(stub: StubFactory, transport: Any) -> None:
    gate = threading.Event()

    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write("data: one\n\n")
        gate.wait(5)
        sse.write("data: two\n\n")
        sse.end()

    s = stub(handle)
    c = Rewloy(api_key=KEY, base_url=s.url, transport=transport)
    stream = c.live_feed(reconnect=False)
    first = next(stream)
    assert first.data == "one"  # the first event is in hand while the connection is still open
    gate.set()
    assert next(stream).data == "two"
    assert list(stream) == []


def test_a_stream_is_closed_from_another_thread(stub: StubFactory, transport: Any) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write(": hb\n\n")
        c.hang(10)

    s = stub(handle)
    stream = Rewloy(api_key=KEY, base_url=s.url, transport=transport).live_feed()
    threading.Timer(0.2, stream.close).start()
    started = time.monotonic()
    assert list(stream) == []
    assert time.monotonic() - started < 3


def test_the_urllib_transport_speaks_only_http_and_https() -> None:
    t = UrllibTransport(proxies={})
    from rewloy import TransportError

    for url in ("file:///etc/hostname", "ftp://127.0.0.1/x", "data:text/plain,hi"):
        with pytest.raises(TransportError):
            t.send(HttpRequest("GET", url, {}, None, 1.0))


def test_the_urllib_transport_makes_a_slow_body_time_out_as_a_whole(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        c._h.send_response(200)
        c._h.send_header("Content-Length", "50")
        c._h.end_headers()
        for _ in range(50):
            if not c.wait(0.1):
                return
            try:
                c._h.wfile.write(b"x")
                c._h.wfile.flush()
            except OSError:
                return

    s = stub(handle)
    from rewloy import TransportTimeout

    started = time.monotonic()
    with pytest.raises(TransportTimeout):
        UrllibTransport(proxies={}).send(HttpRequest("GET", s.url + "/x", {}, None, 0.5))
    assert time.monotonic() - started < 3


def test_a_server_that_is_slow_to_answer_times_out_at_the_headers(stub: StubFactory) -> None:
    s = stub(lambda c: c.hang())
    from rewloy import TransportTimeout

    with pytest.raises(TransportTimeout):
        UrllibTransport(proxies={}).send(HttpRequest("GET", s.url + "/x", {}, None, 0.2))


def test_no_timeout_means_no_limit(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        time.sleep(0.3)
        c.json(200, {"data": {"ok": True}})

    s = stub(handle)
    c = make_client(s, timeout=0)
    assert loose(c.get_pass(SERIAL)) == {"ok": True}


def test_an_error_answer_to_a_stream_is_read_and_raised(stub: StubFactory, transport: Any) -> None:
    s = stub(lambda c: c.json(403, api_error("FORBIDDEN", 403, "yetkiniz yok")))
    c = Rewloy(api_key=KEY, base_url=s.url, transport=transport)
    with pytest.raises(RewloyError) as info:
        list(c.live_feed())
    assert info.value.status == 403 and info.value.code == "FORBIDDEN"
    assert info.value.operation == "liveFeed"


def test_a_closed_port_is_a_quick_failure() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    started = time.monotonic()
    with pytest.raises(RewloyConnectionError):
        make_client(None, base_url=f"http://127.0.0.1:{port}", max_retries=0).get_pass(SERIAL)
    assert time.monotonic() - started < 3
