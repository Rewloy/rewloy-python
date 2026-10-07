"""Idempotency-Key: the same key replays the same answer, card included."""
from __future__ import annotations

import pytest

from rewloy import RewloyError

from .conftest import World


def test_same_key_replays_the_answer(world: World) -> None:
    serial = world.state["stamp_c"]
    key = world.key("idem-sale")
    body = {"locationId": world.location_id, "amountMinor": 2000, "reference": "fis-idem"}
    first = world.client.request("recordSale", path={"serial": serial}, body=body, idempotency_key=key)
    second = world.client.request("recordSale", path={"serial": serial}, body=body, idempotency_key=key)
    assert first.status == second.status
    # a sale answers a repeat itself (duplicate: true, the card as it is now); the replay header is for issue_pass and campaigns
    assert first.replayed is False
    assert first.data["duplicate"] is False
    assert second.data["duplicate"] is True
    assert second.data["credited"] == first.data["credited"]
    assert second.data["balance"] == first.data["balance"] == 1  # written once
    assert "card" in second.data and second.data["card"]["serial"] == serial
    assert world.client.get_pass(serial)["balance"] == 1


def test_issue_pass_replays_with_the_header(world: World) -> None:
    key = world.key("idem-issue")
    body = {"programId": world.stamp_program["id"], "email": world.email("idem-issue"), "kvkkConsent": True}
    first = world.client.request("issuePass", body=body, idempotency_key=key)
    second = world.client.request("issuePass", body=body, idempotency_key=key)
    assert first.replayed is False and first.data["created"] is True
    assert second.replayed is True  # Idempotent-Replayed: true
    assert second.data["serial"] == first.data["serial"]
    assert second.data["cardUrl"] == first.data["cardUrl"]
    cards = [c for c in world.client.list_customers(query={"q": body["email"]}).data[0]["cards"]]
    assert len(cards) == 1  # one card, not two


def test_same_key_with_another_body_is_refused(world: World) -> None:
    with pytest.raises(RewloyError) as reused:
        world.client.record_sale(
            world.state["stamp_c"], idempotency_key=world.key("idem-sale"),
            body={"locationId": world.location_id, "amountMinor": 9999, "reference": "fis-other"},
        )
    assert (reused.value.status, reused.value.code) == (422, "IDEMPOTENCY_KEY_REUSED")


def test_a_key_the_library_refuses_never_reaches_the_server(world: World) -> None:
    with pytest.raises(ValueError):
        world.client.record_sale(world.state["stamp_c"], idempotency_key="fiş-0001", body={"amountMinor": 1})
    with pytest.raises(TypeError):
        world.client.record_sale(world.state["stamp_c"], body={"amountMinor": 1})
