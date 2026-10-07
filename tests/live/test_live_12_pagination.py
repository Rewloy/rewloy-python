"""Pagination of a list: paginate() walks every page once."""
from __future__ import annotations

from .conftest import World


def test_paginate_walks_all_pages(world: World) -> None:
    for tag in ("page-1", "page-2", "page-3"):
        world.client.issue_pass(body={"programId": world.stamp_program["id"], "email": world.email(tag), "kvkkConsent": True})
    query = {"q": f"livepy-{world.run}-page-", "limit": 1}
    first = world.client.request("listCustomers", query=query)
    assert first.meta is not None and first.meta["total"] == 3 and first.meta["pageSize"] == 1
    assert len(first.data) == 1
    walked = list(world.client.paginate("listCustomers", query=query))
    assert len(walked) == 3
    assert len({c["personId"] for c in walked}) == 3  # no page repeated, none skipped
    assert {c["email"] for c in walked} == set(world.emails[-3:])


def test_second_page_by_hand(world: World) -> None:
    page = world.client.list_customers(query={"q": f"livepy-{world.run}-page-", "limit": 2, "page": 2})
    assert page.meta["page"] == 2
    assert len(page.data) == 1
