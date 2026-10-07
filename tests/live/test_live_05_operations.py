"""The operations list, reverseSale and reverseAction."""
from __future__ import annotations

from rewloy import RewloyError

from .conftest import World


def test_operations_list_is_newest_first_with_undo_hints(world: World) -> None:
    page = world.client.list_pass_operations(world.state["stamp_a"])
    ops = page.data
    assert len(ops) >= 3  # sale, earn, redeem
    assert page.meta["total"] >= 3
    times = [op["at"] for op in ops]
    assert times == sorted(times, reverse=True)
    assert {op["undoWith"] for op in ops if op["reversible"]} <= {"sale/reverse", "actions/reverse"}
    assert any(op.get("saleKey") == world.state["sale_a_key"] for op in ops)


def test_reverse_sale(world: World) -> None:
    serial = world.state["stamp_b"]
    key = world.key("sale-b")
    world.client.record_sale(serial, idempotency_key=key, body={"locationId": world.location_id, "amountMinor": 3000, "reference": "fis-b"})
    assert world.client.get_pass(serial)["balance"] == 1
    undone = world.client.reverse_sale(serial, body={"saleKey": key, "locationId": world.location_id})
    assert undone["balance"] == 0
    assert undone["duplicate"] is False
    assert undone["card"]["stamps"]["count"] == 0
    again = world.client.reverse_sale(serial, body={"saleKey": key})
    assert again["duplicate"] is True  # a sale is reversed once


def test_reverse_sale_after_the_stamps_were_spent_is_refused(world: World) -> None:
    try:
        world.client.reverse_sale(world.state["stamp_a"], body={"saleKey": world.state["sale_a_key"]})
    except RewloyError as err:
        assert (err.status, err.code) == (409, "SALE_ALREADY_SPENT")
    else:
        raise AssertionError("expected 409 SALE_ALREADY_SPENT")


def test_reverse_action(world: World) -> None:
    serial = world.state["gift"]
    undone = world.client.reverse_action(serial, body={"actionKey": world.state["spend_key"], "locationId": world.location_id})
    assert undone["undone"] == "spend"
    assert undone["restored"] == 2500
    assert undone["balance"] == 10000
    again = world.client.reverse_action(serial, body={"actionKey": world.state["spend_key"]})
    assert again["duplicate"] is True


def test_operations_show_the_reversals(world: World) -> None:
    ops = world.client.list_pass_operations(world.state["gift"]).data
    assert any(op["reverses"] for op in ops), "no reversal entry in the card's operations"
