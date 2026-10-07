"""resetTestEnvironment, the very last test: leaves the test business clean.

The endpoint takes a team session, not an API key (a key gets 403 CREDENTIAL_NOT_ALLOWED, checked in the errors
area), so this runs only when REWLOY_STAFF_TOKEN is set. A business may reset five times a day.
"""
from __future__ import annotations

import pytest

from rewloy import RewloyError

from .conftest import ENV_STAFF, World


def test_reset_test_environment(world: World) -> None:
    if world.staff is None:
        pytest.skip(f"set {ENV_STAFF} (a team session, rws_...) to run the reset; keys may not call it")
    try:
        result = world.staff.reset_test_environment()
    except RewloyError as err:
        if err.code == "RATE_LIMITED":
            pytest.skip("RATE_LIMITED: a business resets at most 5 times a day; try again tomorrow")
        raise
    assert result["created"] is False
    assert result["closed"] is None
    assert result["keysRevoked"] is False
    assert result["deleted"]["customers"] >= 4
    assert result["deleted"]["cards"] >= 6
    assert result["deleted"]["codes"] >= 2
    assert result["kept"]["programs"] >= 2
    assert result["kept"]["keys"] >= 1  # the key this run uses
    world.state["reset_done"] = True


def test_the_test_business_is_clean_afterwards(world: World) -> None:
    if not world.state.get("reset_done"):
        pytest.skip("no reset ran")
    assert world.client.list_customers().meta["total"] == 0
    assert world.client.list_all_batches().meta["total"] == 0
    with pytest.raises(RewloyError) as gone:
        world.client.get_pass(world.state["stamp_a"])
    assert gone.value.code == "PASS_NOT_FOUND"
    assert world.client.get_business()["id"]  # the key still works: the reset keeps keys
