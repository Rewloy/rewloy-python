"""Webhooks: create, list, rotate the secret, delete.

The address rule is the same in a test and a live business (docs/API.md, Webhooks): a public https address that
resolves; anything else is 422 BAD_WEBHOOK_URL. Only a non-live installation (development, staging) is looser.
So the tests use a resolvable host (example.com, a path unique to the run) and run the whole life cycle on every
server; deliveries to it are tried and fail harmlessly. A refusal is a failure, not a skip.
"""
from __future__ import annotations

import pytest

from rewloy import RewloyError

from .conftest import World



def test_event_catalogue(world: World) -> None:
    catalogue = world.client.webhook_events()
    names = {e["event"] for e in catalogue["events"]}
    assert {"pass.issued", "pass.activity", "pass.voided"} <= names
    assert {"pass.extended", "location.frozen", "location.unfrozen", "business.paused", "business.resumed"} <= names  # 1.3.0


def _url(world: World) -> str:
    return f"https://example.com/rewloy-live-tests/{world.run}"


def test_create_webhook_to_a_resolvable_https_url(world: World) -> None:
    URL = _url(world)
    created = world.client.create_webhook(body={"url": URL, "events": ["pass.issued", "pass.activity"]})
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
    assert world.client.get_webhook(hook["id"])["url"] == _url(world)


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
    created = world.client.create_webhook(body={"url": _url(world) + "/branches", "events": events})
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
