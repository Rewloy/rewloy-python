from __future__ import annotations

import logging
import warnings
from email.utils import formatdate
from typing import Callable, Dict

import pytest

from rewloy import RewloyError

from .helpers import KEY, LOCATION, SERIAL, Ctx, Stub, api_error, loose, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]


def deprecated(operation_id: str) -> Dict[str, str]:
    """What the platform sends on every answer of a deprecated operation (src/api/kit.ts ``deprecationHeaders``)."""
    link = f"https://rewloy.com/gelistiriciler/degisiklikler#{operation_id}"
    return {
        "Deprecation": "@1790985600",
        "Sunset": formatdate(1806537600, usegmt=True),  # Thu, 01 Apr 2027 00:00:00 GMT
        "Link": f'<{link}>; rel="deprecation"; type="text/html", <{link}>; rel="sunset"; type="text/html"',
    }


@pytest.fixture
def api(stub: StubFactory) -> Stub:
    def handle(c: Ctx) -> None:
        if c.req.url.startswith("/v1/passes/"):
            c.json(200, {"data": {"serial": SERIAL}}, deprecated("getPass"))
        elif c.req.url == "/v1/programs":
            c.json(200, {"data": []})
        else:
            c.json(404, api_error("PROGRAM_NOT_FOUND", 404, "Program bulunamadı"), deprecated("getProgram"))

    return stub(handle)


def test_warns_once_per_operation_naming_the_sunset_and_the_link(api: Stub) -> None:
    c = make_client(api)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        c.get_pass(SERIAL)
        assert len(caught) == 1
        w = caught[0]
        assert issubclass(w.category, DeprecationWarning)
        message = str(w.message)
        assert "getPass (GET /v1/passes/{serial}) is deprecated" in message
        assert "Sunset: Thu, 01 Apr 2027 00:00:00 GMT" in message
        assert "See https://rewloy.com/gelistiriciler/degisiklikler#getPass" in message
        # It points at the line that made the call (this file), not at the library.
        assert w.filename == __file__

        c.get_pass(SERIAL)
        make_client(api).get_pass(SERIAL)
        assert len(caught) == 1, "still one for get_pass, from any client"


def test_says_nothing_for_an_operation_that_is_not_deprecated(api: Stub) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_client(api).list_programs()
    assert caught == []


def test_warns_on_an_error_answer_too(api: Stub) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(RewloyError) as info:
            make_client(api, max_retries=0).get_program(LOCATION)
        assert info.value.code == "PROGRAM_NOT_FOUND"
    assert len(caught) == 1
    assert "get_program" not in str(caught[0].message) and "getProgram" in str(caught[0].message)


def test_warns_through_a_paginate_generator_and_request(api: Stub) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_client(api).request("getPass", path={"serial": SERIAL})
    assert len(caught) == 1
    assert caught[0].filename == __file__


def test_an_error_filter_does_not_lose_the_answer_of_a_call_that_went_through(api: Stub, caplog: pytest.LogCaptureFixture) -> None:
    """``-W error`` would raise from inside the call, after the server has acted: the answer wins, the notice is
    logged."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with caplog.at_level(logging.WARNING, logger="rewloy"):
            assert loose(make_client(api).get_pass(SERIAL)) == {"serial": SERIAL}
    assert any("getPass" in r.getMessage() and "deprecated" in r.getMessage() for r in caplog.records)


def test_the_link_header_without_a_deprecation_rel_gives_its_first_url(stub: StubFactory) -> None:
    s = stub(lambda c: c.json(200, {"data": {}}, {"Deprecation": "true", "Link": "<https://example.com/a>; rel=\"alternate\""}))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_client(s, api_key=KEY).get_pass(SERIAL)
    assert "See https://example.com/a" in str(caught[0].message)
    assert "Sunset" not in str(caught[0].message)
