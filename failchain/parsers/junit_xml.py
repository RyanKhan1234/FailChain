"""JUnit XML parser.

Handles the standard JUnit XML format output by Playwright (via reporters),
Jest (jest-junit), pytest (pytest-junit), Cypress (cypress-junit-reporter),
and virtually every other test framework that targets CI systems.

Schema reference: https://llg.cubic.org/docs/junit/
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from failchain.models import TestResult, TestStatus
from failchain.parsers.base import BaseParser


class JUnitXMLParser(BaseParser):
    name = "junit-xml"
    extensions = [".xml"]

    def parse(self) -> list[TestResult]:
        text = self._read_text()
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid JUnit XML in {self.report_path}: {exc}") from exc

        results: list[TestResult] = []

        # Support both <testsuites> wrapper and bare <testsuite> root
        suites = root.findall(".//testsuite")
        if not suites:
            # Root itself might be a testsuite
            suites = [root] if root.tag == "testsuite" else []

        for suite in suites:
            suite_name = suite.get("name", "")
            for case in suite.findall("testcase"):
                result = self._parse_testcase(case, suite_name)
                if result is not None:
                    results.append(result)

        return results

    # ------------------------------------------------------------------

    def _parse_testcase(self, case: ET.Element, suite_name: str) -> TestResult | None:
        classname = case.get("classname", "")
        name = case.get("name", "unknown")
        time_str = case.get("time", "0")

        # Build title: "Suite > Test Name"
        if suite_name and suite_name != classname:
            title = f"{suite_name} > {name}"
        elif classname:
            title = f"{classname} > {name}"
        else:
            title = name

        try:
            duration_ms = float(time_str) * 1000
        except ValueError:
            duration_ms = None

        # Check for failure / error elements
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")

        if skipped is not None:
            return None  # Skip passing/skipped tests

        if failure is None and error is None:
            return None  # Passing test — ignore

        element = failure if failure is not None else error
        assert element is not None

        error_message = self._extract_message(element)
        status = TestStatus.FAILED if failure is not None else TestStatus.ERROR

        # Spec file: prefer classname (usually maps to file path in most reporters),
        # fall back to suite name or a placeholder.
        spec_file = self._resolve_spec_file(classname, suite_name)

        # Screenshots may be embedded in system-out as attachment references
        system_out = case.find("system-out")
        screenshots = []
        if system_out is not None and system_out.text:
            screenshots = _extract_attachment_paths(system_out.text)

        return TestResult(
            title=title,
            spec_file=spec_file,
            status=status,
            error=self._truncate(error_message),
            screenshots=screenshots,
            duration_ms=duration_ms,
            extra={"classname": classname, "suite_name": suite_name},
        )

    @staticmethod
    def _extract_message(element: ET.Element) -> str:
        parts: list[str] = []
        msg = element.get("message", "")
        if msg:
            parts.append(msg)
        if element.text and element.text.strip():
            parts.append(element.text.strip())
        return "\n".join(parts) or "(no error message)"

    @staticmethod
    def _resolve_spec_file(classname: str, suite_name: str) -> str:
        """Try to derive a meaningful spec file path from classname / suite name."""
        for candidate in (classname, suite_name):
            if not candidate:
                continue
            # Some reporters use file paths directly in classname
            for sep in ("/", "\\", "."):
                if sep in candidate:
                    # Heuristic: if it looks like a path, use it
                    if sep in ("/", "\\") and (
                        candidate.endswith(".ts")
                        or candidate.endswith(".js")
                        or candidate.endswith(".py")
                        or candidate.endswith(".spec")
                    ):
                        return candidate
            # Fall back: use as-is
            return candidate
        return "unknown"


def _extract_attachment_paths(text: str) -> list[str]:
    """Extract Playwright-style attachment markers from system-out text.

    Playwright JUnit reporter embeds screenshots as:
        [[ATTACHMENT|/path/to/screenshot.png]]
    """
    import re

    paths = re.findall(r"\[\[ATTACHMENT\|([^\]]+)\]\]", text)
    # Also grab plain .png / .jpg paths
    plain = re.findall(r"(?:^|\s)(/[^\s]+\.(?:png|jpg|jpeg|webp))", text)
    return list(dict.fromkeys(paths + plain))  # deduplicate, preserve order
