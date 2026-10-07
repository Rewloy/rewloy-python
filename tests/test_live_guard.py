"""The live suite's refusals, tested offline against a local stub (the live tests themselves need a DEV server)."""
from __future__ import annotations

from typing import Any, Callable

import pytest

from .helpers import Ctx, Stub
from .live.conftest import _guard

TEST_KEY = "rwk_test_abcdefghijklmnopqrstuvwxyz0123456789"


def answers(stub: Callable[[Any], Stub], payload: object, status: int = 200) -> Stub:
    return stub(lambda c: c.json(status, payload))


def test_dev_server_and_test_key_pass(stub: Callable[[Any], Stub]) -> None:
    s = answers(stub, {"data": {"version": "1.2.2", "apiVersion": "v1", "environment": "dev"}})
    _guard(s.url, TEST_KEY, None)
    assert s.last.url.endswith("/v1/meta")
    assert "authorization" not in {k.lower() for k in s.last.headers}  # the environment is asked without a credential


@pytest.mark.parametrize("payload", [
    {"data": {"version": "1.2.2", "apiVersion": "v1", "environment": "live"}},
    {"data": {"version": "1.2.2", "apiVersion": "v1"}},
    {"data": {"environment": "DEV"}},
    {"data": {"environment": None}},
])
def test_anything_but_dev_is_refused(stub: Callable[[Any], Stub], payload: object) -> None:
    s = answers(stub, payload)
    with pytest.raises(pytest.exit.Exception, match="not \"dev\""):
        _guard(s.url, TEST_KEY, None)
    assert len(s.requests) == 1  # nothing else was sent


def test_a_server_that_does_not_answer_meta_is_refused(stub: Callable[[Any], Stub]) -> None:
    s = answers(stub, {"error": {"code": "INTERNAL", "message": "x"}}, 500)
    with pytest.raises(pytest.exit.Exception, match="cannot tell"):
        _guard(s.url, TEST_KEY, None)


@pytest.mark.parametrize("key", ["rwk_abcdefghij_secretpart", "rws_staffsessiontoken", "rwk_live_abcdef", ""])
def test_only_a_test_key_is_accepted(stub: Callable[[Any], Stub], key: str) -> None:
    s = answers(stub, {"data": {"environment": "dev"}})
    with pytest.raises(pytest.exit.Exception, match="test-mode key"):
        _guard(s.url, key, None)


def test_the_staff_token_must_be_a_team_session(stub: Callable[[Any], Stub]) -> None:
    s = answers(stub, {"data": {"environment": "dev"}})
    with pytest.raises(pytest.exit.Exception, match="team session"):
        _guard(s.url, TEST_KEY, "rwk_test_abc")
