from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Callable, List

import pytest

from rewloy import BranchEvent, PassExtendedData, WebhookSignatureError, sign_webhook, verify_webhook

SECRET = "whsec_dGVzdC1zZWNyZXQtZm9yLXJld2xveS1ub2RlLXRlc3Rz"
T = 1790000000
BODY = '{"id":"0192f7c1-8b2e-7a31-9c1d-2e4f5a6b7c8d","type":"pass.activity","created_at":"2026-10-03T12:00:00.000Z","data":{"kind":"earn","card":"ABCD-EFGH-JKLM","program_id":"0192f7c1-0000-7000-8000-000000000002","location_id":"0192f7c1-0000-7000-8000-000000000003","customer_id":"0192f7c1-0000-7000-8000-000000000004","unit":"stamp","delta":2}}'
#: Computed once with the platform's formula; the same two vectors the Node, PHP and .NET libraries pin. They
#: guard against both sides changing together.
FIXED = "t=1790000000,v1=b17b337b887316b1e0e19c3f16bdc4936c03e93d16fbec3da121aacc0ec1eda7"
TEST_BODY = '{"type":"webhook.test","created_at":"2026-10-03T12:00:00.000Z","data":{"message":"Rewloy webhook testi — ğüşıöç"}}'
TEST_FIXED = "t=1790000000,v1=b06a92a7fb131aed835f2564fdf06a93461e0edb9216b4464598812f47704b1e"


def server_sign(secret: str, body: str, t: int) -> str:
    """The way the platform signs a delivery (its src/modules/webhooks/service.ts, ``sign``), written out again here,
    not imported: HMAC-SHA256 with the whole ``whsec_…`` secret as the key over ``"<t>.<body>"``."""
    digest = hmac.new(secret.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


def refused(reason: str) -> Callable[[BaseException], bool]:
    def check(err: BaseException) -> bool:
        return isinstance(err, WebhookSignatureError) and err.reason == reason

    return check


def test_the_vectors_are_what_the_platform_formula_gives() -> None:
    assert server_sign(SECRET, BODY, T) == FIXED
    assert server_sign(SECRET, TEST_BODY, T) == TEST_FIXED


def test_accepts_what_the_platform_signs_as_a_string_or_as_bytes() -> None:
    for payload in (BODY, BODY.encode(), bytearray(BODY.encode()), memoryview(BODY.encode())):
        event = verify_webhook(payload, FIXED, SECRET, now=T + 10)
        assert event["type"] == "pass.activity"
        assert event["id"] == "0192f7c1-8b2e-7a31-9c1d-2e4f5a6b7c8d"
        assert event["data"]["card"] == "ABCD-EFGH-JKLM"
    test = verify_webhook(TEST_BODY.encode("utf-8"), TEST_FIXED, SECRET, now=datetime.fromtimestamp(T, tz=timezone.utc))
    assert test == {"type": "webhook.test", "created_at": "2026-10-03T12:00:00.000Z", "data": {"message": "Rewloy webhook testi — ğüşıöç"}}


def test_accepts_a_header_split_into_several_values_and_other_entries_around_v1() -> None:
    v1 = "v1=b17b337b887316b1e0e19c3f16bdc4936c03e93d16fbec3da121aacc0ec1eda7"
    assert verify_webhook(BODY, ["t=1790000000", v1], SECRET, now=T)["type"] == "pass.activity"
    assert verify_webhook(BODY, f" v0=abc, {FIXED.replace(',', ' , ')} ", SECRET, now=T)["type"] == "pass.activity"


def test_accepts_any_of_several_v1_signatures_and_any_of_several_secrets() -> None:
    other = server_sign("whsec_other", BODY, T).split(",")[1]
    assert verify_webhook(BODY, f"{FIXED},{other}", SECRET, now=T)["type"] == "pass.activity"
    assert verify_webhook(BODY, f"t={T},{other},{FIXED.split(',')[1]}", SECRET, now=T)["type"] == "pass.activity"
    assert verify_webhook(BODY, FIXED, ["whsec_new", SECRET], now=T)["type"] == "pass.activity"


def test_refuses_a_changed_body_the_wrong_secret_and_a_v1_for_another_time() -> None:
    for payload, header, secret in (
        (BODY.replace('"delta":2', '"delta":20'), FIXED, SECRET),
        (BODY + "\n", FIXED, SECRET),
        (BODY, FIXED, "whsec_wrong"),
        (BODY, FIXED.replace("t=1790000000", "t=1790000001"), SECRET),
        # The prefix is part of the key.
        (BODY, FIXED, SECRET[len("whsec_"):]),
    ):
        with pytest.raises(WebhookSignatureError) as info:
            verify_webhook(payload, header, secret, now=T)
        assert info.value.reason == "mismatch"


def test_refuses_a_time_outside_the_tolerance_either_way() -> None:
    assert verify_webhook(BODY, FIXED, SECRET, now=T + 300)["type"] == "pass.activity"
    assert verify_webhook(BODY, FIXED, SECRET, now=T - 300)["type"] == "pass.activity"
    for now in (T + 301, T - 301):
        with pytest.raises(WebhookSignatureError) as info:
            verify_webhook(BODY, FIXED, SECRET, now=now)
        assert info.value.reason == "expired"
    assert verify_webhook(BODY, FIXED, SECRET, now=T + 3600, tolerance=3600)["type"] == "pass.activity"
    # Real time: a 2026 signature is long expired.
    with pytest.raises(WebhookSignatureError) as info:
        verify_webhook(BODY, "t=1000,v1=" + "a" * 64, SECRET)
    assert info.value.reason == "expired"


def test_a_naive_datetime_counts_as_utc() -> None:
    assert verify_webhook(BODY, FIXED, SECRET, now=datetime(2026, 9, 21, 14, 13, 20))["type"] == "pass.activity"  # 1790000000


def test_refuses_a_missing_or_malformed_header() -> None:
    missing: List[Any] = [None, "", "  ", []]
    for header in missing:
        with pytest.raises(WebhookSignatureError) as info:
            verify_webhook(BODY, header, SECRET, now=T)
        assert info.value.reason == "missing"
    for header in (
        "v1=" + "a" * 64, "t=1790000000", "t=abc,v1=" + "a" * 64, "t=1790000000,v1=xyz", "t=1790000000,v1=" + "a" * 63,
        "garbage", "t=١٧٩٠٠٠٠٠٠٠,v1=" + "a" * 64,  # Arabic-Indic digits are not digits here
    ):
        with pytest.raises(WebhookSignatureError) as info:
            verify_webhook(BODY, header, SECRET, now=T)
        assert info.value.reason == "malformed", header


def test_refuses_a_signed_body_that_is_not_a_json_object() -> None:
    for body in ("not json", "[1,2]", '"text"', "null", b"\xff\xfe"):
        raw = body if isinstance(body, bytes) else body.encode()
        header = f"t={T},v1=" + hmac.new(SECRET.encode(), f"{T}.".encode() + raw, hashlib.sha256).hexdigest()
        with pytest.raises(WebhookSignatureError) as info:
            verify_webhook(raw, header, SECRET, now=T)
        assert info.value.reason == "payload"


def test_a_parsed_object_as_the_payload_and_an_empty_secret_are_programming_errors() -> None:
    parsed: Any = json.loads(BODY)
    with pytest.raises(TypeError, match="raw body"):
        verify_webhook(parsed, FIXED, SECRET, now=T)
    for secret in ("", [], [""]):
        with pytest.raises(ValueError, match="empty"):
            verify_webhook(BODY, FIXED, secret, now=T)


def test_the_event_is_typed_for_a_default_branch() -> None:
    event = verify_webhook(BODY, FIXED, SECRET, now=T)
    if event["type"] == "pass.activity":
        assert event["data"]["unit"] == "stamp"
    else:
        pytest.fail("a card activity")


def test_sign_webhook_signs_as_the_platform_does_for_testing_your_own_handler() -> None:
    assert sign_webhook(BODY, SECRET, timestamp=T) == FIXED
    assert sign_webhook(TEST_BODY.encode(), SECRET, timestamp=T) == TEST_FIXED
    header = sign_webhook(BODY, SECRET)
    assert verify_webhook(BODY, header, SECRET)["type"] == "pass.activity"


def test_the_comparison_is_constant_time_by_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    other = server_sign("whsec_other", BODY, T).split(",")[1]
    # Two secrets times two candidates: every pair is compared even though the first one matches.
    verify_webhook(BODY, f"{FIXED},{other}", [SECRET, "whsec_other"], now=T)
    assert len(calls) == 4


def test_the_1_3_0_events_are_typed_and_verify() -> None:
    extended = '{"id":"e1","type":"pass.extended","created_at":"2026-10-07T09:00:00.000Z","data":{"kind":"expiry_extended","card":"ABCD-EFGH-JKLM","reason":"branch_frozen","from":"2026-12-31T00:00:00.000Z","to":"2027-01-14T00:00:00.000Z"}}'
    frozen = '{"id":"e2","type":"location.frozen","created_at":"2026-10-07T09:00:00.000Z","data":{"kind":"location_frozen","card":null,"customer_id":null,"location_id":"l1","reason":"renovation","startsOn":"2026-10-08","reopensOn":null}}'
    a = verify_webhook(extended, sign_webhook(extended, SECRET, timestamp=T), SECRET, now=T)
    b = verify_webhook(frozen, sign_webhook(frozen, SECRET, timestamp=T), SECRET, now=T)
    assert a["type"] == "pass.extended"
    assert b["type"] == "location.frozen"
    if b["type"] == "location.frozen":
        branch: BranchEvent = b
        assert branch["data"]["startsOn"] == "2026-10-08"
        assert branch["data"].get("reopensOn") is None
    moved: PassExtendedData = a["data"]  # type: ignore[assignment]
    assert moved["from"] == "2026-12-31T00:00:00.000Z"
