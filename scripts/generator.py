"""The generator: Rewloy's OpenAPI 3.1 document in, the Python of
src/rewloy/generated/ out.

Pure, with no I/O, so that a test can run it on the committed snapshot and
compare (tests/test_generate.py); scripts/generate.py is the command around it.

It reads only what the document says, the way the platform writes it
(src/api/openapi.ts there): inline JSON Schemas, ``Error`` and ``PageMeta`` as
components, ``x-credentials`` for the credential kinds, the ``Rewloy-Merchant``
and ``Idempotency-Key`` header parameters, the ``{ data[, meta] }`` envelope and
one example per error code. Its own emitter: the subset is small, and one
method per operation with named types per operation is the shape the library
wants.

Output (deterministic: the document's order, no dates):

  types.py       a TypedDict per object schema, a name per operation part,
                 ``ErrorCode``
  operations.py  the metadata table (OPERATIONS) and the error titles
  methods.py     one method per operation, in snake_case, and the typed
                 ``paginate`` overloads
  __init__.py    a docstring
"""

from __future__ import annotations

import keyword
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, NoReturn, Optional, Sequence, Set, Tuple

if TYPE_CHECKING:
    from typing_extensions import TypeGuard

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
MERCHANT_HEADER = "rewloy-merchant"
IDEMPOTENCY_HEADER = "idempotency-key"
SECURITY_KINDS = {"apiKey": "key", "staffSession": "staff", "holderSession": "holder"}
REFERENCE = "https://rewloy.com/gelistiriciler/api"
CHANGELOG = "https://rewloy.com/gelistiriciler/degisiklikler"
OUT = "src/rewloy/generated"

#: Names the client defines itself (and the ones every object has): no operation may take them as a method name.
RESERVED_METHODS = frozenset({
    "request", "paginate", "stream", "close", "credential", "base_url", "timeout", "max_retries", "merchant",
    "user_agent",
})
#: Keyword arguments every generated method has: no path parameter may take them as a name.
RESERVED_ARGUMENTS = frozenset({
    "self", "query", "body", "headers", "merchant", "idempotency_key", "timeout", "max_retries", "reconnect",
    "idle_timeout",
})
#: Names the generated types module imports.
RESERVED_TYPES = frozenset({"Any", "Dict", "List", "Literal", "Optional", "TypedDict", "Union"})
TR_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")

Json = Any
Obj = Dict[str, Any]


class GenerationError(Exception):
    """The document holds something the generator does not understand."""


def fail(message: str) -> NoReturn:
    raise GenerationError(f"generate: {message}")


@dataclass(frozen=True)
class GeneratedFile:
    #: Relative to the repository root.
    path: str
    content: str


def is_obj(v: Any) -> "TypeGuard[Dict[str, Any]]":
    return isinstance(v, dict)


def as_obj(v: Any) -> Obj:
    return v if isinstance(v, dict) else {}


def as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def as_str(v: Any) -> Optional[str]:
    return v if isinstance(v, str) else None


def pascal(text: str) -> str:
    """``passAction`` or ``weird-name`` to ``PassAction`` or ``WeirdName``."""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", text) if p)


def snake(text: str) -> str:
    """``passAction`` to ``pass_action``; ``getQRCode`` to ``get_qr_code``; ``setTeam2fa`` to ``set_team2fa``."""
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()


def lit(v: Json) -> str:
    """A Python literal for a JSON scalar (a JSON string is a valid Python string literal)."""
    if isinstance(v, bool):
        return "True" if v else "False"
    if v is None:
        return "None"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return "Any"


def one_line(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ------------------------------------------------------------------ reading


@dataclass
class Param:
    name: str
    schema: Json
    required: bool
    description: Optional[str]


@dataclass
class Op:
    id: str
    type: str  # PascalCase id
    method_name: str  # snake_case id
    method: str  # GET, POST…
    path: str
    tag: str
    summary: str
    description: str
    auth: List[str]
    deprecated: Optional[Tuple[Optional[str], Optional[str]]]  # (sunset, use)
    path_params: List[Param]
    query_params: List[Param]
    merchant: Optional[Param]
    idempotency: Optional[Param]
    other_headers: List[Param]
    body: Optional[Tuple[Json, bool]]  # (schema, required)
    response: str  # json | none | blob | raw-json | stream
    paged: bool
    data_schema: Json
    success_statuses: List[str]
    deprecated_fields: List[Tuple[str, Optional[str], Optional[str]]] = field(default_factory=list)  # (path, sunset, use)


def read_params(op: Obj, where: str) -> List[Param]:
    out: List[Param] = []
    for p in as_list(op.get("parameters")):
        if not isinstance(p, dict) or p.get("in") != where:
            continue
        name = as_str(p.get("name"))
        if name is None:
            fail("a parameter without a name")
        schema = as_obj(p.get("schema"))
        out.append(Param(name, schema, p.get("required") is True, as_str(p.get("description")) or as_str(schema.get("description"))))
    return out


def parse_deprecation(description: str) -> Tuple[Optional[str], Optional[str]]:
    """``"1 Nisan 2027"`` (the document's deprecation sentence) to ``"2027-04-01"``; and the replacement."""
    date = re.search(r"(\d{1,2}) (" + "|".join(TR_MONTHS) + r") (\d{4})", description)
    use = re.search(r"yerine `([A-Za-z0-9_]+)`", description)
    sunset = f"{date.group(3)}-{TR_MONTHS.index(date.group(2)) + 1:02d}-{int(date.group(1)):02d}" if date else None
    return sunset, use.group(1) if use else None


def find_deprecated_fields(schema: Json, path: str, out: List[Tuple[str, Optional[str], Optional[str]]]) -> None:
    """Properties marked ``deprecated`` in a schema (``data[].email``), with their sunset and replacement."""
    if not isinstance(schema, dict):
        return
    for name, sub in as_obj(schema.get("properties")).items():
        here = f"{path}.{name}" if path else name
        if isinstance(sub, dict) and sub.get("deprecated") is True:
            dep = as_obj(sub.get("x-deprecation"))
            out.append((here, as_str(sub.get("x-sunset")) or as_str(dep.get("sunset")), as_str(sub.get("x-replacement")) or as_str(dep.get("use"))))
        find_deprecated_fields(sub, here, out)
    if isinstance(schema.get("items"), dict):
        find_deprecated_fields(schema["items"], f"{path}[]", out)


def read_op(path: str, method: str, op: Obj) -> Op:
    oid = as_str(op.get("operationId"))
    if oid is None:
        fail(f"{method.upper()} {path} has no operationId")
    if not re.fullmatch(r"[a-z][A-Za-z0-9]*", oid):
        fail(f'operationId "{oid}" is not camelCase')
    name = snake(oid)
    if name in RESERVED_METHODS or keyword.iskeyword(name) or name.startswith("_"):
        fail(f'operationId "{oid}" collides with a client method ({name})')

    headers = read_params(op, "header")
    merchant = next((h for h in headers if h.name.lower() == MERCHANT_HEADER), None)
    idempotency = next((h for h in headers if h.name.lower() == IDEMPOTENCY_HEADER), None)
    other = [h for h in headers if h is not merchant and h is not idempotency]

    auth: List[str] = []
    if isinstance(op.get("x-credentials"), list):
        auth = [str(c) for c in op["x-credentials"]]
    else:
        for entry in as_list(op.get("security")):
            if isinstance(entry, dict):
                auth.extend(["public"] if not entry else [SECURITY_KINDS.get(str(k), str(k)) for k in entry])

    body: Optional[Tuple[Json, bool]] = None
    if isinstance(op.get("requestBody"), dict):
        request_body: Obj = op["requestBody"]
        json_media = as_obj(request_body.get("content")).get("application/json")
        if not isinstance(json_media, dict):
            fail(f"{oid}: only application/json request bodies are supported")
        body = (as_obj(json_media.get("schema")), request_body.get("required") is True)

    if not isinstance(op.get("responses"), dict):
        fail(f"{oid} has no responses")
    responses: Obj = op["responses"]
    success = sorted(str(s) for s in responses if re.fullmatch(r"2\d\d", str(s)))
    if not success:
        fail(f"{oid} has no 2xx response")
    content = as_obj(as_obj(responses[success[0]]).get("content"))
    paged = False
    data_schema: Json = None
    if not content or success[0] == "204":
        response = "none"
    else:
        ctype, media = next(iter(content.items()))
        schema = as_obj(as_obj(media).get("schema"))
        is_json = re.match(r"application/([a-z.+-]+\+)?json\b", ctype) is not None
        props = as_obj(schema.get("properties"))
        if ctype.startswith("text/event-stream"):
            response = "stream"
        elif is_json and "data" in props:
            response = "json"
            data_schema = props["data"]
            paged = "meta" in props
        else:
            response = "raw-json" if is_json else "blob"

    description = as_str(op.get("description")) or ""
    deprecated: Optional[Tuple[Optional[str], Optional[str]]] = None
    if op.get("deprecated") is True:
        parsed = parse_deprecation(description)
        deprecated = (as_str(op.get("x-sunset")) or parsed[0], as_str(op.get("x-replacement")) or parsed[1])

    fields: List[Tuple[str, Optional[str], Optional[str]]] = []
    if response == "json":
        find_deprecated_fields(data_schema, "data", fields)

    tags = as_list(op.get("tags"))
    return Op(
        id=oid, type=pascal(oid), method_name=name, method=method.upper(), path=path,
        tag=tags[0] if tags and isinstance(tags[0], str) else "",
        summary=as_str(op.get("summary")) or "", description=description,
        auth=auth, deprecated=deprecated,
        path_params=read_params(op, "path"), query_params=read_params(op, "query"),
        merchant=merchant, idempotency=idempotency, other_headers=other, body=body,
        response=response, paged=paged, data_schema=data_schema, success_statuses=success, deprecated_fields=fields,
    )


def error_titles(paths: Obj) -> Dict[str, str]:
    """Error titles, from each error code's example (``summary`` is the catalogue's title)."""
    titles: Dict[str, str] = {}
    for item in paths.values():
        for m in HTTP_METHODS:
            for r in as_obj(as_obj(as_obj(item).get(m)).get("responses")).values():
                media = as_obj(as_obj(as_obj(r).get("content")).get("application/json"))
                for code, ex in as_obj(media.get("examples")).items():
                    title = as_str(as_obj(ex).get("summary"))
                    if title and code not in titles:
                        titles[code] = title
    return titles


# ------------------------------------------------------------------ types


class Names:
    """Hands out unique type names: the first taker of a name keeps it, a later one gets a number."""

    def __init__(self) -> None:
        self.used: Set[str] = set(RESERVED_TYPES)

    def reserve(self, name: str) -> None:
        if name in self.used:
            fail(f"type name {name} collides")
        self.used.add(name)

    def take(self, base: str) -> str:
        name, n = base, 2
        while name in self.used:
            name, n = f"{base}{n}", n + 1
        self.used.add(name)
        return name


class TypeEmitter:
    """Python types for JSON Schemas. An object becomes a named TypedDict, emitted into ``defs`` before the
    definition that uses it; everything else is an expression."""

    def __init__(self, components: Mapping[str, str], names: Names) -> None:
        self.components = components
        self.names = names
        self.defs: List[str] = []
        #: Every public name defined so far, in the order of definition (``__all__``).
        self.exported: List[str] = []

    # -- expressions

    def ref(self, ref: str) -> str:
        m = re.fullmatch(r"#/components/schemas/(.+)", ref)
        mapped = self.components.get(m.group(1)) if m else None
        return mapped if mapped is not None else fail(f"unsupported $ref {ref}")

    @staticmethod
    def union(members: Sequence[str]) -> str:
        unique = list(dict.fromkeys(members))
        if "Any" in unique:
            return "Any"
        if not unique:
            return "Any"
        if len(unique) == 1:
            return unique[0]
        if "None" in unique:
            rest = [m for m in unique if m != "None"]
            return f"Optional[{rest[0]}]" if len(rest) == 1 else f"Union[{', '.join(rest)}, None]"
        return f"Union[{', '.join(unique)}]"

    def type(self, schema: Json, hint: str, name: Optional[str] = None) -> str:
        """The Python type of a JSON Schema. ``hint`` names the object types found inside it; ``name`` is the exact
        name its own object type must take."""
        if schema is None or schema is True:
            return "Any"
        if schema is False:
            fail("a schema of `false` cannot be typed")
        if not isinstance(schema, dict):
            fail("a schema that is not an object")
        if isinstance(schema.get("$ref"), str):
            out = self.ref(schema["$ref"])
        elif "const" in schema:
            out = f"Literal[{lit(schema['const'])}]"
        elif isinstance(schema.get("enum"), list):
            out = f"Literal[{', '.join(lit(v) for v in schema['enum'])}]"
        elif "allOf" in schema:
            fail("allOf is not supported")
        elif isinstance(schema.get("oneOf"), list) or isinstance(schema.get("anyOf"), list):
            members = as_list(schema.get("oneOf")) or as_list(schema.get("anyOf"))
            out = self.union([self.type(s, f"{hint}Option{i + 1}") for i, s in enumerate(members)])
        else:
            declared = schema.get("type")
            if isinstance(declared, list):
                types = [str(t) for t in declared]
            elif isinstance(declared, str):
                types = [declared]
            elif is_obj(schema.get("properties")) or "additionalProperties" in schema:
                types = ["object"]
            elif "items" in schema:
                types = ["array"]
            else:
                types = []
            out = self.union([self.single(t, schema, hint, name) for t in types]) if types else "Any"
        if schema.get("nullable") is True:
            out = self.union([out, "None"])
        return out

    def single(self, kind: str, schema: Obj, hint: str, name: Optional[str]) -> str:
        if kind == "string":
            return "bytes" if schema.get("format") == "binary" else "str"
        if kind == "integer":
            return "int"
        if kind == "number":
            return "float"
        if kind == "boolean":
            return "bool"
        if kind == "null":
            return "None"
        if kind == "array":
            items = self.type(schema.get("items"), f"{hint}Item")
            return f"List[{items}]"
        if kind == "object":
            return self.object(schema, hint, name)
        return "Any"

    def object(self, schema: Obj, hint: str, name: Optional[str] = None, nested: Optional[Mapping[str, str]] = None) -> str:
        props = schema.get("properties") if is_obj(schema.get("properties")) else {}
        extra = schema.get("additionalProperties")
        if not props:
            if extra is None or extra is False or extra is True:
                return "Dict[str, Any]"
            return f"Dict[str, {self.type(extra, f'{hint}Value')}]"
        # A TypedDict has no room for other keys: an object that allows them is a plain dict.
        if extra is True or is_obj(extra):
            return "Dict[str, Any]"
        required = {str(r) for r in schema.get("required", [])} if isinstance(schema.get("required"), list) else set()
        fields: List[Tuple[str, str, bool, str]] = []
        taken = name if name is not None else self.names.take(hint)
        for key, sub in props.items():
            sub_hint = (nested or {}).get(key) or f"{taken}{pascal(key)}"
            expression = self.type(sub, sub_hint)
            notes: List[str] = []
            if is_obj(sub):
                if isinstance(sub.get("description"), str):
                    notes.append(one_line(sub["description"]))
                if sub.get("deprecated") is True:
                    notes.append("Deprecated" + self.deprecation_suffix(sub))
            fields.append((key, expression, key in required, " ".join(notes)))
        description = one_line(schema.get("description")) if isinstance(schema.get("description"), str) else ""
        self.typed_dict(taken, fields, description)
        return taken

    @staticmethod
    def deprecation_suffix(sub: Obj) -> str:
        dep = as_obj(sub.get("x-deprecation"))
        sunset = sub.get("x-sunset") or dep.get("sunset")
        use = sub.get("x-replacement") or dep.get("use")
        parts = [f"sunset {sunset}" if sunset else "", f"use `{use}`" if use else ""]
        text = ", ".join(p for p in parts if p)
        return f" ({text})" if text else ""

    # -- definitions

    def typed_dict(self, name: str, fields: Sequence[Tuple[str, str, bool, str]], description: str) -> None:
        required = [f for f in fields if f[2]]
        optional = [f for f in fields if not f[2]]
        doc = f'    """{escape_doc(description)}"""\n' if description else ""
        self.exported.append(name)
        if required and optional:
            r = self.names.take(f"_{name}Required")
            o = self.names.take(f"_{name}Optional")
            self.defs.append(self.part(r, required, True))
            self.defs.append(self.part(o, optional, False))
            self.defs.append(f"class {name}({r}, {o}):\n{doc or '    pass'}\n")
            return
        total = bool(required) or not optional
        self.defs.append(self.part(name, list(fields), total, description))

    @staticmethod
    def part(name: str, fields: Sequence[Tuple[str, str, bool, str]], total: bool, description: str = "") -> str:
        """One TypedDict: class syntax when every key is an identifier, the functional one otherwise (``from``)."""
        flag = "" if total else ", total=False"
        if all(k.isidentifier() and not keyword.iskeyword(k) for k, _, _, _ in fields):
            lines = [f"class {name}(TypedDict{flag}):"]
            if description:
                lines.append(f'    """{escape_doc(description)}"""')
            for key, expression, _, note in fields:
                if note:
                    lines.append(f"    # {note}")
                lines.append(f"    {key}: {expression}")
            return "\n".join(lines) + "\n"
        lines = [f'{name} = TypedDict("{name}", {{']
        for key, expression, _, note in fields:
            if note:
                lines.append(f"    # {note}")
            lines.append(f"    {lit(key)}: {expression},")
        lines.append(f"}}{flag})")
        return "\n".join(lines) + "\n"

    def declare(self, name: str, schema: Json, description: str = "", nested: Optional[Mapping[str, str]] = None) -> None:
        """A top-level name for a schema: a TypedDict for an object, an alias for anything else."""
        own = one_line(schema.get("description")) if is_obj(schema) and isinstance(schema.get("description"), str) else ""
        text = " ".join(x for x in (description, own) if x)
        if is_obj(schema) and not isinstance(schema.get("$ref"), str) and self.is_typed_dict(schema):
            # The object type takes ``name`` itself.
            self.object_named(schema, name, text, nested)
            return
        expression = self.type(schema, name)
        self.exported.append(name)
        self.defs.append(f"{name} = {expression}\n")

    def object_named(self, schema: Obj, name: str, description: str, nested: Optional[Mapping[str, str]]) -> None:
        # Same as ``object`` with a fixed name and the caller's description.
        self.object({**schema, "description": description}, name, name, nested)

    @staticmethod
    def is_typed_dict(schema: Obj) -> bool:
        declared = schema.get("type")
        kinds = declared if isinstance(declared, list) else [declared] if isinstance(declared, str) else ["object"] if is_obj(schema.get("properties")) else []
        non_null = [k for k in kinds if k != "null"]
        return (
            non_null == ["object"] and len(kinds) == len(non_null) and is_obj(schema.get("properties")) and bool(schema.get("properties"))
            and not (schema.get("additionalProperties") is True or is_obj(schema.get("additionalProperties")))
            and "oneOf" not in schema and "anyOf" not in schema and "enum" not in schema and "const" not in schema
        )


def escape_doc(text: str) -> str:
    """Text for a docstring: backslashes and triple quotes cannot end it early or start an escape."""
    text = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return text[:-1] + '\\"' if text.endswith('"') else text


# ------------------------------------------------------------------ files

HEADER = (
    "# Generated by scripts/generate.py from the Rewloy OpenAPI document\n"
    "# (openapi/openapi.json, API {version}). Do not edit: run `python scripts/generate.py`.\n"
)


def header(version: str) -> str:
    return HEADER.format(version=version)


def is_required_free(schema: Json) -> bool:
    """No required property at the top level: ``{}`` is a valid body."""
    return not is_obj(schema) or not isinstance(schema.get("required"), list) or len(schema["required"]) == 0


def body_required(op: Op) -> bool:
    return op.body is not None and op.body[1] and not is_required_free(op.body[0])


def params_typed_dict(e: TypeEmitter, name: str, params: Sequence[Param], description: str) -> None:
    fields = [(p.name, e.type(p.schema, f"{name}{pascal(p.name)}"), p.required, one_line(p.description)) for p in params]
    e.typed_dict(name, fields, description)


def types_file(version: str, components: Obj, ops: Sequence[Op], codes: Sequence[str], e: TypeEmitter, names: Mapping[str, str]) -> str:
    out: List[str] = [
        header(version),
        '"""The types of the Rewloy API: request bodies, query parameters, answers. Generated; import them from',
        '``rewloy.types``."""',
        "",
        "from typing import Any, Dict, List, Literal, Optional, TypedDict, Union",
        "",
    ]
    code_lines = ",\n".join(f"    {lit(c)}" for c in codes)
    out.append(f"#: Every error code the API can answer with (the catalogue: https://rewloy.com/gelistiriciler/hatalar).\n"
               f"#: New codes may be added without notice: keep a default branch.\n"
               f"ErrorCode = Literal[\n{code_lines},\n]\n")
    for name, schema in components.items():
        ts_name = names[name]
        if name == "Error":
            e.declare(ts_name, schema, "The body of an error answer.", nested={"error": "ErrorInfo"})
        else:
            e.declare(ts_name, schema, one_line(schema.get("description")) if is_obj(schema) else "")
    parts = "\n\n".join(e.defs)
    e.defs.clear()

    chunks: List[str] = []
    for op in ops:
        chunks.append(f"# {'-' * 70}\n# {op.id} · {op.method} {op.path}\n")
        if op.path_params:
            params_typed_dict(e, f"{op.type}Params", op.path_params, f"Path parameters of `{op.id}`.")
        if op.query_params:
            params_typed_dict(e, f"{op.type}Query", op.query_params, f"Query parameters of `{op.id}`.")
        headers = [h for h in (op.merchant, op.idempotency) if h is not None] + op.other_headers
        if headers:
            params_typed_dict(e, f"{op.type}Headers", headers, f"Header parameters of `{op.id}`, as sent on the wire.")
        if op.body is not None:
            e.declare(f"{op.type}Body", op.body[0], f"Request body of `{op.id}`.")
        if op.response == "json":
            data = op.data_schema
            items = data.get("items") if is_obj(data) and data.get("type") == "array" else None
            if op.paged or (is_obj(items) and (items.get("type") == "object" or is_obj(items.get("properties")))):
                e.declare(f"{op.type}Item", items, f"One item of `{op.id}`'s list.")
                if not op.paged:
                    e.exported.append(f"{op.type}Data")
                    e.defs.append(f"{op.type}Data = List[{op.type}Item]\n")
            else:
                e.declare(f"{op.type}Data", data, f"The `data` of `{op.id}`'s answer.")
        chunks.append("\n\n".join(e.defs))
        e.defs.clear()
    out.append(parts)
    out.extend(chunks)

    exported = ["ErrorCode"] + list(dict.fromkeys(e.exported))
    out.append("__all__ = [\n" + "".join(f"    {lit(n)},\n" for n in exported) + "]\n")
    return "\n".join(out)


def operations_file(version: str, ops: Sequence[Op], titles: Sequence[Tuple[str, str]]) -> str:
    out: List[str] = [
        header(version),
        '"""The metadata table of the API: per operation, its method and path, the credential kinds it accepts, whether it',
        'takes ``Rewloy-Merchant`` and ``Idempotency-Key``, how its answer is read and whether it is paged, streams or is',
        'deprecated. Generated."""',
        "",
        "from typing import Dict",
        "",
        "from ..common import Deprecation, OperationMeta",
        "",
        f"#: The version of the API document this was generated from (``info.version``).\nAPI_VERSION = {lit(version)}\n",
        "#: Every operation by its operationId.",
        "OPERATIONS: Dict[str, OperationMeta] = {",
    ]
    for op in ops:
        dep = "None" if op.deprecated is None else f"Deprecation(sunset={lit(op.deprecated[0])}, use={lit(op.deprecated[1])})"
        idem = "None" if op.idempotency is None else lit("required" if op.idempotency.required else "optional")
        out.append(
            f"    {lit(op.id)}: OperationMeta({lit(op.id)}, {lit(op.method_name)}, {lit(op.method)}, {lit(op.path)}, "
            f"({', '.join(lit(a) for a in op.auth)}{',' if len(op.auth) == 1 else ''}), "
            f"{lit(op.merchant is not None)}, {idem}, {lit(op.body is not None)}, {lit(op.response)}, "
            f"{lit(op.paged)}, {lit(op.response == 'stream')}, {dep}),"
        )
    out.append("}\n")
    out.append("#: Each operationId's method name on the client (``passAction`` is ``pass_action``).\n"
               "METHOD_NAMES: Dict[str, str] = {k: v.method_name for k, v in OPERATIONS.items()}\n")
    out.append("#: Each method name's operationId.\nOPERATION_IDS: Dict[str, str] = {v: k for k, v in METHOD_NAMES.items()}\n")
    titles_lines = "".join(f"    {lit(c)}: {lit(t)},\n" for c, t in titles)
    out.append(f"#: Each error code's one-line title in the catalogue (https://rewloy.com/gelistiriciler/hatalar).\n"
               f"ERROR_TITLES: Dict[str, str] = {{\n{titles_lines}}}\n")
    return "\n".join(out)


def reference(op: Op) -> str:
    return f"{REFERENCE}#op-{op.id}"


def deprecation_note(op: Op) -> str:
    assert op.deprecated is not None
    sunset, use = op.deprecated
    return " ".join(x for x in [
        f"The API stops answering this operation after {sunset}." if sunset else "The API will stop answering this operation.",
        f"Use `{use}` instead." if use else "",
        f"{CHANGELOG}#{op.id}",
    ] if x)


def docstring(op: Op, indent: str) -> str:
    parts = [escape_doc(t) for t in (op.summary.strip(), op.description.strip()) if t]
    parts.append(f"``{op.method} {op.path}``")
    parts.append(f"API referansı: {reference(op)}")
    if op.idempotency is not None:
        parts.append(
            "``idempotency_key`` is the ``Idempotency-Key`` header, required: 8–64 printable ASCII characters. The "
            "client never makes one up (a generated key would not survive a restart of your app); it sends this one "
            "on every retry of the call."
            if op.idempotency.required else
            "``idempotency_key`` is the ``Idempotency-Key`` header, optional: 8–64 printable ASCII characters. Left "
            "out, the client generates a UUID and sends the same one on every retry of the call."
        )
    if op.deprecated:
        parts.append(f".. deprecated:: {deprecation_note(op)}")
    if op.deprecated_fields:
        lines = ["Fields marked for removal:"]
        for path, sunset, use in op.deprecated_fields:
            lines.append(f"- ``{path}``" + (f" (until {sunset})" if sunset else "") + (f", use ``{use}``" if use else ""))
        parts.append("\n".join(lines))
    lines = "\n\n".join(parts).split("\n")
    out = [f'{indent}"""{lines[0]}'] + [f"{indent}{line}".rstrip() for line in lines[1:]] + [f'{indent}"""']
    return "\n".join(out)


def result_type(op: Op) -> str:
    if op.response == "none":
        return "None"
    if op.response == "blob":
        return "bytes"
    if op.response == "raw-json":
        return "Any"
    if op.response == "stream":
        return "EventStream"
    return f"Page[T.{op.type}Item]" if op.paged else f"T.{op.type}Data"


def path_arg(p: Param) -> str:
    name = snake(p.name)
    if keyword.iskeyword(name):
        name += "_"
    if name in RESERVED_ARGUMENTS or not name.isidentifier():
        fail(f"path parameter {p.name} of an operation collides with a keyword argument ({name})")
    return name


def method_source(op: Op, e: TypeEmitter) -> str:
    sig: List[str] = ["self"]
    path_names = [(p, path_arg(p)) for p in op.path_params]
    for p, arg in path_names:
        sig.append(f"{arg}: {e.type(p.schema, 'Unused')}")
    sig.append("*")
    call: List[str] = [lit(op.id)]
    if path_names:
        call.append("path={" + ", ".join(f"{lit(p.name)}: {arg}" for p, arg in path_names) + "}")
    if op.query_params:
        required = any(p.required for p in op.query_params)
        sig.append(f"query: T.{op.type}Query" if required else f"query: Optional[T.{op.type}Query] = None")
        call.append("query=query")
    if op.body is not None:
        sig.append(f"body: T.{op.type}Body" if body_required(op) else f"body: Optional[T.{op.type}Body] = None")
        call.append("body=body")
    if op.other_headers:
        required = any(h.required for h in op.other_headers)
        sig.append(f"headers: T.{op.type}Headers" if required else f"headers: Optional[T.{op.type}Headers] = None")
        call.append("headers=headers")
    if op.merchant is not None:
        sig.append("merchant: Optional[str] = None")
        call.append("merchant=merchant")
    if op.idempotency is not None:
        sig.append("idempotency_key: str" if op.idempotency.required else "idempotency_key: Optional[str] = None")
        call.append("idempotency_key=idempotency_key")
    sig.append("timeout: Optional[float] = None")
    call.append("timeout=timeout")
    sig.append("max_retries: Optional[int] = None")
    call.append("max_retries=max_retries")
    if op.response == "stream":
        sig.append("reconnect: bool = True")
        sig.append("idle_timeout: Optional[float] = None")
        call.append("reconnect=reconnect")
        call.append("idle_timeout=idle_timeout")

    result = result_type(op)
    lines = ["    def " + op.method_name + "("]
    lines += [f"        {s}," for s in sig]
    lines.append(f"    ) -> {result}:")
    lines.append(docstring(op, "        "))
    if op.response == "stream":
        args = "".join(f"            {c},\n" for c in call)
        lines.append(f"        return self._open(\n{args}        )")
    elif op.response == "none":
        args = "".join(f"            {c},\n" for c in call)
        lines.append(f"        self._call(\n{args}        )")
    else:
        args = "".join(f"                {c},\n" for c in call)
        lines.append(f'        return cast(\n            "{result}",\n            self._call(\n{args}            ),\n        )')
    return "\n".join(lines)


def paginate_overloads(ops: Sequence[Op]) -> str:
    out: List[str] = []
    for op in ops:
        if not op.paged:
            continue
        sig = ["self", f"operation_id: Literal[{lit(op.id)}]", "*"]
        if op.path_params:
            sig.append(f"path: T.{op.type}Params")
        sig.append(f"query: Optional[T.{op.type}Query] = None")
        if op.merchant is not None:
            sig.append("merchant: Optional[str] = None")
        sig += ["timeout: Optional[float] = None", "max_retries: Optional[int] = None"]
        out.append("    @overload\n    def paginate(\n" + "".join(f"        {s},\n" for s in sig) + f"    ) -> Iterator[T.{op.type}Item]: ...\n")
    return "\n".join(out)


def methods_file(version: str, ops: Sequence[Op], e: TypeEmitter) -> str:
    out: List[str] = [
        header(version),
        '"""One method per operation of the API, named by its operationId in snake_case. ``Rewloy`` extends it. Generated."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import TYPE_CHECKING, Any, Iterator, Literal, Mapping, Optional, cast, overload",
        "",
        "# Only the annotations name these, and the types module is big: importing the client does not load it.",
        "if TYPE_CHECKING:",
        "    from ..common import Page",
        "    from ..sse import EventStream",
        "    from . import types as T",
        "",
        "",
        "class RewloyMethods:",
        '    """One method per operation of the API, named by its operationId in snake_case."""',
        "",
        "    def _call(",
        "        self,",
        "        operation_id: str,",
        "        *,",
        "        path: Optional[Mapping[str, object]] = None,",
        "        query: Optional[Mapping[str, object]] = None,",
        "        body: object = None,",
        "        headers: Optional[Mapping[str, object]] = None,",
        "        merchant: Optional[str] = None,",
        "        idempotency_key: Optional[str] = None,",
        "        timeout: Optional[float] = None,",
        "        max_retries: Optional[int] = None,",
        "    ) -> object:",
        "        raise NotImplementedError",
        "",
        "    def _open(",
        "        self,",
        "        operation_id: str,",
        "        *,",
        "        path: Optional[Mapping[str, object]] = None,",
        "        query: Optional[Mapping[str, object]] = None,",
        "        headers: Optional[Mapping[str, object]] = None,",
        "        merchant: Optional[str] = None,",
        "        timeout: Optional[float] = None,",
        "        max_retries: Optional[int] = None,",
        "        reconnect: bool = True,",
        "        idle_timeout: Optional[float] = None,",
        "    ) -> EventStream:",
        "        raise NotImplementedError",
        "",
        "    def _paginate(",
        "        self,",
        "        operation_id: str,",
        "        *,",
        "        path: Optional[Mapping[str, object]] = None,",
        "        query: Optional[Mapping[str, object]] = None,",
        "        merchant: Optional[str] = None,",
        "        timeout: Optional[float] = None,",
        "        max_retries: Optional[int] = None,",
        "    ) -> Iterator[Any]:",
        "        raise NotImplementedError",
        "",
        paginate_overloads(ops),
        "    def paginate(",
        "        self,",
        "        operation_id: str,",
        "        *,",
        "        path: Optional[Mapping[str, object]] = None,",
        "        query: Optional[Mapping[str, object]] = None,",
        "        merchant: Optional[str] = None,",
        "        timeout: Optional[float] = None,",
        "        max_retries: Optional[int] = None,",
        "    ) -> Iterator[Any]:",
        '        """Walks a paged list item by item, asking for the next page (``page``) while ``meta`` says there is one.',
        "        ``query['page']`` sets where to start and ``query['limit']`` the page size.",
        "",
        "        ``operation_id`` is a paged list's operationId (``listCustomers``); ``path`` holds its path parameters.",
        '        """',
        "        return self._paginate(operation_id, path=path, query=query, merchant=merchant, timeout=timeout, max_retries=max_retries)",
    ]
    tag: Optional[str] = None
    for op in ops:
        if op.tag != tag:
            tag = op.tag
            out.append(f"\n    # {'-' * 60} {tag}")
        out.append("")
        out.append(method_source(op, e))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ entry


def generate(document: Any) -> List[GeneratedFile]:
    if not is_obj(document):
        fail("the document is not an object")
    openapi = document.get("openapi")
    if not isinstance(openapi, str) or not openapi.startswith("3."):
        fail("not an OpenAPI 3 document")
    version = as_str(as_obj(document.get("info")).get("version")) or "0.0.0"
    if not isinstance(document.get("paths"), dict):
        fail("the document has no paths")
    paths: Obj = document["paths"]
    comps = document.get("components")
    components: Obj = comps["schemas"] if is_obj(comps) and is_obj(comps.get("schemas")) else {}

    ops: List[Op] = []
    seen: Set[str] = set()
    seen_methods: Dict[str, str] = {}
    for path, item in paths.items():
        if not is_obj(item):
            continue
        for m in HTTP_METHODS:
            op = item.get(m)
            if not is_obj(op):
                continue
            o = read_op(path, m, op)
            if o.id in seen:
                fail(f'operationId "{o.id}" is used twice')
            if o.method_name in seen_methods:
                fail(f'operationIds "{seen_methods[o.method_name]}" and "{o.id}" make the same method name ({o.method_name})')
            seen.add(o.id)
            seen_methods[o.method_name] = o.id
            ops.append(o)
    if not ops:
        fail("the document has no operations")

    names = Names()
    comp_names: Dict[str, str] = {}
    for name in components:
        ts = "ErrorBody" if name == "Error" else pascal(re.sub(r"[^A-Za-z0-9_]", "_", name))
        names.reserve(ts)
        comp_names[name] = ts
    # Every declared name is reserved first, so that a nested type never takes one an operation needs.
    for op in ops:
        for suffix, present in (
            ("Params", bool(op.path_params)), ("Query", bool(op.query_params)),
            ("Headers", bool(op.merchant or op.idempotency or op.other_headers)), ("Body", op.body is not None),
            ("Data", op.response == "json"), ("Item", op.response == "json"),
        ):
            if present:
                try:
                    names.reserve(f"{op.type}{suffix}")
                except GenerationError:
                    fail(f"type name {op.type}{suffix} collides")
    e = TypeEmitter(comp_names, names)

    error_info = as_obj(as_obj(as_obj(components.get("Error")).get("properties")).get("error"))
    code_schema = as_obj(as_obj(error_info.get("properties")).get("code"))
    codes = [str(c) for c in as_list(code_schema.get("enum"))]
    title_map = error_titles(paths)
    titles = [(c, title_map[c]) for c in codes if c in title_map] + [(c, t) for c, t in title_map.items() if c not in codes]

    types_source = types_file(version, components, ops, codes or list(title_map), e, comp_names)
    return [
        GeneratedFile(f"{OUT}/__init__.py", header(version) + '\n"""Generated from the Rewloy OpenAPI document: ``types``, ``operations`` and ``methods``."""\n'),
        GeneratedFile(f"{OUT}/types.py", types_source),
        GeneratedFile(f"{OUT}/operations.py", operations_file(version, ops, titles)),
        GeneratedFile(f"{OUT}/methods.py", methods_file(version, ops, e)),
    ]
