"""Playwright JSON reporter parser.

Parses the output of Playwright's built-in JSON reporter:
  npx playwright test --reporter=json
or configured via playwright.config.ts:
  reporter: [['json', { outputFile: 'test-results/results.json' }]]

Playwright JSON schema reference:
  https://playwright.dev/docs/test-reporters#json-reporter
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from failchain.models import TestResult, TestStatus
from failchain.parsers.base import BaseParser


class PlaywrightJSONParser(BaseParser):
    name = "playwright-json"
    extensions = [".json"]

    def parse(self) -> list[TestResult]:
        text = self._read_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {self.report_path}: {exc}") from exc

        results: list[TestResult] = []
        suites = data.get("suites", [])
        self._walk_suites(suites, results)
        return results

    # ------------------------------------------------------------------

    def _walk_suites(
        self, suites: list[dict], results: list[TestResult], parent_file: str = ""
    ) -> None:
        for suite in suites:
            file_path = suite.get("file", parent_file) or parent_file
            # Recurse into nested suites
            self._walk_suites(suite.get("suites", []), results, file_path)
            # Process specs in this suite
            for spec in suite.get("specs", []):
                for test_result in spec.get("tests", []):
                    result = self._parse_test(spec, test_result, file_path)
                    if result is not None:
                        results.append(result)

    def _parse_test(
        self,
        spec: dict[str, Any],
        test: dict[str, Any],
        spec_file: str,
    ) -> TestResult | None:
        status = self._map_status(test.get("status", ""))
        if status not in (TestStatus.FAILED, TestStatus.ERROR):
            return None

        title = spec.get("title", "unknown")

        # Playwright results have a list of "results" per retry — take last
        run_results: list[dict] = test.get("results", [])
        last_run = run_results[-1] if run_results else {}

        # Build error message from errors array
        error_parts: list[str] = []
        for err in last_run.get("errors", []):
            msg = err.get("message", "")
            if msg:
                error_parts.append(msg)
        error_message = "\n---\n".join(error_parts) or last_run.get("error", {}).get(
            "message", "(no error message)"
        )

        duration_ms = float(last_run.get("duration", 0) or 0)

        # Attachments — Playwright embeds screenshots as attachments
        screenshots: list[str] = []
        for attachment in last_run.get("attachments", []):
            if attachment.get("contentType", "").startswith("image/"):
                path = attachment.get("path", "")
                if path:
                    screenshots.append(path)

        return TestResult(
            title=title,
            spec_file=spec_file or "unknown",
            status=status,
            error=self._truncate(error_message),
            screenshots=screenshots,
            duration_ms=duration_ms,
            extra={
                "retry_count": len(run_results),
                "expected_status": test.get("expectedStatus", ""),
            },
        )

    @staticmethod
    def _map_status(status: str) -> TestStatus:
        mapping = {
            "failed": TestStatus.FAILED,
            "timedOut": TestStatus.FAILED,
            "interrupted": TestStatus.ERROR,
            "passed": TestStatus.PASSED,
            "skipped": TestStatus.SKIPPED,
            "expected": TestStatus.PASSED,
            "unexpected": TestStatus.FAILED,
            "flaky": TestStatus.FAILED,
        }
        return mapping.get(status, TestStatus.FAILED)
