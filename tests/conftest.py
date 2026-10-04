from __future__ import annotations

from typing import Callable, Iterator, List

import pytest

from rewloy import client as client_module

from .helpers import Handler, Stub


@pytest.fixture
def stub() -> Iterator[Callable[[Handler], Stub]]:
    """``stub(handler)`` starts a local API stub; every one is stopped when the test ends."""
    started: List[Stub] = []

    def start(handler: Handler) -> Stub:
        s = Stub(handler)
        started.append(s)
        return s

    yield start
    for s in started:
        s.close()


@pytest.fixture(autouse=True)
def fresh_deprecation_notices() -> Iterator[None]:
    """One warning per operation per process: every test starts with none given."""
    client_module._warned.clear()
    yield
    client_module._warned.clear()
