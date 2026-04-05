"""Deterministic pre-analysis that detects known TEST CODE FIX patterns.

Runs before the LLM and injects findings into the batch prompt so the
agent has reliable signal without relying on tool calls.
"""

from __future__ import annotations

import re
from pathlib import Path

from failchain.models import FailureGroup

_SEARCHABLE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".css", ".scss",
    ".py", ".vue", ".svelte", ".html",
}


def compute_static_hints(group: FailureGroup, source_dirs: list[str]) -> list[str]:
    """Return pre-computed analysis hints to include in the LLM prompt.

    Detects obvious TEST CODE FIX patterns from the error message without
    requiring the agent to call tools.
    """
    hints: list[str] = []
    error = group.representative.error or ""

    hints.extend(_check_implausible_nth_child(error))
    hints.extend(_check_missing_css_classes(error, source_dirs))
    hints.extend(_check_unreasonably_small_timeout(error))

    return hints


def _check_implausible_nth_child(error: str) -> list[str]:
    hints = []
    for m in re.finditer(r"nth-child\((\d+)\)", error):
        n = int(m.group(1))
        if n > 10:
            hints.append(
                f"nth-child({n}) found in selector — no real UI has {n} siblings "
                f"of the same type. This is a broken selector: TEST CODE FIX."
            )
    return hints


def _check_missing_css_classes(error: str, source_dirs: list[str]) -> list[str]:
    hints = []
    locator_strings = re.findall(r"locator\(['\"]([^'\"]+)['\"]", error)

    seen: set[str] = set()
    for locator in locator_strings:
        for m in re.finditer(r"\.([\w-]{3,})", locator):
            cls = m.group(1)
            if cls in seen:
                continue
            # Skip CSS pseudo-class-like tokens that aren't custom class names
            if cls in {"first", "last", "nth", "not", "is", "where", "has", "nth-child"}:
                continue
            seen.add(cls)
            if not _class_exists_in_source(cls, source_dirs):
                hints.append(
                    f"CSS class `.{cls}` (from locator `{locator}`) was searched "
                    f"across all source directories — NOT FOUND anywhere in the "
                    f"codebase. Selector is checking a nonexistent class: TEST CODE FIX."
                )
    return hints


def _check_unreasonably_small_timeout(error: str) -> list[str]:
    hints = []
    for m in re.finditer(r"timeout[:\s]+(\d+)\s*ms", error, re.IGNORECASE):
        ms = int(m.group(1))
        if ms < 500:
            hints.append(
                f"Timeout of {ms}ms is unreasonably small for a UI assertion. "
                f"Test is too impatient, not the app too slow: TEST CODE FIX."
            )
    return hints


def _class_exists_in_source(class_name: str, source_dirs: list[str]) -> bool:
    """Return True if class_name appears in any source file."""
    pattern = re.compile(re.escape(class_name))
    for source_dir in source_dirs:
        p = Path(source_dir)
        if not p.exists():
            continue
        for file_path in p.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SEARCHABLE_EXTENSIONS:
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if pattern.search(content):
                    return True
            except Exception:
                pass
    return False
