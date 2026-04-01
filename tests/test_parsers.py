"""Tests for the parser layer."""

import textwrap
from pathlib import Path

import pytest

from failchain.models import TestStatus
from failchain.parsers.junit_xml import JUnitXMLParser
from failchain.parsers.playwright_json import PlaywrightJSONParser
from failchain.parsers.registry import ParserRegistry


# ---------------------------------------------------------------------------
# JUnit XML
# ---------------------------------------------------------------------------

JUNIT_XML_SINGLE_FAILURE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <testsuites>
      <testsuite name="checkout tests" tests="2" failures="1">
        <testcase classname="tests/checkout.spec.ts" name="should complete purchase" time="3.5">
          <failure message="Expected element to be visible">
            Error: locator('button[data-testid=buy-now]') not found
            at checkout.spec.ts:42
          </failure>
        </testcase>
        <testcase classname="tests/checkout.spec.ts" name="should show cart" time="1.2"/>
      </testsuite>
    </testsuites>
""")

JUNIT_XML_NO_FAILURES = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <testsuites>
      <testsuite name="smoke tests" tests="3">
        <testcase classname="tests/smoke.spec.ts" name="homepage loads" time="1.0"/>
        <testcase classname="tests/smoke.spec.ts" name="login works" time="2.0"/>
      </testsuite>
    </testsuites>
""")


def test_junit_parser_finds_failure(tmp_path):
    xml_file = tmp_path / "results.xml"
    xml_file.write_text(JUNIT_XML_SINGLE_FAILURE)

    parser = JUnitXMLParser(xml_file)
    results = parser.parse()

    assert len(results) == 1
    result = results[0]
    assert result.status == TestStatus.FAILED
    assert "buy-now" in result.error
    assert result.spec_file == "tests/checkout.spec.ts"
    assert "should complete purchase" in result.title


def test_junit_parser_ignores_passing(tmp_path):
    xml_file = tmp_path / "results.xml"
    xml_file.write_text(JUNIT_XML_NO_FAILURES)

    results = JUnitXMLParser(xml_file).parse()
    assert results == []


def test_junit_parser_missing_file():
    with pytest.raises(FileNotFoundError):
        JUnitXMLParser("/nonexistent/results.xml").parse()


def test_junit_parser_invalid_xml(tmp_path):
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<not valid xml <<>>")
    with pytest.raises(ValueError, match="Invalid JUnit XML"):
        JUnitXMLParser(bad_xml).parse()


# ---------------------------------------------------------------------------
# Playwright JSON
# ---------------------------------------------------------------------------

PLAYWRIGHT_JSON = {
    "suites": [
        {
            "file": "tests/auth.spec.ts",
            "suites": [],
            "specs": [
                {
                    "title": "should login with valid credentials",
                    "tests": [
                        {
                            "status": "failed",
                            "expectedStatus": "passed",
                            "results": [
                                {
                                    "duration": 5000,
                                    "errors": [
                                        {"message": "expect(received).toBe(expected)\nExpected: '/dashboard'\nReceived: '/login'"}
                                    ],
                                    "attachments": [
                                        {"contentType": "image/png", "path": "/tmp/screenshot.png"}
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "should logout",
                    "tests": [{"status": "passed", "expectedStatus": "passed", "results": []}],
                },
            ],
        }
    ]
}


def test_playwright_json_parser(tmp_path):
    import json

    json_file = tmp_path / "results.json"
    json_file.write_text(json.dumps(PLAYWRIGHT_JSON))

    results = PlaywrightJSONParser(json_file).parse()

    assert len(results) == 1
    r = results[0]
    assert r.title == "should login with valid credentials"
    assert r.spec_file == "tests/auth.spec.ts"
    assert r.status == TestStatus.FAILED
    assert "/dashboard" in r.error
    assert "/tmp/screenshot.png" in r.screenshots


def test_playwright_json_ignores_passing(tmp_path):
    import json

    data = {"suites": [{"file": "t.spec.ts", "suites": [], "specs": [
        {"title": "passes", "tests": [{"status": "passed", "expectedStatus": "passed", "results": []}]}
    ]}]}
    json_file = tmp_path / "results.json"
    json_file.write_text(json.dumps(data))
    assert PlaywrightJSONParser(json_file).parse() == []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_returns_known_parsers():
    assert "junit-xml" in ParserRegistry.all_names()
    assert "playwright-json" in ParserRegistry.all_names()


def test_registry_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown parser"):
        ParserRegistry.get("nonexistent-parser")


def test_registry_auto_detect_xml():
    assert ParserRegistry.auto_detect("results.xml") == "junit-xml"


def test_registry_auto_detect_json():
    assert ParserRegistry.auto_detect("results.json") == "playwright-json"
