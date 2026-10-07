"""Earn rules (1.3.0): product groups, rules, previewEarn, previewSale, receipt lines with the earn explanation, line refunds.

One stamp program of its own ("1 stamp for each hot drink") so that the earlier areas' balances do not move. The test
business is a Rewloy-owned throw-away: the groups and rules are removed again in the last test (and by the cleanup).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from rewloy import RewloyError

from .conftest import World

LINES: List[Dict[str, Any]] = [
    {"lineId": "a", "name": "Latte", "unitPriceMinor": 9000, "quantity": 2, "category": "İçecek > Sıcak"},
    {"lineId": "b", "name": "Kek", "unitPriceMinor": 5000, "category": "Tatlı"},
]
TOTAL = 23000  # 2 x 90.00 + 50.00


def _program(world: World) -> Dict[str, Any]:
    return world.state["earn_program"]  # type: ignore[no-any-return]


def test_create_a_product_group_and_a_program(world: World) -> None:
    group = world.client.create_earn_group(body={
        "name": f"Sicak icecek {world.run}",
        "members": [{"effect": "include", "match": "category", "value": "İçecek > Sıcak"}],
    })
    world.earn_group_ids.append(group["id"])
    assert group["name"] == f"Sicak icecek {world.run}"
    assert group["members"][0]["match"] == "category"
    assert group["usedBy"] == []
    world.state["earn_group"] = group
    fetched = world.client.get_earn_group(group["id"])
    assert fetched["id"] == group["id"]
    assert group["id"] in [g["id"] for g in world.client.list_earn_groups()]
    program = world.new_program({
        "type": "stamp", "businessName": f"Live {world.run}", "programName": f"Live earn {world.run}", "maxStamps": 10, "rewardName": "Free coffee",
    })
    world.state["earn_program"] = program


def test_templates_are_listed(world: World) -> None:
    templates = world.client.list_earn_templates()
    assert {t["type"] for t in templates} >= {"stamp", "points"}
    assert all(t["rules"] for t in templates)


def test_a_program_has_no_rules_until_they_are_saved(world: World) -> None:
    rules = world.client.get_earn_rules(_program(world)["id"])
    assert rules["active"] is False
    assert rules["revision"] == 0
    assert rules["rules"] == []


def test_save_the_rules_and_a_stale_revision_conflicts(world: World) -> None:
    program = _program(world)
    group = world.state["earn_group"]
    saved = world.client.put_earn_rules(program["id"], body={
        "revision": 0,
        "rules": [{"kind": "stamp.perUnit", "groupId": group["id"], "stamps": 1}],
        "settings": {"dailyCap": 20},
    })
    assert saved["active"] is True
    assert saved["revision"] == 1
    assert saved["rules"][0]["kind"] == "stamp.perUnit"
    assert saved["rules"][0]["groupId"] == group["id"]
    assert saved["settings"]["dailyCap"] == 20
    assert saved["text"]  # the rules in one sentence
    with pytest.raises(RewloyError) as stale:
        world.client.put_earn_rules(program["id"], body={"revision": 0, "rules": []})
    assert (stale.value.status, stale.value.code) == (409, "REVISION_CONFLICT")
    assert stale.value.details == {"revision": 1}
    again = world.client.get_earn_rules(program["id"])
    assert again["revision"] == 1
    revisions = world.client.list_earn_rule_revisions(program["id"])
    assert revisions.meta["total"] >= 1


def test_a_group_in_use_cannot_be_deleted(world: World) -> None:
    with pytest.raises(RewloyError) as used:
        world.client.delete_earn_group(world.state["earn_group"]["id"])
    assert (used.value.status, used.value.code) == (409, "GROUP_IN_USE")


def test_preview_earn_without_a_card(world: World) -> None:
    preview = world.client.preview_earn(_program(world)["id"], body={"amountMinor": TOTAL, "currency": world.currency, "lines": LINES})
    assert preview["credited"] == 2
    assert preview["unit"] == "stamps"
    earn = preview["earn"]
    assert earn["source"] == "rules"
    assert earn["revision"] == 1
    by_line = {line["lineId"]: line for line in earn["lines"]}
    assert (by_line["a"]["status"], by_line["a"]["earned"]) == ("earned", 2)
    assert (by_line["b"]["status"], by_line["b"]["earned"]) == ("no_rule", 0)
    assert earn["total"]["credited"] == 2


def test_preview_earn_with_an_unsaved_draft_rule_set(world: World) -> None:
    draft = {"rules": [{"kind": "stamp.perReceipt", "stamps": 3}]}
    preview = world.client.preview_earn(_program(world)["id"], body={"amountMinor": TOTAL, "lines": LINES, "ruleSet": draft})
    assert preview["credited"] == 3  # the draft, not the saved rule
    assert world.client.get_earn_rules(_program(world)["id"])["revision"] == 1  # nothing was saved


def test_too_many_lines_are_refused(world: World) -> None:
    lines: List[Any] = [{"name": "x", "unitPriceMinor": 1}] * 501
    with pytest.raises(RewloyError) as many:
        world.client.preview_earn(_program(world)["id"], body={"amountMinor": 501, "lines": lines})
    assert (many.value.status, many.value.code) == (422, "TOO_MANY_LINES")
    assert many.value.details == {"max": 500, "lines": 501}


def test_issue_a_card(world: World) -> None:
    issued = world.client.issue_pass(body={"programId": _program(world)["id"], "email": world.email("earn"), "kvkkConsent": True})
    world.state["earn_serial"] = issued["serial"]
    assert world.client.get_pass(issued["serial"])["balance"] == 0


def test_preview_sale_writes_nothing(world: World) -> None:
    serial = world.state["earn_serial"]
    preview = world.client.preview_sale(serial, body={"locationId": world.location_id, "amountMinor": TOTAL, "lines": LINES})
    assert preview["preview"] is True
    assert preview["credited"] == 2
    assert preview["earn"]["lines"][0]["lineId"] == "a"
    assert world.client.get_pass(serial)["balance"] == 0
    assert world.client.list_pass_operations(serial).meta["total"] == 0


def test_record_sale_with_receipt_lines_explains_the_earn(world: World) -> None:
    serial = world.state["earn_serial"]
    key = world.key("earn-sale")
    sale = world.client.record_sale(
        serial, idempotency_key=key,
        body={"locationId": world.location_id, "amountMinor": TOTAL, "currency": world.currency, "reference": f"fis-earn-{world.run}", "lines": LINES},
    )
    assert sale["applied"] == "stamps"
    assert sale["credited"] == 2
    assert sale["balance"] == 2
    assert sale["card"]["stamps"]["count"] == 2
    earn = sale["earn"]
    assert earn["source"] == "rules"
    assert earn["total"]["credited"] == 2
    assert earn["rules"][0]["kind"] == "stamp.perUnit"
    assert earn["rules"][0]["units"] == 2
    assert earn["rules"][0]["lines"] == ["a"]
    assert {line["lineId"]: line["earned"] for line in earn["lines"]} == {"a": 2, "b": 0}
    world.state["earn_sale_key"] = key
    again = world.client.record_sale(
        serial, idempotency_key=key,
        body={"locationId": world.location_id, "amountMinor": TOTAL, "currency": world.currency, "reference": f"fis-earn-{world.run}", "lines": LINES},
    )
    assert again["duplicate"] is True
    assert again["balance"] == 2


def test_seen_lines_remember_the_categories(world: World) -> None:
    seen = world.client.list_seen_lines()
    labels = {row["key"] for row in seen.data}
    assert "içecek > sıcak" in labels
    sources = world.client.list_earn_sources()
    assert any(s["kind"] == "key" for s in sources)


def test_refund_one_unit_of_a_line(world: World) -> None:
    serial = world.state["earn_serial"]
    refund = world.client.reverse_sale(
        serial, idempotency_key=world.key("earn-refund-1"),
        body={"saleKey": world.state["earn_sale_key"], "lines": [{"lineId": "a", "quantity": 1}]},
    )
    assert refund["reversed"] == 1
    assert refund["balance"] == 1
    assert refund["card"]["stamps"]["count"] == 1
    left = {row["lineId"]: row for row in refund["linesLeft"]}
    assert left["a"]["quantity"] == 1
    assert left["a"]["amountMinor"] == 9000
    assert left["b"]["quantity"] == 1


def test_refund_the_rest_and_the_refusals(world: World) -> None:
    serial = world.state["earn_serial"]
    sale_key = world.state["earn_sale_key"]
    with pytest.raises(RewloyError) as unknown:
        world.client.reverse_sale(serial, idempotency_key=world.key("earn-refund-x"), body={"saleKey": sale_key, "lines": [{"lineId": "zzz"}]})
    assert (unknown.value.status, unknown.value.code) == (404, "LINE_NOT_FOUND")
    rest = world.client.reverse_sale(serial, idempotency_key=world.key("earn-refund-2"), body={"saleKey": sale_key, "lines": [{"lineId": "a"}]})
    assert rest["balance"] == 0
    with pytest.raises(RewloyError) as gone:
        world.client.reverse_sale(serial, idempotency_key=world.key("earn-refund-3"), body={"saleKey": sale_key, "lines": [{"lineId": "a"}]})
    assert (gone.value.status, gone.value.code) == (409, "LINE_ALREADY_REFUNDED")
    assert gone.value.details == {"lineId": "a"}


def test_take_the_rules_and_the_group_away(world: World) -> None:
    program = _program(world)
    group = world.state["earn_group"]
    world.client.delete_earn_rules(program["id"])
    assert world.client.get_earn_rules(program["id"])["active"] is False
    world.client.delete_earn_group(group["id"])
    world.earn_group_ids.remove(group["id"])
    with pytest.raises(RewloyError) as gone:
        world.client.get_earn_group(group["id"])
    assert (gone.value.status, gone.value.code) == (404, "GROUP_NOT_FOUND")
