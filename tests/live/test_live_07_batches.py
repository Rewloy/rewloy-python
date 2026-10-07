"""Batches (codes): create, list, listAllBatches, send-link refusals."""
from __future__ import annotations

from typing import Any

import pytest

from rewloy import RewloyError

from .conftest import World


def _refused(world: World, batch_id: str, *codes: str) -> RewloyError:
    with pytest.raises(RewloyError) as caught:
        world.client.send_batch_link(batch_id, body={"email": world.email("link")})
    assert caught.value.code in codes, f"{caught.value.code} not in {codes}"
    assert caught.value.status in (409, 410)
    return caught.value


def test_create_and_list_batches(world: World) -> None:
    batch = world.client.create_batch(world.gift_program["id"], body={"name": f"Live codes {world.run}", "valueMinor": 5000, "capacity": 3})
    world.batch_ids.append(batch["id"])
    world.state["batch"] = batch
    assert batch["status"] == "open"
    assert batch["valueMinor"] == 5000
    assert batch["code"] and batch["claimUrl"].endswith(batch["code"])
    listed = world.client.list_batches(world.gift_program["id"])
    assert [b["id"] for b in listed] == [batch["id"]]


def test_list_all_batches_filters_and_pages(world: World) -> None:
    batch = world.state["batch"]
    page = world.client.list_all_batches(query={"programId": world.gift_program["id"], "status": "open"})
    assert [b["id"] for b in page.data] == [batch["id"]]
    assert page.data[0]["state"] == "open"
    assert page.meta["total"] == 1
    walked = list(world.client.paginate("listAllBatches", query={"programId": world.gift_program["id"], "limit": 1}))
    assert batch["id"] in [b["id"] for b in walked]
    closed = world.client.list_all_batches(query={"programId": world.gift_program["id"], "status": "closed"})
    assert batch["id"] not in [b["id"] for b in closed.data]


def test_send_link_to_an_open_batch_is_queued(world: World) -> None:
    sent = world.client.send_batch_link(world.state["batch"]["id"], body={"email": world.email("link")})
    assert sent["result"] == "queued"


def test_send_link_validation_and_unknown_batch(world: World) -> None:
    with pytest.raises(RewloyError) as bad:
        world.client.send_batch_link(world.state["batch"]["id"], body={"email": "not-an-email"})
    assert (bad.value.status, bad.value.code) == (400, "VALIDATION")
    with pytest.raises(RewloyError) as missing:
        world.client.send_batch_link("01a11749-0000-7000-8000-000000000000", body={"email": world.email("link")})
    assert (missing.value.status, missing.value.code) == (404, "BATCH_NOT_FOUND")


def test_send_link_refused_when_closed(world: World) -> None:
    batch = world.state["batch"]
    closed: Any = world.client.close_batch(batch["id"])
    assert closed["status"] == "closed"
    err = _refused(world, batch["id"], "BATCH_CLOSED")
    assert err.status == 410
    page = world.client.list_all_batches(query={"programId": world.gift_program["id"], "status": "closed"})
    assert batch["id"] in [b["id"] for b in page.data]


def test_send_link_refused_when_every_card_is_taken(world: World) -> None:
    full = world.client.create_batch(world.gift_program["id"], body={"name": f"Live one card {world.run}", "valueMinor": 1000, "capacity": 1})
    world.batch_ids.append(full["id"])
    claimed = world.client.claim_code(full["code"], body={"email": world.email("claim"), "kvkkConsent": True})
    assert claimed["serial"]
    err = _refused(world, full["id"], "BATCH_FULL")
    assert err.status == 410
    state = world.client.list_all_batches(query={"programId": world.gift_program["id"], "status": "full"})
    assert full["id"] in [b["id"] for b in state.data]


def test_archived_program_takes_no_new_code_and_no_link(world: World) -> None:
    program = world.new_program({"type": "giftcard", "businessName": f"Live {world.run}", "programName": f"Live archived {world.run}"})
    batch = world.client.create_batch(program["id"], body={"name": "before archive", "valueMinor": 1000})
    world.batch_ids.append(batch["id"])
    world.client.archive_program(program["id"])
    with pytest.raises(RewloyError) as refused:
        world.client.create_batch(program["id"], body={"name": "after archive", "valueMinor": 1000})
    assert (refused.value.status, refused.value.code) == (409, "PROGRAM_ARCHIVED")
    # archiving closes the program's codes; either refusal is documented, and no e-mail goes
    _refused(world, batch["id"], "BATCH_CLOSED", "PROGRAM_ARCHIVED")
