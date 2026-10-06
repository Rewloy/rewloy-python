"""The operations and fields Rewloy API 1.2.0 added."""

from __future__ import annotations

from typing import Callable

import pytest

from rewloy import OPERATIONS, RewloyError

from .helpers import LOCATION, SERIAL, Ctx, Stub, api_error, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]
WEBHOOK = "0192f7c1-0000-7000-8000-0000000000aa"
REFUSALS = {"b-closed": (410, "BATCH_CLOSED"), "b-expired": (410, "BATCH_EXPIRED"), "b-full": (410, "BATCH_FULL"), "b-archived": (409, "PROGRAM_ARCHIVED")}


def webhook_row(paused_until: str | None, resumable_until: str | None) -> dict[str, object]:
    """A webhook object as 1.2.0 answers: pausedUntil and resumableUntil are always present."""
    return {
        "id": WEBHOOK,
        "url": "https://ornek.com/rewloy/webhook",
        "events": ["pass.activity"],
        "status": "active",
        "failures": 0,
        "disabledReason": None,
        "createdAt": "2026-10-06T09:00:00.000Z",
        "week": {"delivered": 3, "failed": 0, "pending": 1},
        "lastDelivered": "2026-10-06T09:30:00.000Z",
        "createdByKey": None,
        "pausedUntil": paused_until,
        "resumableUntil": resumable_until,
    }


def handle(c: Ctx) -> None:
    url = c.req.url
    if url.startswith(f"/v1/passes/{SERIAL}/operations"):
        c.json(200, {
            "data": [{"id": "o1", "kind": "earn", "delta": 1, "unit": "stamp", "saleKey": "kasa3-z0187-fis0042", "undoWith": "sale/reverse", "reversible": True, "byCaller": True}],
            "meta": {"page": 1, "pageSize": 50, "total": 1},
        })
    elif url.startswith("/v1/batches/b-") and url.endswith("/send"):
        status, code = REFUSALS[url.split("/")[3]]
        c.json(status, api_error(code, status, code))
    elif url == "/v1/developers/webhooks" and c.req.method == "GET":
        c.json(200, {"data": [webhook_row("2026-10-06T10:01:00.000Z", None), webhook_row(None, "2026-10-07T09:45:00.000Z")]})
    elif url == f"/v1/developers/webhooks/{WEBHOOK}" and c.req.method == "PATCH":
        c.json(200, {"data": webhook_row(None, None)})
    elif url.startswith("/v1/batches"):
        c.json(200, {"data": [{"id": "b1", "status": "open", "state": "archived"}], "meta": {"page": 1, "pageSize": 50, "total": 1}})
    elif url == f"/v1/developers/webhooks/{WEBHOOK}/rotate-secret":
        c.json(200, {"data": {"secret": "whsec_new", "previousValidUntil": "2026-10-07T10:00:00.000Z"}})
    elif url == f"/v1/developers/webhooks/{WEBHOOK}" and c.req.method == "DELETE":
        c.raw(204)
    elif url == "/v1/developers/keys":
        c.json(201, {"data": {"token": "rwk_x_y", "baseUrl": "https://app.rewloy.com"}})
    elif url == "/v1/test/environment/reset":
        c.json(200, {"data": {"keysRevoked": True}})
    elif url == "/v1/programs/p1/batches":
        c.json(409, api_error("PROGRAM_ARCHIVED", 409, "Program arşivde"))
    elif url.endswith("/sale"):
        c.json(200, {"data": {"type": "stamp", "applied": "stamps", "credited": 1, "balance": 3, "duplicate": True, "reversed": True, "rewardReady": False, "rewardsReady": 0, "card": None}})
    else:
        c.json(200, {"data": {"ok": True}})


def test_knows_the_new_operations() -> None:
    for op in ("listPassOperations", "listAllBatches", "rotateWebhookSecret", "deleteWebhook"):
        assert op in OPERATIONS, op
    assert OPERATIONS["listPassOperations"].paged
    assert OPERATIONS["listAllBatches"].paged
    assert OPERATIONS["listPassOperations"].method_name == "list_pass_operations"


def test_lists_a_cards_operations_and_pages_them(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    page = c.list_pass_operations(SERIAL, query={"limit": 10})
    assert page.data[0]["undoWith"] == "sale/reverse"
    assert s.requests[-1].url.endswith("/operations?limit=10")
    ids = [op["id"] for op in c.paginate("listPassOperations", path={"serial": SERIAL})]
    assert ids == ["o1"]


def test_lists_every_batch_with_the_archived_state(stub: StubFactory) -> None:
    s = stub(handle)
    page = make_client(s).list_all_batches(query={"status": "archived"})
    assert page.data[0]["state"] == "archived"
    assert s.requests[-1].url == "/v1/batches?status=archived"


def test_rotates_and_deletes_a_webhook(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    assert c.rotate_webhook_secret(WEBHOOK)["secret"] == "whsec_new"
    assert s.requests[-1].method == "POST"
    c.delete_webhook(WEBHOOK)
    assert s.requests[-1].method == "DELETE"


def test_creates_a_pos_key_and_resets_the_test_environment_with_revoke_keys(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    c.create_api_key(body={"kind": "pos", "locationId": LOCATION, "register": "Kasa 1", "password": "x"})
    assert s.requests[-1].json() == {"kind": "pos", "locationId": LOCATION, "register": "Kasa 1", "password": "x"}
    c.reset_test_environment(body={"revokeKeys": True})
    assert s.requests[-1].json() == {"revokeKeys": True}


def test_reads_card_and_reversed_on_a_replayed_sale_and_card_may_be_none(stub: StubFactory) -> None:
    c = make_client(stub(handle))
    sale = c.record_sale(SERIAL, body={"locationId": LOCATION, "amountMinor": 100}, idempotency_key="kasa3-z0187-fis0042")
    assert sale["reversed"] is True
    card = sale["card"]
    assert card is None


def test_surfaces_program_archived(stub: StubFactory) -> None:
    c = make_client(stub(handle))
    with pytest.raises(RewloyError) as info:
        c.create_batch("p1", body={})
    assert info.value.status == 409
    assert info.value.code == "PROGRAM_ARCHIVED"


def test_reads_the_webhook_state_fields_a_date_time_or_none(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    rows = c.list_webhooks()
    paused: str | None = rows[0]["pausedUntil"]
    resumable: str | None = rows[1]["resumableUntil"]
    assert paused == "2026-10-06T10:01:00.000Z"
    assert rows[0]["resumableUntil"] is None
    assert rows[1]["pausedUntil"] is None
    assert resumable == "2026-10-07T09:45:00.000Z"
    turned_on = c.set_webhook_status(WEBHOOK, body={"active": True})
    assert (turned_on["pausedUntil"], turned_on["resumableUntil"]) == (None, None)
    assert s.requests[-1].method == "PATCH"


@pytest.mark.parametrize("batch", sorted(REFUSALS))
def test_surfaces_what_send_batch_link_refuses(stub: StubFactory, batch: str) -> None:
    c = make_client(stub(handle))
    status, code = REFUSALS[batch]
    with pytest.raises(RewloyError) as info:
        c.send_batch_link(batch, body={"email": "ali@ornek.com"})
    assert info.value.status == status
    assert info.value.code == code
