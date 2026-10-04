"""Generate src/rewloy/generated/ from the Rewloy OpenAPI document.

    python scripts/generate.py                  fetch the live document, keep it as
                                                openapi/openapi.json, write src/rewloy/generated/
    python scripts/generate.py --file <path>    generate from a saved document, e.g. the
                                                committed snapshot (reproducible builds)
    python scripts/generate.py --url <url>      fetch from another address

The document is checked (the generator refuses what it does not understand)
before anything is written; files that did not change are left alone. The
snapshot is written as the other Rewloy libraries write it (two-space JSON,
UTF-8 as it is, a final newline), so that the files can be compared with ``cmp``.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator import generate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIVE = "https://app.rewloy.com/v1/openapi.json"
SNAPSHOT = ROOT / "openapi" / "openapi.json"


def option(argv: List[str], name: str) -> Optional[str]:
    if name not in argv:
        return None
    i = argv.index(name)
    if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
        raise SystemExit(f"{name} needs a value")
    return argv[i + 1]


def put(path: Path, content: str) -> bool:
    """Writes when the content differs; returns whether it did."""
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return True


def whole_numbers(value: Any) -> Any:
    """JSON.stringify writes 1.0 as 1: do the same, so the snapshot matches the one the other libraries keep."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
        return int(value)
    if isinstance(value, list):
        return [whole_numbers(v) for v in value]
    if isinstance(value, dict):
        return {k: whole_numbers(v) for k, v in value.items()}
    return value


def snapshot_text(document: Any) -> str:
    return json.dumps(whole_numbers(document), indent=2, ensure_ascii=False) + "\n"


def main(argv: List[str]) -> int:
    file = option(argv, "--file")
    if file:
        document = json.loads(Path(file).read_text(encoding="utf-8"))
    else:
        url = option(argv, "--url") or LIVE
        request = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "rewloy-python-generator"})
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (the URL is the maintainer's)
            document = json.loads(response.read().decode("utf-8"))

    files = generate(document)
    changed: List[str] = []
    if not file and put(SNAPSHOT, snapshot_text(document)):
        changed.append(str(SNAPSHOT.relative_to(ROOT)))
    for f in files:
        if put(ROOT / f.path, f.content):
            changed.append(f.path)

    paths = document["paths"]
    count = sum(1 for item in paths.values() for m in item if m in ("get", "post", "put", "patch", "delete"))
    print(f"{count} operations; " + (f"changed: {', '.join(changed)}" if changed else "nothing changed"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
