"""recordSale and passAction: earn, redeem, spend."""
from __future__ import annotations

import pytest

from .conftest import World


def test_record_sale_without_receipt_lines(world: World) -> None:
    serial = world.state["stamp_a"]
    key = world.key("sale-a")
    sale = world.client.record_sale(
        serial, idempotency_key=key,
        body={"locationId": world.location_id, "amountMinor": 4550, "currency": world.currency, "reference": f"fis-{world.run}"},
    )
    assert sale["applied"] == "stamps"
    assert sale["credited"] == 1
    assert sale["balance"] == 1
    assert sale["duplicate"] is False
    assert sale["card"]["stamps"]["count"] == 1  # the card after the write comes with the answer
    world.state["sale_a_key"] = key


@pytest.mark.skip(reason="TODO 0.3.0: recordSale receipt lines (line items) are not in API 1.2.0 / library 0.2.4; see tests/live/TODO.md")
def test_record_sale_with_receipt_lines(world: World) -> None:
    raise AssertionError("add when the regenerated library has the line-item schema")


def test_sale_on_gift_card_writes_nothing(world: World) -> None:
    sale = world.client.record_sale(
        world.state["gift"], idempotency_key=world.key("sale-gift"),
        body={"locationId": world.location_id, "amountMinor": 1000},
    )
    assert sale["applied"] == "none"
    assert sale["reason"] == "type_does_not_earn"
    assert sale["balance"] == 10000


def test_pass_action_earn_stamps_then_redeem(world: World) -> None:
    serial = world.state["stamp_a"]
    earned = world.client.pass_action(
        serial, idempotency_key=world.key("earn-a"),
        body={"action": "earn-stamps", "locationId": world.location_id, "count": 3},
    )
    assert earned["balance"] == 4
    assert earned["card"]["rewardReady"] is True
    card = world.client.get_pass(serial)
    redeem = next(a for a in card["actions"] if a["action"] == "redeem-stamps")
    assert redeem["ready"] is True
    redeemed = world.client.pass_action(
        serial, idempotency_key=world.key("redeem-a"),
        body={"action": "redeem-stamps", "locationId": world.location_id},
    )
    assert redeemed["balance"] == 0
    assert redeemed["card"]["stamps"]["count"] == 0


def test_gift_card_spend(world: World) -> None:
    key = world.key("spend-gift")
    spent = world.client.pass_action(
        world.state["gift"], idempotency_key=key,
        body={"action": "spend", "locationId": world.location_id, "amountMinor": 2500},
    )
    assert spent["balance"] == 7500
    assert spent["card"]["money"]["amountMinor"] == 7500
    world.state["spend_key"] = key
