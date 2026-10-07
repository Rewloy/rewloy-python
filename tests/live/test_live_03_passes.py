"""Passes: issue, get, the till view; one card of each kind for the areas that follow."""
from __future__ import annotations

from typing import Any, Dict

from .conftest import World


def _issue(world: World, program: Dict[str, Any], tag: str, **extra: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"programId": program["id"], "email": world.email(tag), "firstName": "Live", "kvkkConsent": True}
    body.update(extra)
    issued = world.client.issue_pass(body=body)
    assert issued["created"] is True
    assert issued["serial"]
    assert issued["cardUrl"].startswith(world.base_url.rstrip("/"))
    return dict(issued)


def test_issue_stamp_pass(world: World) -> None:
    issued = _issue(world, world.stamp_program, "stamp-a")
    world.state["stamp_a"] = issued["serial"]


def test_get_stamp_pass(world: World) -> None:
    card = world.client.get_pass(world.state["stamp_a"])
    assert card["type"] == "stamp"
    assert card["programId"] == world.stamp_program["id"]
    assert card["stamps"] == {"count": 0, "max": 4}
    assert card["balance"] == 0
    assert {a["action"] for a in card["actions"]} >= {"earn-stamps", "redeem-stamps"}
    redeem = next(a for a in card["actions"] if a["action"] == "redeem-stamps")
    assert redeem["ready"] is False


def test_issue_again_returns_the_same_card(world: World) -> None:
    again = world.client.issue_pass(body={
        "programId": world.stamp_program["id"], "email": world.emails[-1], "kvkkConsent": True, "ifExists": "return",
    })
    assert again["created"] is False
    assert again["serial"] == world.state["stamp_a"]


def test_till_view(world: World) -> None:
    till = world.client.get_pass_till(world.state["stamp_a"], query={"locationId": world.location_id})
    assert till["allowed"] is True
    assert isinstance(till["notices"], list)


def test_issue_more_cards(world: World) -> None:
    world.state["stamp_b"] = _issue(world, world.stamp_program, "stamp-b")["serial"]  # for the sale reversal
    world.state["stamp_c"] = _issue(world, world.stamp_program, "stamp-c")["serial"]  # for idempotency
    gift = _issue(world, world.gift_program, "gift", faceMinor=10000)
    world.state["gift"] = gift["serial"]
    card = world.client.get_pass(gift["serial"])
    assert card["type"] == "giftcard"
    assert card["money"] == {"amountMinor": 10000, "currency": world.currency}
