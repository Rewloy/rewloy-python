"""Live integration tests: the library against a running Rewloy DEV server.

Not part of the normal run (deselected). ``pytest -m live`` selects them; they run only with ``REWLOY_BASE_URL`` +
``REWLOY_API_KEY`` set, otherwise every one is skipped with the reason. Before anything else the session:

1. asks ``GET /v1/meta`` (no credentials) and stops unless it says ``"environment": "dev"``;
2. refuses any key that is not a test-mode key (``rwk_test_``);
3. checks that the first authenticated answer says ``Rewloy-Mode: test``.

A refusal ends the whole run with a non-zero exit code (``pytest.exit``): this suite must never touch a live
business. Everything goes through the library (``rewloy.Rewloy``), never raw HTTP.
"""
from __future__ import annotations

import os
import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import pytest

from rewloy import Rewloy, RewloyError

ENV_URL = "REWLOY_BASE_URL"
ENV_KEY = "REWLOY_API_KEY"
ENV_STAFF = "REWLOY_STAFF_TOKEN"  # optional: a team session (rws_...) for resetTestEnvironment, which keys may not call
ENV_MERCHANT = "REWLOY_MERCHANT_ID"  # optional: the business the team session works for, if it has several

HERE = os.path.dirname(os.path.abspath(__file__))


def _env_missing() -> Optional[str]:
    """None when the environment is set, else the skip reason."""
    if not os.environ.get(ENV_URL) or not os.environ.get(ENV_KEY):
        return f"set {ENV_URL} and {ENV_KEY} (a DEV server and a rwk_test_ key) to run the live tests"
    return None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: runs against a Rewloy DEV server (see tests/live/conftest.py); needs -m live")


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """A normal run does not even list the live tests; `-m live` selects them and, without the environment, skips them."""
    asked = "live" in (config.getoption("markexpr") or "")
    why = _env_missing()
    keep: List[pytest.Item] = []
    dropped: List[pytest.Item] = []
    for item in items:
        if not str(item.fspath).startswith(HERE):
            keep.append(item)
            continue
        item.add_marker(pytest.mark.live)
        if not asked:
            dropped.append(item)
            continue
        if why is not None:
            item.add_marker(pytest.mark.skip(reason=why))
        keep.append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep


# ---------------------------------------------------------------------------------------------------- the world


@dataclass
class World:
    """What the run created and what later areas need from earlier ones."""

    run: str
    client: Any  # a Rewloy; Any because these tests read the JSON as it is, not through the TypedDicts
    base_url: str
    staff: Optional[Any]
    location_id: str = ""
    currency: str = "TRY"
    stamp_program: Dict[str, Any] = field(default_factory=dict)
    gift_program: Dict[str, Any] = field(default_factory=dict)
    programs: List[Dict[str, Any]] = field(default_factory=list)  # every program this run created
    batch_ids: List[str] = field(default_factory=list)
    webhook_ids: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)  # serials and keys passed between areas
    notes: List[str] = field(default_factory=list)  # cleanup report, printed in the summary

    def email(self, tag: str) -> str:
        address = f"livepy-{self.run}-{tag}@example.test"
        self.emails.append(address)
        return address

    def key(self, tag: str) -> str:
        """An Idempotency-Key: 8 to 64 visible ASCII characters, unique per run."""
        return f"livepy-{self.run}-{tag}"

    def new_program(self, body: Dict[str, Any]) -> Dict[str, Any]:
        program: Dict[str, Any] = dict(self.client.create_program(body=body))
        self.programs.append(program)
        return program


def _stop(message: str) -> None:
    pytest.exit(f"LIVE TESTS REFUSED TO RUN: {message}", returncode=3)


def _guard(base_url: str, key: str, staff_token: Optional[str]) -> None:
    # 1. never against anything but a dev server: ask it, without credentials
    try:
        with Rewloy(base_url=base_url, max_retries=0, timeout=15) as anonymous:
            meta = anonymous.get_meta()
    except RewloyError as err:
        _stop(f"GET /v1/meta on {base_url} failed ({err.code}); cannot tell which environment this is")
    environment = meta.get("environment") if isinstance(meta, dict) else None
    if environment != "dev":
        _stop(f'{base_url} says environment={environment!r}, not "dev"; these tests only run against a dev server')
    # 2. only a test-mode key
    if not key.startswith("rwk_test_"):
        _stop(f"{ENV_KEY} is not a test-mode key (rwk_test_...); live keys are never used")
    if staff_token is not None and not staff_token.startswith("rws_"):
        _stop(f"{ENV_STAFF} is not a team session token (rws_...)")


@pytest.fixture(scope="session")
def world() -> Iterator[World]:
    base_url = os.environ[ENV_URL]
    key = os.environ[ENV_KEY]
    staff_token = os.environ.get(ENV_STAFF) or None
    _guard(base_url, key, staff_token)

    client = Rewloy(api_key=key, base_url=base_url)
    # 3. the first authenticated answer must say test mode
    answer = client.request("getBusiness")
    if answer.mode != "test":
        client.close()
        _stop(f"the key works on a business in mode {answer.mode!r}, not 'test'")
    staff: Optional[Rewloy] = None
    if staff_token:
        merchant = os.environ.get(ENV_MERCHANT) or None
        staff = Rewloy(staff_session=staff_token, base_url=base_url, merchant=merchant)

    w = World(run=uuid.uuid4().hex[:8], client=client, base_url=base_url, staff=staff)
    _world_ref.append(w)
    try:
        yield w
    finally:
        _cleanup(w)
        client.close()
        if staff is not None:
            staff.close()


def _cleanup(w: World) -> None:
    """Whatever the areas did not remove themselves. Never raises."""
    c = w.client
    for webhook_id in w.webhook_ids:
        try:
            c.delete_webhook(webhook_id)
            w.notes.append(f"webhook {webhook_id[:8]} deleted")
        except RewloyError:
            pass  # already gone
    for batch_id in w.batch_ids:
        try:
            c.close_batch(batch_id)
        except RewloyError:
            pass
    deleted = archived = left = 0
    for program in w.programs:
        try:
            c.delete_program(program["id"], query={"confirmName": program["name"]})
            deleted += 1
            continue
        except RewloyError:
            pass  # cards exist (no reset ran): archive instead
        try:
            c.archive_program(program["id"])
            archived += 1
        except RewloyError:
            left += 1
    w.notes.append(f"programs: {deleted} deleted, {archived} archived (they hold cards), {left} left")


# ---------------------------------------------------------------------------------------------------- the summary

_AREA = re.compile(r"test_live_\d+_([a-z_]+)\.py")
_results: "OrderedDict[str, Dict[str, int]]" = OrderedDict()


def _area(nodeid: str) -> str:
    m = _AREA.search(nodeid)
    return m.group(1) if m else "other"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if "tests/live/" not in report.nodeid:
        return
    if report.when == "call":
        outcome = report.outcome
    elif report.outcome != "passed":
        outcome = "failed" if report.outcome == "failed" else "skipped"  # a setup error counts as failed
    else:
        return
    row = _results.setdefault(_area(report.nodeid), {"passed": 0, "failed": 0, "skipped": 0})
    row[outcome] += 1


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    if not _results:
        return
    tr = terminalreporter
    tr.write_sep("=", "live tests: summary per area")
    for area, row in _results.items():
        verdict = "FAIL" if row["failed"] else ("skip" if not row["passed"] else "ok")
        tr.write_line(f"  {verdict:<4}  {area:<14} passed {row['passed']:>2}   failed {row['failed']:>2}   skipped {row['skipped']:>2}")
    total = {k: sum(r[k] for r in _results.values()) for k in ("passed", "failed", "skipped")}
    tr.write_line(f"  ----  {'total':<14} passed {total['passed']:>2}   failed {total['failed']:>2}   skipped {total['skipped']:>2}")
    for note in _notes():
        tr.write_line(f"  cleanup: {note}")


_world_ref: List[World] = []


def _notes() -> List[str]:
    return _world_ref[0].notes if _world_ref else []
