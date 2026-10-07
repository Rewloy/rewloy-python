"""Meta and business: the server says what it is, the key sees its test business."""
from __future__ import annotations

from typing import Any

from rewloy import Rewloy

from .conftest import World


def test_meta_says_dev(world: World) -> None:
    with Rewloy(base_url=world.base_url) as anonymous:
        meta: Any = anonymous.get_meta()  # 0.2.4's GetMetaData has no 'environment' yet (TODO 0.3.0)
    assert meta["environment"] == "dev"
    assert meta["apiVersion"] == "v1"
    assert meta["version"].count(".") == 2


def test_business_is_the_test_business(world: World) -> None:
    answer = world.client.request("getBusiness")
    assert answer.status == 200
    assert answer.mode == "test"
    business = answer.data
    assert business["name"].endswith("Test")  # the test business is named "<name> · Test"
    assert len(business["currency"]) == 3
    world.currency = business["currency"]


def test_a_location_exists(world: World) -> None:
    locations = world.client.request("listLocations").data
    assert locations, "the test business has no location"
    world.location_id = locations[0]["id"]
    assert not locations[0]["archived"]
