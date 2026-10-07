"""Programs: create a stamp program and a gift card program, list them."""
from __future__ import annotations

from .conftest import World


def test_create_stamp_program(world: World) -> None:
    program = world.new_program({
        "type": "stamp", "businessName": f"Live {world.run}", "programName": f"Live stamp {world.run}",
        "maxStamps": 4, "rewardName": "Free coffee",
    })
    assert program["type"] == "stamp"
    assert program["status"] == "active"
    assert program["programName"] == f"Live stamp {world.run}"
    world.stamp_program = program


def test_create_gift_card_program(world: World) -> None:
    program = world.new_program({"type": "giftcard", "businessName": f"Live {world.run}", "programName": f"Live gift {world.run}"})
    assert program["type"] == "giftcard"
    world.gift_program = program


def test_list_and_get_programs(world: World) -> None:
    listed = {p["id"]: p for p in world.client.list_programs()}
    assert world.stamp_program["id"] in listed
    assert world.gift_program["id"] in listed
    fetched = world.client.get_program(world.stamp_program["id"])
    assert fetched["id"] == world.stamp_program["id"]
    assert fetched["type"] == "stamp"
