"""Branch QR and freeze (1.3.0): the branch's public page, the QR images and the print sheet, the QR list, what a key may not do.

Freezing a branch needs a team session and the person's password (a key gets 403 CREDENTIAL_NOT_ALLOWED), and the live
suite has no password, so no branch is frozen here: the refusal, the freeze history and the read side are tested, and
LOCATION_FROZEN / BUSINESS_FROZEN are not reachable (tests/live/TODO.md). copyProgram: a gift card is copied, a loyalty
card refused.
"""
from __future__ import annotations

from typing import Any

import pytest

from rewloy import Rewloy, RewloyError

from .conftest import World


def _branch(world: World) -> Any:
    return next(loc for loc in world.client.list_locations() if loc["id"] == world.location_id)


def test_a_branch_has_a_permanent_qr(world: World) -> None:
    qr = _branch(world)["qr"]
    assert len(qr["code"]) == 6
    assert qr["url"].endswith(f"/s/{qr['code']}")
    assert qr["state"] in ("live", "empty")  # live: there is a card to take here
    assert _branch(world)["frozen"] is None
    world.state["branch_code"] = qr["code"]


def test_the_public_branch_page_needs_no_credentials(world: World) -> None:
    with Rewloy(base_url=world.base_url) as anonymous:
        page = anonymous.public_branch(world.state["branch_code"])
    assert page["code"] == world.state["branch_code"]
    assert page["branch"]["name"] == _branch(world)["name"]
    assert page["branch"]["state"] in ("live", "empty")
    assert page["business"]["name"].endswith("Test")


def test_an_unknown_branch_code_is_a_404(world: World) -> None:
    with pytest.raises(RewloyError) as missing:
        world.client.public_branch("ZZZZZZ")
    assert (missing.value.status, missing.value.code) == (404, "BRANCH_NOT_FOUND")


def test_download_the_qr_images_and_the_print_sheet(world: World) -> None:
    c, loc = world.client, world.location_id
    svg = c.location_qr_svg(loc)
    assert isinstance(svg, bytes) and svg.lstrip().startswith(b"<svg")
    png = c.location_qr_png(loc, query={"size": 512})
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    pdf = c.location_qr_sheet_pdf(loc)
    assert pdf.startswith(b"%PDF-")
    sheet = c.location_qr_sheet_svg(loc)
    assert sheet.lstrip().startswith(b"<svg")
    assert len(sheet) > len(svg)


def test_the_qr_list_and_its_preview(world: World) -> None:
    items = world.client.get_location_qr_items(world.location_id)
    assert items["autoAdd"] is True
    assert isinstance(items["version"], int)
    assert items["items"], "an active loyalty card of the business should be on the QR by rule"
    assert all(item["state"] for item in items["items"])
    preview = world.client.preview_location_qr(world.location_id)
    assert preview["code"] == world.state["branch_code"]
    assert preview["branch"]["name"] == _branch(world)["name"]


def test_a_stale_qr_list_version_is_refused(world: World) -> None:
    with pytest.raises(RewloyError) as stale:
        world.client.put_location_qr_items(world.location_id, body={"version": 999999, "items": []})
    assert (stale.value.status, stale.value.code) == (409, "QR_LIST_CHANGED")
    assert world.client.get_location_qr_items(world.location_id)["autoAdd"] is True  # nothing was written


def test_a_key_cannot_freeze_a_branch_or_read_a_holders_page(world: World) -> None:
    with pytest.raises(RewloyError) as freeze:
        world.client.freeze_location(world.location_id, body={"reason": "renovation", "password": "not-sent-anywhere-real"})
    assert (freeze.value.status, freeze.value.code) == (403, "CREDENTIAL_NOT_ALLOWED")
    with pytest.raises(RewloyError) as holder:
        world.client.holder_branch(world.state["branch_code"])
    assert (holder.value.status, holder.value.code) == (403, "CREDENTIAL_NOT_ALLOWED")


def test_freeze_history_and_unfreezing_an_open_branch(world: World) -> None:
    history = world.client.list_location_freezes(world.location_id)
    assert history["freezes"] == []
    assert history["freeDays"]["left"] == 90
    with pytest.raises(RewloyError) as open_branch:
        world.client.unfreeze_location(world.location_id)
    assert (open_branch.value.status, open_branch.value.code) == (409, "NOT_FROZEN")


def test_copy_a_gift_card_program(world: World) -> None:
    copy = world.client.copy_program(world.gift_program["id"])
    world.programs.append(dict(copy))
    assert copy["id"] != world.gift_program["id"]
    assert copy["type"] == "giftcard"
    assert copy["status"] == "active"


def test_a_loyalty_card_is_not_copied(world: World) -> None:
    with pytest.raises(RewloyError) as refused:
        world.client.copy_program(world.stamp_program["id"])
    assert (refused.value.status, refused.value.code) == (422, "NOT_AN_INSTRUMENT")
