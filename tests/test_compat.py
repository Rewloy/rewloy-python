"""The library supports Python 3.9 and later; most of CI runs on a newer one. These checks keep 3.10+ syntax out of the
source on any interpreter (the 3.9 job runs the tests for real)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterator, List

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(p for d in ("src", "scripts", "tests") for p in (ROOT / d).rglob("*.py"))


def test_there_is_something_to_check() -> None:
    assert len(SOURCES) > 20


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_parses_as_python_3_9(path: Path) -> None:
    # `match` statements, `except*` and parenthesized context managers are rejected by feature_version.
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


def annotation_nodes(tree: ast.AST) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            yield node.returns


LIBRARY = [p for p in SOURCES if "tests" not in p.relative_to(ROOT).parts and "generated" not in p.parts]


@pytest.mark.parametrize("path", LIBRARY, ids=lambda p: str(p.relative_to(ROOT)))
def test_annotations_avoid_the_pipe_union_that_3_9_cannot_evaluate(path: Path) -> None:
    """``X | None`` is fine under ``from __future__ import annotations`` until something evaluates it (typing.get_type_hints,
    pydantic, FastAPI); the library's public annotations use Optional and Union, so that they always can be."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pipes: List[str] = []
    for annotation in annotation_nodes(tree):
        for node in ast.walk(annotation):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                pipes.append(ast.unparse(annotation))
    assert pipes == []


@pytest.mark.skipif(sys.version_info < (3, 12), reason="older parsers reject these themselves")
@pytest.mark.parametrize("path", [p for p in SOURCES if "generated" not in p.parts], ids=lambda p: str(p.relative_to(ROOT)))
def test_f_strings_are_valid_before_3_12(path: Path) -> None:
    """PEP 701 (3.12) allows the quote of an f-string inside its braces, and backslashes: 3.9 to 3.11 do not."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = ast.get_source_segment(source, node) or ""
        quote = text.lstrip("rbfRBF")[:3] if text.lstrip("rbfRBF")[:3] in ('"""', "'''") else text.lstrip("rbfRBF")[:1]
        for part in node.values:
            if not isinstance(part, ast.FormattedValue):
                continue
            segment = ast.get_source_segment(source, part.value) or ""
            assert quote[:1] not in segment or len(quote) == 3, f"{path.name}:{node.lineno}: {quote} inside {segment!r}"
            assert "\\" not in segment, f"{path.name}:{node.lineno}: a backslash in an f-string expression"
