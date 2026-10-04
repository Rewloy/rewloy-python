from __future__ import annotations

from typing import Any, Callable, Iterator, List
from urllib.parse import parse_qs, urlsplit

from rewloy.types import ListCustomersQuery

from .helpers import Ctx, Stub, loose, make_client

StubFactory = Callable[[Callable[[Ctx], None]], Stub]


def customers(stub: StubFactory, total: int) -> Stub:
    """A stub list of ``total`` customers, paged as the API pages."""

    def handle(c: Ctx) -> None:
        q = parse_qs(urlsplit(c.req.url).query)
        page = int(q.get("page", ["1"])[0])
        size = int(q.get("limit", ["50"])[0])
        n = max(0, min(size, total - (page - 1) * size))
        data = [{"personId": f"p{(page - 1) * size + i + 1}"} for i in range(n)]
        c.json(200, {"data": data, "meta": {"page": page, "pageSize": size, "total": total}})

    return stub(handle)


def ids(items: Iterator[Any]) -> List[str]:
    return [x["personId"] for x in items]


def test_walks_every_page_and_stops_at_the_total(stub: StubFactory) -> None:
    s = customers(stub, 5)
    c = make_client(s)
    assert ids(c.paginate("listCustomers", query={"limit": 2, "consent": "yes"})) == ["p1", "p2", "p3", "p4", "p5"]
    assert [r.url for r in s.requests] == [
        "/v1/customers?limit=2&consent=yes&page=1",
        "/v1/customers?limit=2&consent=yes&page=2",
        "/v1/customers?limit=2&consent=yes&page=3",
    ]


def test_does_not_ask_past_a_full_last_page(stub: StubFactory) -> None:
    s = customers(stub, 4)
    assert ids(make_client(s).paginate("listCustomers", query={"limit": 2})) == ["p1", "p2", "p3", "p4"]
    assert len(s.requests) == 2


def test_starts_at_the_page_given_and_handles_an_empty_list(stub: StubFactory) -> None:
    s = customers(stub, 5)
    assert ids(make_client(s).paginate("listCustomers", query={"limit": 2, "page": 2})) == ["p3", "p4", "p5"]
    empty = customers(stub, 0)
    assert ids(make_client(empty).paginate("listCustomers")) == []
    assert len(empty.requests) == 1


def test_is_lazy_and_stops_asking_when_the_caller_stops_reading(stub: StubFactory) -> None:
    s = customers(stub, 500)
    c = make_client(s)
    stream = c.paginate("listCustomers", query={"limit": 10})
    assert len(s.requests) == 0
    n = 0
    for _ in stream:
        n += 1
        if n == 15:
            break
    assert len(s.requests) == 2


def test_does_not_change_the_query_it_was_given(stub: StubFactory) -> None:
    s = customers(stub, 5)
    query: ListCustomersQuery = {"limit": 2}
    ids(make_client(s).paginate("listCustomers", query=query))
    assert query == {"limit": 2}


def test_gives_a_page_with_its_meta_through_the_method_itself(stub: StubFactory) -> None:
    s = customers(stub, 3)
    page = make_client(s).list_customers(query={"limit": 2})
    assert len(page.data) == 2
    assert page.meta == {"page": 1, "pageSize": 2, "total": 3}


def test_a_list_with_a_path_parameter_takes_it_as_path(stub: StubFactory) -> None:
    def handle(c: Ctx) -> None:
        c.json(200, {"data": [{"id": "x"}], "meta": {"page": 1, "pageSize": 50, "total": 1}})

    s = stub(handle)
    items = list(make_client(s).paginate("listBatchCards", path={"id": "b/1"}))
    assert loose(items) == [{"id": "x"}]
    assert s.last.url.startswith("/v1/batches/b%2F1/")
