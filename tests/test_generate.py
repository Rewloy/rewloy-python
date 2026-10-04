from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest

from generate import snapshot_text  # scripts/generate.py
from generator import GenerationError, generate, parse_deprecation, snake

ROOT = Path(__file__).resolve().parent.parent


def snapshot() -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads((ROOT / "openapi" / "openapi.json").read_text(encoding="utf-8"))
    return data


def test_is_deterministic_and_the_committed_output_is_current() -> None:
    first = generate(snapshot())
    second = generate(snapshot())
    assert first == second
    assert [f.path for f in first] == [
        "src/rewloy/generated/__init__.py",
        "src/rewloy/generated/types.py",
        "src/rewloy/generated/operations.py",
        "src/rewloy/generated/methods.py",
    ]
    for f in first:
        committed = (ROOT / f.path).read_text(encoding="utf-8")
        assert committed == f.content, f"{f.path} is out of date: run `python scripts/generate.py --file openapi/openapi.json`"


def test_the_snapshot_is_written_the_way_the_other_libraries_write_it() -> None:
    text = (ROOT / "openapi" / "openapi.json").read_text(encoding="utf-8")
    assert snapshot_text(json.loads(text)) == text
    assert text.endswith("}\n") and text.startswith('{\n  "openapi": "3.1.0",')
    assert snapshot_text({"a": 1.0, "b": [2.5, 3.0]}) == '{\n  "a": 1,\n  "b": [\n    2.5,\n    3\n  ]\n}\n'


def test_makes_one_method_per_operation_of_the_snapshot() -> None:
    doc = snapshot()
    ids = [op["operationId"] for item in doc["paths"].values() for m, op in item.items() if m in ("get", "post", "put", "patch", "delete")]
    assert len(ids) == 237 == len(set(ids))
    methods = next(f.content for f in generate(doc) if f.path.endswith("methods.py"))
    for operation_id in ids:
        assert re.search(rf"^    def {snake(operation_id)}\($", methods, re.M), operation_id
        assert f'"{operation_id}",' in methods


def test_every_generated_file_parses_for_python_3_9() -> None:
    for f in generate(snapshot()):
        ast.parse(f.content, feature_version=(3, 9))


def test_snake_case_names() -> None:
    assert snake("passAction") == "pass_action"
    assert snake("getQRCode") == "get_qr_code"
    assert snake("setTeam2fa") == "set_team2fa"
    assert snake("holderCardEvents") == "holder_card_events"
    assert snake("openapi") == "openapi"


def envelope(data: Any) -> Dict[str, Any]:
    return {"content": {"application/json": {"schema": {"type": "object", "required": ["data"], "properties": {"data": data}}}}}


def fixture() -> Dict[str, Any]:
    """A small document with the cases the live one does not have yet (and the ones it has)."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Fixture", "version": "9.9.9"},
        "paths": {
            "/v1/things/{id}": {
                "get": {
                    "operationId": "getThing", "tags": ["Şeyler"], "summary": "Bir şey",
                    "deprecated": True,
                    "description": '**Kullanımdan kalkıyor:** 1 Nisan 2027 tarihine kadar çalışır; yerine `getThingV2`. Ayrıntı: https://rewloy.com/gelistiriciler/degisiklikler#getThing\n\nÜç tırnak """ kapanmasın ve ters bölü \\ de.\nSon söz "tırnaklı"',
                    "x-credentials": ["key", "staff"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
                        {"name": "Rewloy-Merchant", "in": "header", "required": False, "schema": {"type": "string"}},
                        {"name": "status", "in": "query", "required": True, "schema": {"type": "string", "enum": ["a", "b"]}},
                    ],
                    "responses": {
                        "200": envelope({
                            "type": "object", "additionalProperties": False, "required": ["state", "weird-name", "from"],
                            "properties": {
                                "state": {"type": ["string", "null"], "enum": ["on", "off", None]},
                                "weird-name": {"oneOf": [{"const": "all"}, {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}}]},
                                "from": {"type": "string"},
                                "note": {"type": "string", "description": "Tırnak ' ve ters bölü \\ içerir"},
                                "extra": {"type": "object", "additionalProperties": {"type": "integer"}},
                                "free": {"type": "object", "additionalProperties": True, "properties": {"a": {"type": "string"}}},
                                "price": {"type": ["number", "null"]},
                                "nested": {"type": "object", "additionalProperties": False, "properties": {"deep": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["x"], "properties": {"x": {"type": "boolean"}}}}}},
                                "old": {"type": "string", "deprecated": True, "x-sunset": "2027-04-05", "x-replacement": "newer"},
                            },
                        }),
                        "404": {"description": "x", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}, "examples": {"NOT_FOUND": {"summary": "Bulunamadı", "value": {}}}}}},
                    },
                },
            },
            "/v1/things": {
                "get": {
                    "operationId": "listThings", "tags": ["Şeyler"], "summary": "Liste", "x-credentials": ["key"],
                    "parameters": [{"name": "page", "in": "query", "schema": {"type": "integer"}}, {"name": "X-Trace", "in": "header", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "x", "content": {"application/json": {"schema": {
                        "type": "object", "required": ["data", "meta"],
                        "properties": {"data": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id"], "properties": {"id": {"type": "string"}}}}, "meta": {"$ref": "#/components/schemas/PageMeta"}}}}}}},
                },
            },
            "/v1/things/{id}/events": {
                "get": {
                    "operationId": "thingEvents", "tags": ["Şeyler"], "summary": "Akış", "x-credentials": ["holder"],
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "x", "content": {"text/event-stream": {"schema": {"type": "string", "format": "binary"}}}}},
                },
                "delete": {
                    "operationId": "forgetThing", "tags": ["Şeyler"], "summary": "Sil", "security": [{"apiKey": []}, {}],
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}, {"name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string"}}],
                    "responses": {"204": {"description": "Tamam — gövde yok."}},
                },
            },
        },
        "components": {"schemas": {
            "Error": {"type": "object", "required": ["error"], "properties": {"error": {"type": "object", "required": ["code", "message", "requestId"], "properties": {
                "code": {"type": "string", "enum": ["NOT_FOUND", "INTERNAL"]}, "message": {"type": "string"}, "requestId": {"type": "string"}}}}},
            "PageMeta": {"type": "object", "required": ["page", "pageSize", "total"], "properties": {"page": {"type": "integer"}, "pageSize": {"type": "integer"}, "total": {"type": "integer"}}},
        }},
    }


@pytest.fixture(scope="module")
def files() -> Dict[str, str]:
    return {Path(f.path).name: f.content for f in generate(fixture())}


def test_marks_a_deprecated_operation_with_its_sunset_and_replacement(files: Dict[str, str]) -> None:
    assert parse_deprecation("**Kullanımdan kalkıyor:** 1 Nisan 2027 tarihine kadar çalışır; yerine `getThingV2`.") == ("2027-04-01", "getThingV2")
    assert parse_deprecation("**Kullanımdan kalkıyor:** 15 Aralık 2026 tarihine kadar çalışır.") == ("2026-12-15", None)
    assert ".. deprecated:: The API stops answering this operation after 2027-04-01. Use `getThingV2` instead." in files["methods.py"]
    assert '"getThing": OperationMeta("getThing", "get_thing", "GET", "/v1/things/{id}", ("key", "staff"), True, None, False, "json", False, False, Deprecation(sunset="2027-04-01", use="getThingV2")),' in files["operations.py"]


def test_keeps_docstrings_closed_and_the_source_valid(files: Dict[str, str]) -> None:
    methods = files["methods.py"]
    assert 'Üç tırnak \\"\\"\\" kapanmasın ve ters bölü \\\\ de.' in methods
    assert 'Son söz "tırnaklı\\"' in methods
    for content in files.values():
        compile(content, "generated", "exec")


def test_writes_the_types_the_schemas_say(files: Dict[str, str]) -> None:
    types = files["types.py"]
    namespace: Dict[str, Any] = {}
    exec(compile(types, "types.py", "exec"), namespace)
    data = namespace["GetThingData"]
    assert data.__required_keys__ == {"state", "weird-name", "from"}
    assert data.__optional_keys__ == {"note", "extra", "free", "price", "nested", "old"}
    assert namespace["ErrorCode"].__args__ == ("NOT_FOUND", "INTERNAL")
    assert namespace["ListThingsItem"].__required_keys__ == {"id"}
    assert 'state: Literal["on", "off", None]' not in types  # a key that is not an identifier makes the functional form
    assert '"state": Literal["on", "off", None],' in types
    assert '"weird-name": Union[Literal["all"], List[Union[str, int]]],' in types
    assert '"from": str,' in types
    assert "    note: str" in types and "    extra: Dict[str, int]" in types
    assert "    free: Dict[str, Any]" in types, "an object that allows other keys cannot be a TypedDict"
    assert "    price: Optional[float]" in types
    assert "    nested: GetThingDataNested" in types and "    deep: List[GetThingDataNestedDeepItem]" in types
    assert "# Deprecated (sunset 2027-04-05, use `newer`)" in types
    assert "class ErrorBody(TypedDict):" in types and "    error: ErrorInfo" in types
    assert "class GetThingQuery(TypedDict):" in types and "    status: Literal[\"a\", \"b\"]" in types
    assert "ListThingsHeaders = TypedDict(" in types and '"X-Trace": str,' in types
    assert "ListThingsData = List[ListThingsItem]" not in types  # a paged list has no Data
    assert "__all__" in namespace and "GetThingData" in namespace["__all__"]


def test_reads_streams_empty_answers_and_credentials_from_security(files: Dict[str, str]) -> None:
    ops = files["operations.py"]
    assert '"thingEvents": OperationMeta("thingEvents", "thing_events", "GET", "/v1/things/{id}/events", ("holder",), False, None, False, "stream", False, True, None),' in ops
    assert '"forgetThing": OperationMeta("forgetThing", "forget_thing", "DELETE", "/v1/things/{id}/events", ("key", "public"), False, "optional", False, "none", False, False, None),' in ops
    assert 'API_VERSION = "9.9.9"' in ops
    assert '"NOT_FOUND": "Bulunamadı",' in ops
    assert '"listThings": OperationMeta("listThings", "list_things", "GET", "/v1/things", ("key",), False, None, False, "json", True, False, None),' in ops
    methods = files["methods.py"]
    assert re.search(r"def thing_events\(\n        self,\n        id: str,\n        \*,\n.*?\) -> EventStream:", methods, re.S)
    assert re.search(r"def forget_thing\(.*?\) -> None:", methods, re.S)
    assert re.search(r"def list_things\(\n        self,\n        \*,\n        query: Optional\[T\.ListThingsQuery\] = None,\n        headers: T\.ListThingsHeaders,", methods)
    assert "def get_thing(\n        self,\n        id: str,\n        *,\n        query: T.GetThingQuery," in methods
    assert 'operation_id: Literal["listThings"],' in methods
    assert "    ) -> Iterator[T.ListThingsItem]: ..." in methods
    assert "-> Page[T.ListThingsItem]:" in methods


def test_refuses_what_it_cannot_generate() -> None:
    with pytest.raises(GenerationError, match="not an OpenAPI 3 document"):
        generate({})
    with pytest.raises(GenerationError, match="the document has no paths"):
        generate({"openapi": "3.1.0"})
    with pytest.raises(GenerationError, match="no operations"):
        generate({"openapi": "3.1.0", "paths": {}})

    def changed(operation_id: str, path: str = "/v1/things/{id}/events", method: str = "get") -> Dict[str, Any]:
        doc = copy.deepcopy(fixture())
        doc["paths"][path][method]["operationId"] = operation_id
        return doc

    with pytest.raises(GenerationError, match="used twice"):
        generate(changed("getThing"))
    for reserved in ("paginate", "request", "stream", "close", "merchant"):
        with pytest.raises(GenerationError, match="collides with a client method"):
            generate(changed(reserved))
    with pytest.raises(GenerationError, match="not camelCase"):
        generate(changed("Get_thing"))
    # Two ids that differ only in the case of a letter make one snake_case name.
    doc = fixture()
    doc["paths"]["/v1/things/{id}"]["get"]["operationId"] = "getUrl"
    doc["paths"]["/v1/things/{id}/events"]["get"]["operationId"] = "getURL"
    with pytest.raises(GenerationError, match='"getUrl" and "getURL" make the same method name'):
        generate(doc)


def test_refuses_constructs_it_does_not_support() -> None:
    doc = fixture()
    doc["paths"]["/v1/things/{id}"]["get"]["responses"]["200"] = envelope({"allOf": [{"type": "object"}]})
    with pytest.raises(GenerationError, match="allOf"):
        generate(doc)
    doc = fixture()
    doc["paths"]["/v1/things/{id}"]["get"]["responses"]["200"] = envelope({"$ref": "#/components/schemas/Nope"})
    with pytest.raises(GenerationError, match="unsupported \\$ref"):
        generate(doc)
    doc = fixture()
    doc["paths"]["/v1/things/{id}"]["get"]["requestBody"] = {"content": {"text/plain": {"schema": {"type": "string"}}}}
    with pytest.raises(GenerationError, match="only application/json"):
        generate(doc)
    doc = fixture()
    doc["paths"]["/v1/things/{id}"]["get"]["parameters"][0]["name"] = "body"
    with pytest.raises(GenerationError, match="collides with a keyword argument"):
        generate(doc)
    doc = fixture()
    doc["paths"]["/v1/things/{id}"]["get"]["responses"] = {"404": {"description": "x"}}
    with pytest.raises(GenerationError, match="no 2xx response"):
        generate(doc)
