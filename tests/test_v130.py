"""The operations and fields Rewloy API 1.3.0 added (library 0.3.0)."""

from __future__ import annotations

from typing import Any, Callable, List

import pytest

from rewloy import API_VERSION, ERROR_TITLES, OPERATIONS, RewloyError

from .helpers import LOCATION, SERIAL, Ctx, Stub, api_error, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]
PROGRAM = "0192f7c1-0000-7000-8000-0000000000b1"
GROUP = "0192f7c1-0000-7000-8000-0000000000b2"
LINES: List[Any] = [
    {"lineId": "a", "name": "Latte", "unitPriceMinor": 9000, "quantity": 2, "category": "İçecek > Sıcak"},
    {"lineId": "b", "name": "Kek", "unitPriceMinor": 5000, "category": ["Tatlı"]},
]
EARN = {
    "source": "rules", "revision": 1, "unit": "stamps",
    "lines": [{"lineId": "a", "status": "earned", "groups": [GROUP], "rules": ["r1"], "earned": 2}, {"lineId": "b", "status": "no_rule", "earned": 0}],
    "rules": [{"ruleId": "r1", "kind": "stamp.perUnit", "units": 2, "lines": ["a"], "text": "1 stamp for each item"}],
    "total": {"beforeRounding": "2", "rounded": 2, "receiptCap": None, "promotion": None, "caps": [], "credited": 2},
}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def handle(c: Ctx) -> None:
    url = c.req.url.split("?")[0]
    method = c.req.method
    if url == "/v1/earn-groups" and method == "POST":
        c.json(201, {"data": {"id": GROUP, "name": "Sıcak içecek", "members": [], "lines30d": 0, "usedBy": [], "warnings": []}})
    elif url == f"/v1/programs/{PROGRAM}/earn-rules" and method == "PUT":
        c.json(200, {"data": {"programId": PROGRAM, "active": True, "revision": 2, "rules": [], "warnings": [{"kind": "no_daily_cap", "ruleIds": ["r1"]}]}})
    elif url == f"/v1/programs/{PROGRAM}/earn-rules/preview":
        c.json(200, {"data": {"credited": 2, "unit": "stamps", "earn": EARN, "preview": True}})
    elif url == f"/v1/passes/{SERIAL}/sale/preview":
        c.json(200, {"data": {"type": "stamp", "applied": "stamps", "credited": 2, "balance": 2, "duplicate": False, "earn": EARN, "preview": True}})
    elif url == f"/v1/passes/{SERIAL}/sale":
        c.json(200, {"data": {"type": "stamp", "applied": "stamps", "credited": 2, "balance": 2, "duplicate": False, "earn": EARN}})
    elif url == f"/v1/passes/{SERIAL}/sale/reverse":
        c.json(200, {"data": {"type": "stamp", "applied": "stamps", "reversed": 1, "balance": 1, "earn": EARN, "linesLeft": [{"lineId": "a", "quantity": 1, "amountMinor": 9000}]}})
    elif url == "/v1/public/branches/Z5KDH2":
        c.json(200, {"data": {"code": "Z5KDH2", "branch": {"name": "Test şubesi", "state": "live"}}})
    elif url == f"/v1/locations/{LOCATION}/qr.png":
        c.raw(200, PNG, {"Content-Type": "image/png"})
    elif url == f"/v1/locations/{LOCATION}/qr.svg":
        c.raw(200, b"<svg/>", {"Content-Type": "image/svg+xml"})
    elif url == f"/v1/locations/{LOCATION}/qr/sheet.pdf":
        c.raw(200, b"%PDF-1.7\n", {"Content-Type": "application/pdf"})
    elif url == f"/v1/locations/{LOCATION}/freeze" and method == "POST":
        c.json(403, api_error("CREDENTIAL_NOT_ALLOWED", 403, "Bu kimlik türü bu uç noktayı kullanamaz"))
    elif url == f"/v1/locations/{LOCATION}/unfreeze":
        c.json(409, api_error("NOT_FROZEN", 409, "Şube donuk değil"))
    elif url == f"/v1/programs/{PROGRAM}/copy":
        c.json(422, api_error("NOT_AN_INSTRUMENT", 422, "Yalnız hediye kartı, kupon ve indirim kartının kopyası oluşturulur"))
    elif url == "/v1/holder/branches/Z5KDH2/join":
        c.json(201, {"data": {"joined": []}})
    else:
        c.json(200, {"data": {"ok": True}})


def test_knows_the_1_3_0_operations() -> None:
    assert API_VERSION == "1.3.0"
    assert len(OPERATIONS) == 298
    for op in (
        "createEarnGroup", "listEarnGroups", "getEarnGroup", "updateEarnGroup", "deleteEarnGroup", "listEarnSources", "listSeenLines",
        "ignoreSeenLine", "unignoreSeenLine", "listEarnTemplates", "getEarnRules", "putEarnRules", "deleteEarnRules", "createEarnRule",
        "updateEarnRule", "deleteEarnRule", "listEarnRuleRevisions", "previewEarn", "previewSale", "copyProgram", "extendProgramCards",
        "updateBatch", "publicBranch", "holderBranch", "joinHolderBranch", "previewLocationQr", "getLocationQrItems", "putLocationQrItems",
        "addQrItems", "locationQrSvg", "locationQrPng", "locationQrSheetPdf", "locationQrSheetSvg", "freezeLocation", "updateLocationFreeze",
        "cancelLocationFreeze", "unfreezeLocation", "listLocationFreezes",
    ):
        assert op in OPERATIONS, op
    assert OPERATIONS["locationQrPng"].response == "blob"
    assert OPERATIONS["freezeLocation"].auth == ("staff",)
    assert OPERATIONS["reverseSale"].idempotency == "optional"


def test_knows_the_1_3_0_errors() -> None:
    for code in ("LOCATION_FROZEN", "BUSINESS_FROZEN", "NOT_AN_INSTRUMENT", "TOO_MANY_LINES", "LINES_TOTAL_MISMATCH", "LINE_NOT_FOUND",
                 "LINE_ALREADY_REFUNDED", "REVISION_CONFLICT", "ALREADY_FROZEN", "NOT_FROZEN", "FREEZE_LIMIT", "BRANCH_NOT_FOUND"):
        assert code in ERROR_TITLES, code


def test_creates_a_group_saves_rules_and_previews_the_earn(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    group = c.create_earn_group(body={"name": "Sıcak içecek", "members": [{"effect": "include", "match": "category", "value": "İçecek > Sıcak"}]})
    assert group["id"] == GROUP
    saved = c.put_earn_rules(PROGRAM, body={"revision": 1, "rules": [{"kind": "stamp.perUnit", "groupId": GROUP, "stamps": 1}]})
    assert saved["revision"] == 2
    assert saved["warnings"][0]["kind"] == "no_daily_cap"
    assert s.requests[-1].method == "PUT"
    assert s.requests[-1].json()["rules"][0]["kind"] == "stamp.perUnit"
    preview = c.preview_earn(PROGRAM, body={"amountMinor": 23000, "lines": LINES})
    assert preview["credited"] == 2
    assert preview["earn"]["lines"][1]["status"] == "no_rule"
    assert s.requests[-1].url == f"/v1/programs/{PROGRAM}/earn-rules/preview"


def test_receipt_lines_go_through_record_sale_and_preview_sale_and_the_earn_explanation_comes_back(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    body: Any = {"locationId": LOCATION, "amountMinor": 23000, "lines": LINES, "receiptDiscountMinor": 0}
    sale = c.record_sale(SERIAL, body=body, idempotency_key="kasa3-z0187-fis0043")
    assert s.requests[-1].json()["lines"][0]["lineId"] == "a"
    assert s.requests[-1].json()["lines"][1]["category"] == ["Tatlı"]
    earn = sale["earn"]
    assert earn["total"]["credited"] == 2
    assert earn["rules"][0]["ruleId"] == "r1"
    preview = c.preview_sale(SERIAL, body=body)
    assert s.requests[-1].method == "POST"
    assert s.requests[-1].url == f"/v1/passes/{SERIAL}/sale/preview"
    assert preview["preview"] is True


def test_refunds_some_lines_of_a_sale(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    answer = c.reverse_sale(SERIAL, body={"saleKey": "kasa3-z0187-fis0043", "lines": [{"lineId": "a", "quantity": 1}]}, idempotency_key="kasa3-z0187-iade1")
    assert answer["linesLeft"][0] == {"lineId": "a", "quantity": 1, "amountMinor": 9000}
    assert s.requests[-1].json()["lines"] == [{"lineId": "a", "quantity": 1}]
    assert s.requests[-1].headers["idempotency-key"] == "kasa3-z0187-iade1"


def test_reads_a_public_branch_page_and_downloads_the_branch_qr_as_bytes(stub: StubFactory) -> None:
    s = stub(handle)
    c = make_client(s)
    page = c.public_branch("Z5KDH2")
    assert page["code"] == "Z5KDH2"
    png = c.location_qr_png(LOCATION, query={"size": 1024})
    assert isinstance(png, bytes) and png.startswith(b"\x89PNG")
    assert s.requests[-1].url == f"/v1/locations/{LOCATION}/qr.png?size=1024"
    assert c.location_qr_svg(LOCATION).startswith(b"<svg")
    assert c.location_qr_sheet_pdf(LOCATION).startswith(b"%PDF")


def test_surfaces_what_a_key_may_not_do_and_what_a_loyalty_card_cannot(stub: StubFactory) -> None:
    c = make_client(stub(handle))
    with pytest.raises(RewloyError) as denied:
        c.freeze_location(LOCATION, body={"reason": "renovation", "password": "x"})
    assert (denied.value.status, denied.value.code) == (403, "CREDENTIAL_NOT_ALLOWED")
    with pytest.raises(RewloyError) as open_branch:
        c.unfreeze_location(LOCATION)
    assert open_branch.value.code == "NOT_FROZEN"
    with pytest.raises(RewloyError) as loyalty:
        c.copy_program(PROGRAM)
    assert (loyalty.value.status, loyalty.value.code) == (422, "NOT_AN_INSTRUMENT")
