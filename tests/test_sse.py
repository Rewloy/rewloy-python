from __future__ import annotations

import threading
import time
from typing import Callable, Iterable, Iterator, List, Tuple

import pytest

from rewloy import EventStream, RewloyError, RewloyTimeoutError, ServerSentEvent, SseParser

from .helpers import HOLDER, KEY, SERIAL, Ctx, Sleeps, Stub, api_error, eventually, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]


def parse(pieces: Iterable[str], last_event_id: str = "") -> Tuple[List[ServerSentEvent], SseParser]:
    """Parses text fed in the given pieces."""
    parser = SseParser(last_event_id)
    events: List[ServerSentEvent] = []
    for piece in pieces:
        events.extend(parser.push(piece))
    return events, parser


def cuts(text: str) -> Iterator[List[str]]:
    """Every way of cutting ``text`` in two, and one piece per character."""
    yield [text]
    yield list(text)
    for i in range(1, len(text)):
        yield [text[:i], text[i:]]


def ev(data: str, event: str = "message", id: str = "") -> ServerSentEvent:
    return ServerSentEvent(event, data, id)


class TestParser:
    def test_parses_the_apis_own_stream(self) -> None:
        text = 'retry: 5000\n\n: hb\n\nevent: event\ndata: {"kind":"earn","delta":2}\n\nevent: changed\ndata: 1\n\n'
        for pieces in cuts(text):
            events, parser = parse(pieces)
            assert events == [ev('{"kind":"earn","delta":2}', "event"), ev("1", "changed")], pieces
            assert parser.retry == 5000

    def test_takes_lf_cr_and_crlf_line_endings_wherever_a_piece_ends(self) -> None:
        expected = [ev("a\nb"), ev("c", "x")]
        for text in (
            "data: a\ndata: b\n\nevent: x\ndata: c\n\n",
            "data: a\rdata: b\r\revent: x\rdata: c\r\r",
            "data: a\r\ndata: b\r\n\r\nevent: x\r\ndata: c\r\n\r\n",
        ):
            for pieces in cuts(text):
                assert parse(pieces)[0] == expected, pieces

    def test_reads_fields_as_the_standard_says(self) -> None:
        events, parser = parse([
            "﻿data:no space\n",            # BOM dropped; no space after the colon
            "data:  two spaces\n",              # only one space is removed
            "data\n",                           # a field name alone: empty value
            "ignored: field\n",
            "id: 7\n\n",
            "data: next\n\n",                   # the last event ID carries over
            "id: bad\0id\ndata: x\n\n",         # an id with NULL is ignored
            "retry: 12a\nretry: 250\n",         # only digits count
            "event: lonely\n\n",                # no data: no event, and the type resets
            "data: after\n\n",
            "id\ndata: cleared\n\n",            # an empty id clears it
            "data: unfinished",                 # no blank line: dropped at the end
        ])
        assert events == [
            ev("no space\n two spaces\n", id="7"),
            ev("next", id="7"),
            ev("x", id="7"),
            ev("after", id="7"),
            ev("cleared", id=""),
        ]
        assert parser.retry == 250
        parser.end()
        assert parser.push("\n") == []

    def test_dispatches_an_event_whose_data_is_empty(self) -> None:
        assert parse(["data\n\ndata:\n\n"])[0] == [ev(""), ev("")]

    def test_starts_from_a_last_event_id_it_is_given(self) -> None:
        assert parse(["data: x\n\n"], "41")[0] == [ev("x", id="41")]

    def test_takes_the_last_event_id_at_a_blank_line_even_without_data(self) -> None:
        events, parser = parse(["id: 5\n\n", "id: 6\n"])
        assert events == []
        assert parser.last_event_id == "5"
        parser.push("\n")
        assert parser.last_event_id == "6"

    def test_an_event_parses_its_data_as_json(self) -> None:
        assert ev('{"a":[1,2]}').json() == {"a": [1, 2]}


def collect(stream: Iterable[ServerSentEvent]) -> List[ServerSentEvent]:
    return list(stream)


def test_decodes_utf8_split_across_chunks_and_lines_and_events_split_anywhere(stub: StubFactory) -> None:
    raw = 'event: event\r\ndata: {"name":"Ayşe","location":"Moda Şubesi"}\r\n\r\n: hb\r\n\r\n'.encode("utf-8")

    def handle(c: Ctx) -> None:
        sse = c.stream(headers={"Rewloy-Mode": "test"})
        for i in range(0, len(raw), 3):
            sse.write(raw[i : i + 3])
        sse.end()

    s = stub(handle)
    stream = make_client(s).stream("liveFeed", reconnect=False)
    assert collect(stream) == [ev('{"name":"Ayşe","location":"Moda Şubesi"}', "event")]
    assert stream.request_id == "req-live"
    assert stream.mode == "test"


def test_sends_the_credential_merchant_and_accept_and_parses_events_from_the_server(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream(chunked=False)  # close-delimited, as HTTP/1.0 servers do
        sse.write("retry: 5000\n\n")
        time.sleep(0.01)
        sse.write("event: event\nda")
        time.sleep(0.01)
        sse.write('ta: {"kind":"scan"}\n')
        time.sleep(0.01)
        sse.write("\n")
        sse.end()

    s = stub(handle)
    stream = make_client(s, staff_session="rws_x", merchant="m-1").live_feed(reconnect=False)
    assert collect(stream) == [ev('{"kind":"scan"}', "event")]
    assert stream.retry == 5.0
    h = s.requests[0].headers
    assert h["accept"] == "text/event-stream"
    assert h["authorization"] == "Bearer rws_x"
    assert h["rewloy-merchant"] == "m-1"
    assert h["cache-control"] == "no-cache"
    assert "last-event-id" not in h
    assert s.requests[0].url == "/v1/live"


def test_reconnects_after_the_servers_retry_delay_with_last_event_id(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write("retry: 1234\n\nid: 7\nevent: changed\ndata: 1\n\n" if c.n == 1 else "event: changed\ndata: 2\n\n")
        sse.end()

    s = stub(handle)
    sleeps = Sleeps()
    c = make_client(s, holder_session=HOLDER, sleep=sleeps)
    got: List[ServerSentEvent] = []
    for event in c.holder_card_events(SERIAL):
        got.append(event)
        if len(got) == 2:
            break
    assert got == [ev("1", "changed", "7"), ev("2", "changed", "7")]
    assert sleeps.seconds == [1.234]
    assert s.requests[0].url == f"/v1/holder/cards/{SERIAL}/events"
    assert s.requests[1].headers["last-event-id"] == "7"


def test_closes_the_connection_on_break_and_on_close_and_ends_quietly(stub: StubFactory) -> None:
    closed: List[int] = []

    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write("event: event\ndata: first\n\n")
        while c.wait(0.02):
            if not sse.write(": hb\n\n"):
                break
        closed.append(c.n)

    s = stub(handle)
    c = make_client(s)
    for event in c.live_feed():
        assert event.data == "first"
        break
    # close() from another thread ends the iteration quietly.
    stream = c.live_feed()
    timer = threading.Timer(0.15, stream.close)
    timer.start()
    assert [e.data for e in stream] == ["first"]
    timer.join()
    # The context manager closes it too.
    with c.live_feed() as managed:
        assert next(iter(managed)).data == "first"
    assert eventually(lambda: len(closed) == 3), closed
    assert len(s.requests) == 3


def test_ends_with_the_error_a_reconnection_cannot_fix(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        if c.n == 1:
            sse = c.stream()
            sse.write("event: changed\ndata: 1\n\n")
            sse.end()
        else:
            c.json(401, api_error("TOKEN_INVALID", 401, "Oturum geçersiz ya da süresi dolmuş; yeniden giriş yapın"))

    s = stub(handle)
    c = make_client(s, holder_session=HOLDER, sleep=Sleeps())
    got: List[str] = []
    with pytest.raises(RewloyError) as info:
        for event in c.holder_card_events(SERIAL):
            got.append(event.data)
    assert info.value.code == "TOKEN_INVALID"
    assert got == ["1"]
    assert len(s.requests) == 2


def test_reconnects_through_transient_failures(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        if c.n <= 4:
            c.json(503, api_error("INTERNAL", 503, "busy"))
        else:
            sse = c.stream()
            sse.write("data: back\n\n")
            sse.end()

    s = stub(handle)
    sleeps = Sleeps()
    c = make_client(s, sleep=sleeps, max_retries=1)
    for event in c.live_feed():
        assert event.data == "back"
        break
    # Two connections of two attempts each failed; the fifth request got through.
    assert len(s.requests) == 5
    assert len(sleeps.seconds) == 4


def test_treats_a_silent_connection_as_dropped(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write(": hb\n\n")
        c.hang()

    s = stub(handle)
    c = make_client(s)
    started = time.monotonic()
    with pytest.raises(RewloyTimeoutError, match="no data for 0.2 s"):
        collect(c.live_feed(reconnect=False, idle_timeout=0.2))
    assert time.monotonic() - started < 3


def test_reconnects_after_a_silent_connection(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        if c.n == 1:
            sse.write(": hb\n\n")
            c.hang()
        else:
            sse.write("data: alive\n\n")
            sse.end()

    s = stub(handle)
    sleeps = Sleeps()
    for event in make_client(s, sleep=sleeps).live_feed(idle_timeout=0.2):
        assert event.data == "alive"
        break
    assert len(s.requests) == 2
    # The wait after a drop is at least the server's retry delay (3 s by default) and backs off.
    assert sleeps.seconds[0] >= 3.0


def test_with_reconnect_off_the_end_of_the_connection_ends_the_stream(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write("data: only\n\n")
        sse.end()

    s = stub(handle)
    assert collect(make_client(s).live_feed(reconnect=False)) == [ev("only")]
    assert len(s.requests) == 1


def test_a_stream_is_iterated_once_and_nothing_is_sent_before(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write("data: x\n\n")
        sse.end()

    s = stub(handle)
    stream = make_client(s).live_feed(reconnect=False)
    assert isinstance(stream, EventStream)
    assert s.requests == []
    assert collect(stream) == [ev("x")]
    assert collect(stream) == []  # the same iterator, spent
    assert len(s.requests) == 1


def test_a_connection_that_breaks_mid_stream_is_a_connection_error_without_reconnect(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        sse = c.stream()
        sse.write("data: a\n\n")
        c.drop()

    s = stub(handle)
    got: List[str] = []
    stream = make_client(s, api_key=KEY).live_feed(reconnect=False)
    try:
        for event in stream:
            got.append(event.data)
    except RewloyError as err:
        assert err.code == "CONNECTION_ERROR"
    assert got == ["a"]
