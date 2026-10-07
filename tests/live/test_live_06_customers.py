"""Customer search."""
from __future__ import annotations

from .conftest import World


def test_search_finds_the_customer(world: World) -> None:
    email = world.emails[0]
    page = world.client.list_customers(query={"q": email})
    assert page.meta["total"] == 1
    customer = page.data[0]
    assert customer["email"] == email
    assert customer["passCount"] >= 1
    assert any(c["serial"] == world.state["stamp_a"] for c in customer["cards"])
    world.state["person_id"] = customer["personId"]


def test_get_customer(world: World) -> None:
    customer = world.client.get_customer(world.state["person_id"])
    assert customer["email"] == world.emails[0]
    assert customer["blocked"] is False


def test_search_for_nobody_is_empty(world: World) -> None:
    page = world.client.list_customers(query={"q": f"nobody-{world.run}@example.test"})
    assert page.data == []
    assert page.meta["total"] == 0
