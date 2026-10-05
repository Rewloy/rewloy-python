"""Every generated method, against a stub that answers each operation the way the API does: the path, the verb, the
headers and the way the answer is read are checked for every one of them."""

from __future__ import annotations

import inspect
import json
import re
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib.parse import quote, urlsplit

import pytest

from rewloy import OPERATIONS, EventStream, OperationMeta, Page

from .helpers import Ctx, Stub, make_client

ROOT = Path(__file__).resolve().parent.parent
SPEC: Dict[str, Any] = json.loads((ROOT / "openapi" / "openapi.json").read_text(encoding="utf-8"))
SPEC_OPS: Dict[str, Dict[str, Any]] = {
    op["operationId"]: op for item in SPEC["paths"].values() for m, op in item.items() if m in ("get", "post", "put", "patch", "delete")
}


def answer(c: Ctx, meta: OperationMeta) -> None:
    if meta.stream:
        sse = c.stream()
        sse.write("data: hi\n\n")
        sse.end()
    elif meta.response == "none":
        c.raw(204)
    elif meta.response == "blob":
        c.raw(200, b"bytes", {"Content-Type": "application/octet-stream"})
    elif meta.response == "raw-json":
        c.json(200, {"openapi": "3.1.0"})
    elif meta.paged:
        c.json(200, {"data": [], "meta": {"page": 1, "pageSize": 50, "total": 0}})
    else:
        c.json(200, {"data": {}})


def required_query(operation_id: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in SPEC_OPS[operation_id].get("parameters", []):
        if p["in"] == "query" and p.get("required"):
            schema = p.get("schema", {})
            out[p["name"]] = schema["enum"][0] if "enum" in schema else "x"
    return out


@pytest.fixture(scope="module")
def stub_for_all() -> Any:
    holder: Dict[str, OperationMeta] = {}
    s = Stub(lambda c: answer(c, holder["op"]))
    yield s, holder
    s.close()


@pytest.mark.parametrize("operation_id", sorted(OPERATIONS))
def test_a_method_calls_its_operation(operation_id: str, stub_for_all: Any) -> None:
    s, holder = stub_for_all
    meta = OPERATIONS[operation_id]
    holder["op"] = meta
    client = make_client(s, staff_session="rws_x", merchant="m-1")
    method: Callable[..., Any] = getattr(client, meta.method_name)

    signature = inspect.signature(method)
    positional = [p for p in signature.parameters.values() if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
    names = re.findall(r"\{([^}]+)\}", meta.path)
    assert len(positional) == len(names), (operation_id, names, list(signature.parameters))
    values = [f"v{i}/" for i in range(len(names))]
    kwargs: Dict[str, Any] = {}
    if "query" in signature.parameters and signature.parameters["query"].default is inspect.Parameter.empty:
        kwargs["query"] = required_query(operation_id)
    if "body" in signature.parameters and signature.parameters["body"].default is inspect.Parameter.empty:
        kwargs["body"] = {}
    if "idempotency_key" in signature.parameters and signature.parameters["idempotency_key"].default is inspect.Parameter.empty:
        assert meta.idempotency == "required", operation_id
        kwargs["idempotency_key"] = "till-key-0001"
    else:
        assert meta.idempotency != "required", operation_id
    if meta.stream:
        kwargs["reconnect"] = False

    before = len(s.requests)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = method(*values, **kwargs)
        if isinstance(result, EventStream):
            assert [e.data for e in result] == ["hi"]
    assert len(s.requests) == before + 1
    seen = s.requests[-1]

    expected = meta.path
    for name, value in zip(names, values):
        expected = expected.replace("{" + name + "}", quote(value, safe=""))
    assert seen.method == meta.http_method
    assert urlsplit(seen.url).path == expected
    # The credential goes unless the operation does not take this kind but works without one.
    assert ("authorization" in seen.headers) == ("staff" in meta.auth or "public" not in meta.auth)
    assert ("rewloy-merchant" in seen.headers) == meta.merchant
    assert ("idempotency-key" in seen.headers) == (meta.idempotency is not None)
    assert ("content-type" in seen.headers) == meta.body
    if meta.body:
        assert seen.json() == {}

    if meta.response == "none":
        assert result is None
    elif meta.response == "blob":
        assert result == b"bytes"
    elif meta.response == "raw-json":
        assert result == {"openapi": "3.1.0"}
    elif meta.paged:
        assert isinstance(result, Page) and result.data == [] and result.meta["total"] == 0
    elif not meta.stream:
        assert result == {}
