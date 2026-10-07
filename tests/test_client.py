from __future__ import annotations

import json
import platform
import re
from typing import Any, Callable, Dict

import pytest

from rewloy import OPERATIONS, METHOD_NAMES, OPERATION_IDS, EventStream, Headers, Page, RateLimit, Rewloy, VERSION, parse_rate_limit

from .helpers import HOLDER, KEY, LOCATION, MERCHANT, SERIAL, STAFF, Ctx, Stub, loose, make_client

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_takes_one_credential_of_the_right_kind() -> None:
    assert Rewloy(api_key=KEY).credential == "key"
    assert Rewloy(staff_session=STAFF, merchant=MERCHANT).merchant == MERCHANT
    assert Rewloy(holder_session=HOLDER).credential == "holder"
    assert Rewloy().credential is None
    with pytest.raises(ValueError, match='api_key must start with "rwk_"'):
        Rewloy(api_key=STAFF)
    with pytest.raises(ValueError, match='staff_session must start with "rws_"'):
        Rewloy(staff_session=KEY)
    with pytest.raises(ValueError, match='holder_session must start with "rwh_"'):
        Rewloy(holder_session="abc")
    with pytest.raises(ValueError, match="one credential"):
        Rewloy(api_key=KEY, holder_session=HOLDER)
    with pytest.raises(ValueError, match="merchant"):
        Rewloy(api_key=KEY, merchant=MERCHANT)
    with pytest.raises(TypeError, match="must be a string"):
        Rewloy(api_key=b"rwk_x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="http"):
        Rewloy(base_url="file:///etc/passwd")
    with pytest.raises(ValueError, match="negative"):
        Rewloy(timeout=-1)


def test_has_defaults_and_never_shows_the_credential() -> None:
    c = Rewloy(api_key=KEY)
    assert c.base_url == "https://app.rewloy.com"
    assert c.timeout == 60.0
    assert c.max_retries == 2
    assert Rewloy(base_url="http://localhost:3000/").base_url == "http://localhost:3000"
    assert KEY not in repr(c)
    assert KEY not in str(vars(c).get("_user_agent"))
    assert "rwk_" not in repr(c)


def test_has_a_method_for_every_operation_and_a_mapping_from_the_operation_id() -> None:
    c = Rewloy()
    # The snapshot is regenerated daily: the count follows it, not a constant.
    assert len(OPERATIONS) == len(set(METHOD_NAMES.values())) > 237
    for operation_id, meta in OPERATIONS.items():
        assert callable(getattr(c, meta.method_name)), operation_id
        assert METHOD_NAMES[operation_id] == meta.method_name
        assert OPERATION_IDS[meta.method_name] == operation_id
    assert METHOD_NAMES["passAction"] == "pass_action"
    assert METHOD_NAMES["setTeam2fa"] == "set_team2fa"


def test_says_the_version_it_is() -> None:
    import rewloy

    assert rewloy.__version__ == VERSION == "0.3.0"


@pytest.fixture
def api(stub: Callable[[Callable[[Ctx], None]], Stub]) -> Stub:
    def handle(c: Ctx) -> None:
        url = c.req.url
        if url.startswith("/v1/customers"):
            c.json(200, {"data": [{"personId": "p1"}], "meta": {"page": 1, "pageSize": 50, "total": 1}})
        elif url.startswith("/v1/developers/keys/"):
            c.raw(204, headers={"X-Request-Id": "r-204"})
        elif url.endswith("/map.png"):
            c.raw(200, bytes([0x89, 0x50, 0x4E, 0x47]), {"Content-Type": "image/png"})
        elif url == "/v1/openapi.json":
            c.json(200, {"openapi": "3.1.0", "paths": {}})
        elif url == "/v1/campaigns" and c.req.method == "POST":
            c.json(201, {"data": {"id": "c1"}}, {"Idempotent-Replayed": "true", "Rewloy-Mode": "test", "X-Request-Id": "r-campaign", "RateLimit-Limit": "120", "RateLimit-Remaining": "117", "RateLimit-Reset": "41"})
        elif url.endswith("/actions/reverse"):
            c.json(200, {"data": {"type": "giftcard", "undone": "spend", "restored": 5000, "balance": 5000, "uses": None, "usesLeft": None, "status": "active", "reopened": False, "duplicate": False, "rewardReady": False, "rewardsReady": 0}})
        elif url.endswith("/actions") and c.req.method == "POST":
            c.json(200, {"data": {"status": "active", "duplicate": False, "uses": 3, "usesLeft": 2}})
        else:
            c.json(200, {"data": {"ok": True}})

    return stub(handle)


def test_sends_the_api_key_the_client_and_no_merchant(api: Stub) -> None:
    c = make_client(api, user_agent="KasaPOS/4.2")
    assert loose(c.get_pass(SERIAL)) == {"ok": True}
    r = api.last
    assert r.method == "GET"
    assert r.url == f"/v1/passes/{SERIAL}"
    assert r.headers["authorization"] == f"Bearer {KEY}"
    assert r.headers["user-agent"] == f"rewloy-python/{VERSION} python/{platform.python_version()} KasaPOS/4.2"
    assert r.headers["accept"] == "application/json"
    for absent in ("rewloy-merchant", "content-type", "idempotency-key", "last-event-id"):
        assert absent not in r.headers


def test_sends_a_staff_session_with_its_merchant_overridable_per_call(api: Stub) -> None:
    c = make_client(api, staff_session=STAFF, merchant=MERCHANT)
    c.list_programs()
    assert api.last.headers["authorization"] == f"Bearer {STAFF}"
    assert api.last.headers["rewloy-merchant"] == MERCHANT
    c.list_programs(merchant="other-merchant")
    assert api.last.headers["rewloy-merchant"] == "other-merchant"
    # An operation without the header never gets it.
    c.login(body={"email": "a@b.co", "password": "x"})
    assert "rewloy-merchant" not in api.last.headers


def test_sends_a_holder_session(api: Stub) -> None:
    c = make_client(api, holder_session=HOLDER)
    c.holder_cards(query={"merchant": "kahve-dukkani"})
    assert api.last.headers["authorization"] == f"Bearer {HOLDER}"
    assert api.last.url == "/v1/holder/cards?merchant=kahve-dukkani"


def test_calls_an_operation_that_does_not_take_this_credential_but_works_without_one_without_it(api: Stub) -> None:
    key = make_client(api)
    key.login(body={"email": "a@b.co", "password": "x"})
    assert "authorization" not in api.last.headers
    key.holder_provider_nonce(body={"provider": "google"})
    assert "authorization" not in api.last.headers
    holder = make_client(api, holder_session=HOLDER)
    holder.holder_provider_nonce(body={"provider": "google"})
    assert api.last.headers["authorization"] == f"Bearer {HOLDER}"
    holder.public_program(LOCATION)
    assert api.last.headers["authorization"] == f"Bearer {HOLDER}"
    # Not public: the credential goes, and the API answers whether it may.
    key.holder_cards()
    assert api.last.headers["authorization"] == f"Bearer {KEY}"
    make_client(api, api_key=None).holder_cards()
    assert "authorization" not in api.last.headers


def test_sends_json_bodies_and_empty_object_when_an_all_optional_body_is_left_out(api: Stub) -> None:
    c = make_client(api)
    c.issue_pass(body={"programId": LOCATION, "email": "ayşe@example.com", "kvkkConsent": True})
    assert api.last.method == "POST"
    assert api.last.headers["content-type"] == "application/json"
    assert api.last.json() == {"programId": LOCATION, "email": "ayşe@example.com", "kvkkConsent": True}
    # UTF-8 as it is, no escapes, no spaces.
    assert api.last.text == '{"programId":"%s","email":"ayşe@example.com","kvkkConsent":true}' % LOCATION
    c.update_program(LOCATION)
    assert api.last.method == "PATCH"
    assert api.last.text == "{}"
    c.close_batch(LOCATION)
    assert api.last.text == ""
    assert "content-type" not in api.last.headers


def test_a_body_that_is_not_json_is_the_callers_mistake() -> None:
    c = make_client()
    with pytest.raises(TypeError, match="not JSON serializable"):
        c.create_segment(body={"name": "x", "rule": {"minVisits": object()}})  # type: ignore[typeddict-item]
    with pytest.raises(ValueError):
        c.create_segment(body={"name": "x", "rule": {"minVisits": float("nan")}})  # type: ignore[typeddict-item]


def test_generates_an_idempotency_key_where_it_is_optional_and_sends_the_given_one(api: Stub) -> None:
    c = make_client(api)
    c.issue_pass(body={"programId": "p1", "name": "Ayşe"})
    assert UUID.match(api.last.headers["idempotency-key"])
    c.issue_pass(body={"programId": "p1"}, idempotency_key="kayit-000123")
    assert api.last.headers["idempotency-key"] == "kayit-000123"


def test_requires_the_idempotency_key_where_the_api_does_and_never_makes_one_up(api: Stub) -> None:
    c = make_client(api)
    body = {"action": "earn-stamps", "locationId": LOCATION, "count": 2}
    with pytest.raises(TypeError, match="idempotency_key"):
        c.pass_action(SERIAL, body=body)  # type: ignore[call-arg,arg-type]
    with pytest.raises(ValueError, match="pass_action needs idempotency_key|passAction needs idempotency_key"):
        c.request("passAction", path={"serial": SERIAL}, body=body)
    with pytest.raises(ValueError, match="sendCampaign needs idempotency_key"):
        c.request("sendCampaign", body={"body": "Merhaba"})
    with pytest.raises(ValueError, match="needs idempotency_key"):
        c.pass_action(SERIAL, body=body, idempotency_key=None)  # type: ignore[arg-type]
    assert api.requests == []  # nothing was sent
    c.pass_action(SERIAL, body=body, idempotency_key="fis-000123")  # type: ignore[arg-type]
    assert api.last.headers["idempotency-key"] == "fis-000123"


def test_refuses_an_idempotency_key_that_cannot_be_a_header_value_before_sending(api: Stub) -> None:
    c = make_client(api)
    body = {"action": "earn-stamps", "locationId": LOCATION}
    for bad in ["fiş-000123-ğ", "with space 123", "kısa", "a" * 65, "", "tab\there-123", "satir\nsonu-123", "valid-key-1\n"]:
        with pytest.raises(ValueError, match="Idempotency-Key yalnız ASCII karakterler içerebilir"):
            c.pass_action(SERIAL, body=body, idempotency_key=bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="printable ASCII"):
        c.issue_pass(body={"programId": "p1"}, idempotency_key="çiçek-çiçek-1")
    with pytest.raises(ValueError, match="Idempotency-Key yalnız ASCII"):
        c.request("passAction", path={"serial": SERIAL}, body=body, idempotency_key="fiş-000123")
    assert api.requests == []  # nothing was sent
    for good in ["12345678", "a" * 64, "kasa3-z0187-fis0042", "!~#$%&()*+,-./:;<=>?@[]^_{|}"]:
        c.pass_action(SERIAL, body=body, idempotency_key=good)  # type: ignore[arg-type]
        assert api.last.headers["idempotency-key"] == good


def test_accepts_the_base_url_with_or_without_v1(api: Stub) -> None:
    for suffix in ["", "/", "/v1", "/v1/", "//v1//"]:
        c = make_client(api, base_url=api.url + suffix)
        assert c.base_url == api.url, suffix
        c.get_pass(SERIAL)
        assert api.last.url == f"/v1/passes/{SERIAL}", suffix
    assert Rewloy(base_url="https://app.rewloy.com/v1").base_url == "https://app.rewloy.com"
    assert Rewloy(base_url="https://app.rewloy.com/v1/").base_url == "https://app.rewloy.com"
    assert Rewloy(base_url="https://proxy.example.com/rewloy/v1").base_url == "https://proxy.example.com/rewloy"
    assert Rewloy(base_url="https://proxy.example.com/rewloy").base_url == "https://proxy.example.com/rewloy"


def test_encodes_path_parameters_and_the_query(api: Stub) -> None:
    c = make_client(api)
    c.get_pass("AB/CD EF")
    assert api.last.url == "/v1/passes/AB%2FCD%20EF"
    c.list_customers(query={"q": "Ayşe Yılmaz", "blocked": False, "page": 2, "limit": 10})
    assert api.last.url == "/v1/customers?q=Ay%C5%9Fe%20Y%C4%B1lmaz&blocked=false&page=2&limit=10"
    # A list repeats its key, None leaves a parameter out.
    c.request("listCustomers", query={"status": None, "q": ["a", "b"], "limit": 5})
    assert api.last.url == "/v1/customers?q=a&q=b&limit=5"
    with pytest.raises(ValueError, match=r"getPass needs path\['serial'\]"):
        c.request("getPass")
    with pytest.raises(ValueError, match="needs path"):
        c.get_pass("")
    with pytest.raises(TypeError, match="must be a string, number or boolean"):
        c.request("listCustomers", query={"q": {"a": 1}})


def test_reads_each_kind_of_answer(api: Stub) -> None:
    c = make_client(api, staff_session=STAFF)
    page = c.list_customers()
    assert isinstance(page, Page)
    assert loose(page.data) == [{"personId": "p1"}]
    assert page.meta == {"page": 1, "pageSize": 50, "total": 1}
    c.revoke_api_key(LOCATION)
    png = c.location_map(LOCATION)
    assert png == bytes([0x89, 0x50, 0x4E, 0x47])
    assert c.openapi() == {"openapi": "3.1.0", "paths": {}}


def test_gives_the_whole_answer_through_request(api: Stub) -> None:
    c = make_client(api)
    res = c.request("sendCampaign", body={"body": "Bu hafta kahveler 2 damga!"}, idempotency_key="kampanya-2026-10-03")
    assert res.status == 201
    assert res.data == {"id": "c1"}
    assert res.meta is None
    assert res.request_id == "r-campaign"
    assert res.mode == "test"
    assert res.replayed is True
    assert res.rate_limit == RateLimit(limit=120, remaining=117, reset=41)
    assert isinstance(res.headers, Headers)
    assert res.headers["Rewloy-Mode"] == "test"  # case-insensitive
    assert "rewloy-mode" in res.headers
    # By method name too.
    again = c.request("send_campaign", body={"body": "x"}, idempotency_key="kampanya-0002")
    assert again.status == 201
    listing = c.request("listCustomers")
    assert listing.meta == {"page": 1, "pageSize": 50, "total": 1}
    assert listing.mode is None
    assert listing.replayed is False
    assert listing.rate_limit is None, "no RateLimit headers, no rate_limit"
    assert listing.data == [{"personId": "p1"}]


def test_reverses_a_till_action_without_an_idempotency_key_and_narrows_pass_actions_two_answers(api: Stub) -> None:
    c = make_client(api)
    back = c.reverse_action(SERIAL, body={"actionKey": "kasa3-z0187-fis0042", "locationId": LOCATION})
    assert back["undone"] == "spend"
    assert back["restored"] == 5000
    assert api.last.method == "POST"
    assert api.last.url == f"/v1/passes/{SERIAL}/actions/reverse"
    assert "idempotency-key" not in {k.lower() for k in api.last.headers}, "the API does not ask for one"
    assert json.loads(api.last.body) == {"actionKey": "kasa3-z0187-fis0042", "locationId": LOCATION}
    assert METHOD_NAMES["reverseAction"] == "reverse_action"

    use = c.pass_action(SERIAL, body={"action": "use", "locationId": LOCATION}, idempotency_key="kasa3-z0187-fis0043")
    # A union of two TypedDicts, not Any: `uses` exists only on the coupon / discount-card answer.
    if "uses" in use:
        assert use["usesLeft"] == 2  # mypy: narrowed to the coupon answer
    else:
        assert use["balance"] is not None
    assert "balance" not in use


def test_reads_the_rate_limit_headers() -> None:
    assert parse_rate_limit(Headers([("RateLimit-Limit", "60"), ("RateLimit-Remaining", "0"), ("RateLimit-Reset", "9")])) == RateLimit(60, 0, 9)
    assert parse_rate_limit(Headers([("RateLimit-Limit", "60")])) is None
    assert parse_rate_limit(Headers([("RateLimit-Limit", "x"), ("RateLimit-Remaining", "0"), ("RateLimit-Reset", "9")])) is None
    assert parse_rate_limit(None) is None


def test_opens_streams_through_their_methods_not_request(api: Stub) -> None:
    c = make_client(api)
    stream = c.live_feed(reconnect=False)
    assert isinstance(stream, EventStream)
    stream.close()
    assert len(api.requests) == 0  # nothing is sent until the first event is asked for
    with pytest.raises(ValueError, match="liveFeed is a stream"):
        c.request("liveFeed")
    with pytest.raises(ValueError, match="not a paged list"):
        c.paginate("getPass")  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="unknown operation"):
        c.request("noSuchOperation")
    with pytest.raises(ValueError, match="not a stream"):
        c.stream("getPass")


def test_uses_a_transport_you_give_it() -> None:
    from rewloy import HttpRequest, HttpResponse

    seen: Dict[str, Any] = {}

    class Fake:
        def send(self, request: HttpRequest) -> HttpResponse:
            seen["request"] = request
            return HttpResponse(200, "OK", Headers([("Content-Type", "application/json")]), b'{"data":{"serial":"%s"}}' % SERIAL.encode())

        def open_stream(self, request: HttpRequest) -> Any:
            raise AssertionError("not a stream")

        def close(self) -> None:
            seen["closed"] = True

    c = Rewloy(api_key=KEY, base_url="https://example.invalid", transport=Fake())
    assert loose(c.get_pass(SERIAL)) == {"serial": SERIAL}
    assert seen["request"].url == f"https://example.invalid/v1/passes/{SERIAL}"
    assert seen["request"].timeout == 60.0
    c.close()
    assert "closed" not in seen  # a transport you passed in is yours to close


def test_is_a_context_manager_that_closes_its_own_transport() -> None:
    with Rewloy(api_key=KEY) as c:
        assert c.credential == "key"


def test_a_timeout_of_zero_or_infinity_means_none() -> None:
    from rewloy import HttpRequest, HttpResponse

    timeouts = []

    class Fake:
        def send(self, request: HttpRequest) -> HttpResponse:
            timeouts.append(request.timeout)
            return HttpResponse(200, "OK", Headers(), b'{"data":{}}')

        def open_stream(self, request: HttpRequest) -> Any:
            raise AssertionError

        def close(self) -> None:
            pass

    c = Rewloy(api_key=KEY, transport=Fake(), timeout=0)
    c.get_pass(SERIAL)
    c.get_pass(SERIAL, timeout=float("inf"))
    c.get_pass(SERIAL, timeout=5)
    assert timeouts == [None, None, 5]


def test_importing_the_library_does_not_load_the_types() -> None:
    """The types module is big (a thousand TypedDicts): only annotations name it, so ``import rewloy`` skips it."""
    import subprocess
    import sys

    code = "import sys, rewloy; rewloy.Rewloy().get_pass; assert 'rewloy.generated.types' not in sys.modules; import rewloy.types; assert 'rewloy.generated.types' in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


def test_one_client_serves_many_threads(api: Stub) -> None:
    import threading

    c = make_client(api)
    errors = []

    def work() -> None:
        try:
            for _ in range(10):
                assert loose(c.get_pass(SERIAL)) == {"ok": True}
        except BaseException as err:  # noqa: BLE001
            errors.append(err)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(api.requests) == 80


def test_the_version_is_the_changelogs_latest_heading() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## (\d+\.\d+\.\d+)\b", text, re.M)
    assert versions and versions[0] == VERSION
