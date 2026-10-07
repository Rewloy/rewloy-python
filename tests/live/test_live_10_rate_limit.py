"""Rate-limit headers are read into response.rate_limit."""
from __future__ import annotations

from .conftest import World


def test_rate_limit_headers_are_read(world: World) -> None:
    first = world.client.request("getBusiness")
    second = world.client.request("getBusiness")
    for answer in (first, second):
        assert answer.rate_limit is not None
        assert answer.rate_limit.limit >= 1
        assert 0 <= answer.rate_limit.remaining <= answer.rate_limit.limit
        assert answer.rate_limit.reset >= 0
    assert second.rate_limit is not None and first.rate_limit is not None
    assert second.rate_limit.remaining <= first.rate_limit.remaining  # inside one window it only goes down
    assert second.request_id and second.request_id != first.request_id
