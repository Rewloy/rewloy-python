# Decisions

Choices made while building v0.1 without the owner (4 Oct 2026). The Node
library's decisions (`Rewloy/rewloy-node`, docs/DECISIONS.md, 24 of them)
hold here unless one below replaces it. Each can be revisited; most are a
line to change.

**Reused as they are** (Node's numbers): own emitter (1), sunset dates read
from the platform's sentence (3), generation refuses what it does not
understand (5), English library text with the API's Turkish descriptions and
a bilingual README (8), a credential is left out where an operation does not
take its kind but works without one (13), construction is checked (14), the
retry rules and their numbers (15), timeouts per attempt, for a stream only
until its headers (16), idempotency keys (17: required where the API's
document says so and never made up for those, printable ASCII of 8–64
characters checked before sending, a UUID v4 only where optional), one error hierarchy with the same codes for what
never got an answer (18), test mode read from `Rewloy-Mode` on the answer, not
kept on the client (20), streams reconnect by default (21), webhooks accept
any `v1` and any of several secrets with a ±300 s tolerance (22), and the
regeneration workflow (24).

## Generation

1. **The generator is Python, in the repository** (`scripts/generator.py`,
   run by `scripts/generate.py`), not a Node script.
   - **Who needs what:** a Python developer who wants to regenerate needs only
     Python, with nothing to install.
   - **Tests:** they call `generate()` in-process (determinism, the committed
     output being current, a fixture of the cases the live document does not
     have, its refusals).
   - **The snapshot** is byte for byte what the Node, PHP and .NET libraries
     keep: `json.dumps(…, indent=2, ensure_ascii=False)` plus a newline
     equals `JSON.stringify(doc, null, 2)`, and whole floats are written as
     integers as JavaScript does. A test pins the format and `cmp` agrees.
2. **Where the generated code lives:** `src/rewloy/generated/` (`types.py`,
   `operations.py`, `methods.py`). `rewloy.types` re-exports the types, so
   that `from rewloy.types import IssuePassBody` is the address to document.
3. **A `TypedDict` per object schema, not dataclasses or pydantic.** The
   document has about 800 inline object schemas; they come out as about 830
   named TypedDicts (the nested ones are named `{Parent}{Property}`, a list's
   items `…Item`, and a clash gets a number).
   - **Forward compatible:** an answer is the decoded JSON, so a field the API
     adds is in your dict at once, before the next regeneration. A dataclass
     would drop it.
   - **No dependency, no copy:** requests and answers are plain dicts that
     `json` reads and writes. Nothing validates at run time: the API does, and
     `mypy` checks your side.
   - **Same data as Node and PHP,** whose methods return plain objects and
     arrays.
   - **The cost:** `answer["balance"]`, not `answer.balance`.
4. **Required and optional keys without `typing_extensions`.** `Required[]`
   and `NotRequired[]` are in `typing` from 3.11, and the library supports
   3.9, so an object with both kinds of key is two TypedDicts (`_XRequired`,
   `_XOptional(total=False)`) and a class that inherits both. A key that is
   not an identifier (`from`, one in the document today) makes that part the
   functional form, `TypedDict("X", {"from": str})`.
5. **What a TypedDict cannot say:**
   - an object with known keys **and** other keys (`additionalProperties`:
     two request fields today, the passkey `response`) is `Dict[str, Any]`,
     as in PHP: a TypedDict would refuse the other keys;
   - `number` is `float` (an `int` is accepted where a float is expected) and
     `format: binary` is `bytes`;
   - `enum` and `const` are `Literal[…]`, `oneOf` and `anyOf` are `Union[…]`
     and `null` is `Optional[…]`;
   - a `$ref` is resolved (only `Error` and `PageMeta` exist); `allOf` and an
     unknown `$ref` are refused.
6. **`ErrorCode` is a `Literal`, `RewloyError.code` is a `str`.** New codes
   come without notice: the Literal says what exists today, and an `if` on a
   code you have not seen is not a type error.
7. **The types are not loaded with the client.** The types module holds about
   a thousand classes and takes about 80 ms to import; only annotations name
   it, so the generated methods, `Page` and the client import it under
   `TYPE_CHECKING`. `import rewloy` does not load it (a test checks), and
   `import rewloy.types` does. The cost: `typing.get_type_hints()` on a
   generated method needs `rewloy.types` imported first.
8. **Method names are the operationId in snake_case** (`passAction` is
   `pass_action`, `setTeam2fa` is `set_team2fa`; an acronym run is one word:
   `getQRCode` would be `get_qr_code`).
   - **The mapping:** `METHOD_NAMES` (operationId to method name) and
     `OPERATION_IDS` (the other way) are in `rewloy`, and each row of
     `OPERATIONS` has both. `request()`, `paginate()` and `stream()` take
     either name.
   - **Refusals** beyond Node's: two ids that make the same snake_case name
     (`getUrl`, `getURL`), a method name the client has itself (`request`,
     `paginate`, `stream`, `close`, `credential`, `base_url`, `timeout`,
     `max_retries`, `merchant`, `user_agent`), a Python keyword, and a path
     parameter that takes one of the keyword arguments' names.
9. **The shape of a call:** path parameters are positional (`get_pass(serial)`),
   everything else is keyword-only: `query`, `body`, `merchant`,
   `idempotency_key`, `timeout`, `max_retries`.
   - **The dicts use the API's names** (`programId`, `kvkkConsent`), not
     snake_case. Translating keys would mean a rule for every key of a body
     that the generator cannot know is a name and not a value (`locations`
     holds ids, a design holds colours), and a mistake would be silent.
   - **A body whose fields are all optional** may be left out and is sent as
     `{}`, as Node does.
10. **`request()` is not typed by operation.** It returns `ApiResponse[Any]`:
    `ParamSpec` and `TypeVarTuple` are 3.10 and 3.11, and 237 overloads would
    double the file. For the whole answer of a typed call, `request()` takes
    the operationId and `typing.cast` fits the data. A generated twin per
    method (as .NET's `…WithResponseAsync`) is the way if it is asked for.
11. **`paginate()` is typed:** the generated class has one `@overload` per
    paged list (20), so that `for c in rewloy.paginate("listCustomers", …)` gives
    `ListCustomersItem`.
12. **Deprecated fields** (five today, all until 5 April 2027) are listed in
    their method's docstring (`data[].email`) and noted beside the key in the
    types, as PHP does.

## Language and package

13. **Python 3.9 and later**, as the brief says; CI runs 3.9 and 3.13.
    - **Annotations use `Optional` and `Union`, not `X | Y`,** so that
      `typing.get_type_hints()` (pydantic, FastAPI, Sphinx) works on 3.9. A
      test refuses the pipe in the library's annotations.
    - **Syntax:** a test parses every file with `feature_version=(3, 9)` and,
      on 3.12 and later, refuses an f-string that only 3.12 reads (its own
      quote inside the braces). `vermin` says 3.9 for `src` and `scripts`.
    - **Not run on a real 3.9 here:** the machine has Python 3.14 only, `uv`
      is not installed, and the brief asked for another interpreter only when
      the system one was older than 3.9. `mypy` 1.20 checked `src` and
      `scripts` as 3.9 (not `httpx_transport.py`, whose dependency `anyio` has
      3.10 syntax in the 3.14 environment), and the 3.9 job in CI runs the
      whole suite for real.
14. **No runtime dependencies:** `urllib.request`, `http.client`, `json`,
    `hmac`, `threading`. The `httpx` extra is optional (decision 20) and the
    `dev` extra has `pytest`, `mypy`, `build` and `httpx`.
15. **mypy `strict` on `src`, `scripts` and `tests`, against each
    interpreter's own version.** mypy 2 cannot target 3.9 (it says "must be 3.10
    or higher"), so the config has no `python_version`: the 3.13 job checks
    for 3.13 with the current mypy, and the 3.9 job gets mypy 1.x from pip and
    checks for 3.9. The package ships `py.typed`.
16. **Packaging:** hatchling, distribution `rewloy`, import `rewloy`. The
    version is `__version__` in `src/rewloy/_version.py`, which hatchling reads
    and `rewloy.VERSION` exports; a test keeps it equal to CHANGELOG.md's
    latest heading. The wheel holds `src/rewloy` (128 KB); the sdist adds the
    tests, scripts, docs and the snapshot, so that the tests run from it.
17. **Installed from GitHub until PyPI:** `pip install
    git+https://github.com/Rewloy/rewloy-python`, which builds with hatchling.
    The name `rewloy` was free on PyPI on 4 Oct 2026 (a 404 on its page).

## Client

18. **Sync only in 0.1; no async client.** The choice, with its reasons:
    - **The default transport blocks.** `urllib` has no async form. A real
      async client needs an async transport (`httpx.AsyncClient`), and then
      the retry loop (about 100 lines), the stream state machine and paging
      exist twice, or are rewritten sans-I/O: more than a copy-paste, and the
      kind of refactor that is better made once a user asks for it.
    - **A wrapper would pretend.** `asyncio.to_thread` over the sync client
      works (the client is thread-safe, the README shows it) but cannot cancel
      a call in flight, so it is not offered as `AsyncRewloy`.
    - **The generated file would double** (237 methods again).
    - **It is not closed off:** `Transport` is a protocol, and the generated
      methods call three functions (`_call`, `_open`, `_paginate`) that an
      async twin would replace.
19. **The default transport is `urllib.request`,** as the brief says, with
    these choices (`rewloy/transport.py`):
    - **No redirects.** The opener has no redirect handler: the API does not
      redirect, and following one could carry the token elsewhere. A 3xx is an
      error answer (`HTTP_301`), as in PHP and .NET.
    - **Only http and https.** `file:` and `ftp:` are refused (a test).
    - **Every status is an answer.** The opener has no error processor, so a
      4xx or 5xx is read like any other answer.
    - **Proxies:** the environment's (`HTTPS_PROXY`, `NO_PROXY`), which is
      what `urllib` does; `proxies={}` for none, or a mapping. `ssl_context`
      replaces the default (a private authority).
    - **One connection per request.** `urllib` has no keep-alive; for pooling,
      HTTP/2 or a tuned proxy, use `HttpxTransport`.
    - **The timeout covers the whole attempt,** as decision 16 says. `urllib`'s
      own timeout is per socket operation, so the body is read with `read1`
      (one read at a time) and the time left is checked between reads. The
      socket's timeout is also moved to the time left, by reaching the
      socket under the response (`resp.fp.raw._sock`): a private attribute,
      so it is guarded, and where it is not found the check between reads
      still ends the attempt, up to one read late. Tests with a body that
      trickles one byte at a time check the whole-attempt rule.
    - **`User-Agent`:** `rewloy-python/0.1.0 python/3.13.1 [suffix]`, never
      `Python-urllib`.
20. **An optional `httpx` transport** (`rewloy.httpx_transport.HttpxTransport`,
    `pip install "rewloy[httpx]"`). It costs nothing to anyone who does not
    import it: the library does not, and the package has no dependency on it.
    - **What it adds:** a pool, keep-alive, HTTP/2 with `httpx.Client(http2=True)`,
      and `httpx`'s proxy and certificate settings.
    - **The same rules:** no redirects, the whole-attempt time, and a stream
      closed from another thread (it shuts the socket down, which `httpx`'s own
      `close` does not do under a blocked read).
    - **Tested** with the same stub server as the default one, for each of the
      transport tests; they skip when `httpx` is not installed.
21. **Times are seconds, as floats** (`timeout`, `idle_timeout`, `Retry-After`
    and the waits, as in PHP). `0` or `math.inf` is no limit. A per-call
    `timeout=None` means "the client's", which is the Python convention
    for "unset" and not the one for "no timeout" (use `0`).
22. **Errors.**
    - **Names:** `RewloyError`, `RateLimitError`, `RewloyConnectionError`
      and `RewloyTimeoutError` (the prefix, because `ConnectionError` and
      `TimeoutError` are builtins). The last extends the one before it.
    - **Fields:** `status`, `code`, `title`, `detail`, `details`, `docs`,
      `request_id`, `body`, `headers` and `operation`; `RateLimitError` has
      `retry_after` (whole seconds).
    - **`code` is a string,** as decision 6 says; `ERROR_TITLES` has each
      code's title.
    - **The cause** is `__cause__` (`raise … from`).
    - **Pickle and copy work:** a keyword-only constructor cannot be rebuilt
      from `args`, so `__reduce__` copies the fields (a test).
    - **Programming errors** are the builtins: `ValueError` for a wrong
      prefix, two credentials, an empty secret, an unknown operation or a
      missing path parameter; `TypeError` for a body `json` cannot write or a
      query value that is not a scalar. `WebhookSignatureError` is apart from
      `RewloyError`, as in Node.
23. **Deprecation warnings** are `warnings.warn(…, DeprecationWarning)`, once
    per operation per process, whatever the number of clients.
    - **The warning points at the caller's line** (the first frame outside
      the package, found by walking the stack). Python's default filter shows a
      `DeprecationWarning` only when it is attributed to `__main__`, so a
      warning attributed to the library would never be seen.
    - **`-W error`:** the exception would be raised from inside the call,
      after the server has acted, and the answer would be lost. The call
      returns, and the notice goes to the `rewloy` logger as a warning. This
      is PHP's and Node's decision about handlers that throw.
24. **`EventStream` is its own iterator,** written as a state machine, not a
    generator.
    - **Why:** a test found that a generator's frame holds the stream and the
      stream holds the generator, a cycle that kept the connection open after
      `break` until the garbage collector ran. As a plain object, `break`
      closes the connection at once in CPython (`__del__`), and `with` or
      `close()` anywhere else.
    - **`close()` is thread-safe** and wakes a blocked read: the default
      transport shuts the socket down first. Waits between reconnections are
      `threading.Event.wait`, which `close()` ends at once (unless the caller
      gave a `sleep`).
    - **State:** `last_event_id`, `retry` (seconds), `request_id` and `mode`.
      `ServerSentEvent.json()` parses `data`. Nothing is sent until the first
      event is asked for; a stream is iterated once.
    - **On the wire:** `Accept-Encoding: identity` and `Cache-Control:
      no-cache`, as an `EventSource` asks and so that no proxy holds events
      back (the same as .NET).
25. **On the wire:**
    - **The body** is `json.dumps` with UTF-8 as it is (no `\u` escapes),
      no spaces and `allow_nan=False`; `uuid.UUID`, `datetime`, `date` and
      `Enum` values are written as their string or value.
    - **The query:** RFC 3986 (`%20`), booleans as `true`/`false`, a list
      repeats its key, `None` leaves a parameter out, the same values as the
      body are accepted.
    - **Path values** are escaped as a whole (`/` too).
26. **A client is thread-safe** and meant to be shared: it holds no mutable
    state, the transport's opener is shared, and the set of operations already
    warned about is under a lock. A test runs eight threads on one client.
27. **`Page` and `ApiResponse` are frozen dataclasses,** not TypedDicts:
    generic TypedDicts need 3.11. A page is `page.data` and `page.meta`.
28. **Webhooks** (`verify_webhook(payload, header, secret, *, tolerance=300,
    now=None)`; `sign_webhook(payload, secret, *, timestamp=None)`):
    - **HMAC-SHA256 with `hmac.compare_digest`,** every pair of candidate and
      secret compared whether or not one matched already.
    - **The vectors** are the two fixed ones that Node, PHP and .NET pin, plus
      a signer written out again in the test from the platform's formula.
    - **A signed body that is not a JSON object** is refused (`payload`), as
      PHP does; a parsed `dict` as the payload is a `TypeError` and an empty
      secret a `ValueError`.
    - **`now`** is Unix seconds or a `datetime` (naive counts as UTC);
      `header` is a string or a list of strings.
    - **The result** is a `PassEvent` or `WebhookTestEvent` TypedDict, so that
      `event["type"] == "webhook.test"` narrows it for `mypy`, and a new type
      is a `default` branch. The names avoid a `Test` prefix, which `pytest`
      would take for a test class.

## Tests and CI

29. **Tests** are `pytest` on a stub server (`http.server` in a thread, one
    per test, 127.0.0.1): no network beyond the loopback, no credential. The
    default transport in them has `proxies={}`, so that a proxy in the
    environment cannot change a result. They cover construction, requests,
    retries, errors, paging, the SSE parser and streams (chunks of one byte, a
    silent connection, `close()` from another thread, a connection that
    breaks), webhooks, deprecations, both transports, the generator and the
    3.9 checks. One test per operation (237) calls each generated method
    against a stub that answers it as the API does, and checks the verb, the
    path, the headers and the way the answer is read. 445 tests, about 12
    seconds.
30. **`ci.yml`:** `actions/checkout@v7` and `actions/setup-python@v7` (the
    current majors), on Python 3.9 and 3.13. It installs `.[dev]`, runs `mypy`
    and `pytest`, then a `package` job builds the sdist and the wheel,
    installs the wheel in a clean virtual environment away from the checkout,
    imports it, and checks that `py.typed` and the licence are inside.
31. **`regenerate.yml`** is Node's decision 24, with `mypy` and `pytest` as its
    check, on Python 3.13, at 06:17 UTC (Node's runs at 05:23, PHP's at 05:41,
    .NET's at 05:59).

## 0.3.0 (API 1.3.2)

32. **The webhook event types are split, not widened.** The 1.3.0 events that
    are not about a card (`location.frozen`, `location.unfrozen`,
    `business.paused`, `business.resumed`) are a `BranchEvent` with its own
    `data` (`BranchEventData`: `card` and `customer_id` are `None`), and
    `WebhookEvent` is `PassEvent | BranchEvent | WebhookTestEvent`. A single
    type with every key optional would have kept old code compiling, but it
    would say a branch event has a `unit` and a `delta`. The cost is one
    visible change for a type checker (narrow on `event["type"]` before reading
    `event["data"]["unit"]`); nothing changes at run time, and the CHANGELOG
    lists it. `pass.extended` stays a `PassEvent` (a card event), with
    `PassExtendedData` for its `from` / `to` (`from` is a keyword, so that type
    is the functional form of `TypedDict`).
33. **No `lines` helper.** A receipt line is a plain `TypedDict`
    (`RecordSaleBodyLinesItem`, `PreviewSaleBodyLinesItem`, …); the API checks
    the totals, the library does not. The three line item types of
    `record_sale`, `preview_sale` and `preview_earn` are separate classes with
    the same keys, as the generator makes one class per place in the document.
34. **The live suite never freezes a branch.** Freezing needs a password, which
    a suite that runs on a key must not hold; `LOCATION_FROZEN` is tested
    against the stub only (`tests/live/TODO.md`).
