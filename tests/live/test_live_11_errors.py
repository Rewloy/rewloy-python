"""Error objects: code, status, request id, details."""
from __future__ import annotations

import pytest

from rewloy import Rewloy, RewloyError

from .conftest import World


def test_404_error_object(world: World) -> None:
    with pytest.raises(RewloyError) as caught:
        world.client.get_pass("ZZZZ-ZZZZ-ZZZZ")
    err = caught.value
    assert err.status == 404
    assert err.code == "PASS_NOT_FOUND"
    assert err.request_id
    assert err.title and err.detail
    assert err.rate_limit is not None  # errors carry the RateLimit-* headers too
    assert err.operation == "getPass"


def test_validation_error_object(world: World) -> None:
    with pytest.raises(RewloyError) as caught:
        world.client.create_program(body={"type": "nope", "businessName": "x"})
    err = caught.value
    assert (err.status, err.code) == (400, "VALIDATION")
    assert err.request_id
    assert err.details and err.details[0]["field"] == "type"
    assert err.details[0]["rule"] == "enum"


def test_wrong_credential_and_wrong_kind_of_credential(world: World) -> None:
    with Rewloy(api_key="rwk_test_" + "a" * 40, base_url=world.base_url) as bogus:
        with pytest.raises(RewloyError) as unknown:
            bogus.get_business()
    assert (unknown.value.status, unknown.value.code) == (401, "INVALID_API_KEY")
    with pytest.raises(RewloyError) as kind:  # resetTestEnvironment wants a team session, not a key
        world.client.reset_test_environment()
    assert (kind.value.status, kind.value.code) == (403, "CREDENTIAL_NOT_ALLOWED")
