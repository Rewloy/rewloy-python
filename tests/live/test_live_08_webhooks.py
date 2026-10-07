"""Webhooks: create, list, rotate the secret, delete.

A webhook to an https address that does not resolve publicly is accepted in a TEST business (it says so in the
docs: test deliveries are tried and fail harmlessly); a live business would refuse it. Either outcome is
documented, so this checks that the answer is one of the two and, when created, runs the whole life cycle.
"""
from __future__ import annotations

import pytest

from rewloy import RewloyError

from .conftest import World

URL = "https://hooks.live-test.invalid/rewloy"


def test_event_catalogue(world: World) -> None:
    catalogue = world.client.webhook_events()
    names = {e["event"] for e in catalogue["events"]}
    assert {"pass.issued", "pass.activity", "pass.voided"} <= names
    assert {"pass.extended", "location.frozen", "location.unfrozen", "business.paused", "business.resumed"} <= names  # 1.3.0


def test_unresolvable_https_url_is_created_or_refused_as_documented(world: World) -> None:
    try:
        created = world.client.create_webhook(body={"url": URL, "events": ["pass.issued", "pass.activity"]})
    except RewloyError as err:
        assert 400 <= err.status < 500 and err.code, "a refusal must be a 4xx with a code"
        pytest.skip(f"this server refuses the address ({err.status} {err.code}); the life cycle below needs a created webhook")
    hook = created["webhook"]
    world.webhook_ids.append(hook["id"])
    world.state["webhook"] = hook
    world.state["webhook_secret"] = created["secret"]
    assert created["secret"].startswith("whsec_")
    assert hook["url"] == URL
    assert hook["status"] == "active"
    assert sorted(hook["events"]) == ["pass.activity", "pass.issued"]


def test_list_and_get(world: World) -> None:
    if "webhook" not in world.state:
        pytest.skip("no webhook was created")
    hook = world.state["webhook"]
    assert hook["id"] in [w["id"] for w in world.client.list_webhooks()]
    assert world.client.get_webhook(hook["id"])["url"] == URL


def test_rotate_secret(world: World) -> None:
    if "webhook" not in world.state:
        pytest.skip("no webhook was created")
    rotated = world.client.rotate_webhook_secret(world.state["webhook"]["id"])
    assert rotated["secret"].startswith("whsec_")
    assert rotated["secret"] != world.state["webhook_secret"]
    assert rotated["previousValidUntil"]  # the old secret keeps working for a while


def test_subscribe_to_the_1_3_0_events(world: World) -> None:
    if "webhook" not in world.state:
        pytest.skip("no webhook was created")
    events = ["pass.extended", "location.frozen", "location.unfrozen", "business.paused", "business.resumed"]
    created = world.client.create_webhook(body={"url": URL + "/branches", "events": events})
    world.webhook_ids.append(created["webhook"]["id"])
    assert sorted(created["webhook"]["events"]) == sorted(events)
    assert world.client.delete_webhook(created["webhook"]["id"]) is None
    world.webhook_ids.remove(created["webhook"]["id"])


def test_delete(world: World) -> None:
    if "webhook" not in world.state:
        pytest.skip("no webhook was created")
    hook_id = world.state["webhook"]["id"]
    assert world.client.delete_webhook(hook_id) is None
    world.webhook_ids.remove(hook_id)
    assert hook_id not in [w["id"] for w in world.client.list_webhooks()]
    with pytest.raises(RewloyError) as gone:
        world.client.delete_webhook(hook_id)
    assert (gone.value.status, gone.value.code) == (404, "WEBHOOK_NOT_FOUND")
