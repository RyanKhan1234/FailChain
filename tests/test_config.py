"""Tests for config loading."""

import textwrap
from pathlib import Path

import pytest

from failchain.config import FailChainConfig, load_config


MINIMAL_YAML = textwrap.dedent("""\
    parser: playwright-json
    report_path: ./results/out.json
""")

FULL_YAML = textwrap.dedent("""\
    parser: junit-xml
    report_path: ./test-results/results.xml

    framework:
      name: playwright
      test_dir: ./e2e
      runner_command: "npx playwright test"
      screenshot_dir: ./screenshots

    source_dirs:
      - ./src
      - ./backend

    related_files:
      strategy: playwright-pom
      page_objects_dir: ./e2e/pages

    llm:
      agent_model: openai:gpt-4o
      vision_model: gpt-4o
      max_prompt_tokens: 80000
      max_retries: 5

    analysis:
      max_failures: 20
      max_screenshots: 3
      skip_reruns: true
      skip_screenshots: false
      collapse_threshold: 3
""")


def test_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert isinstance(cfg, FailChainConfig)
    assert cfg.parser == "auto"
    assert cfg.llm.max_retries == 3


def test_minimal_yaml(tmp_path):
    p = tmp_path / "test-analyzer.yml"
    p.write_text(MINIMAL_YAML)
    cfg = load_config(p)
    assert cfg.parser == "playwright-json"
    assert cfg.report_path == "./results/out.json"
    # Defaults still apply
    assert cfg.framework.name == "playwright"


def test_full_yaml(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(FULL_YAML)
    cfg = load_config(p)

    assert cfg.parser == "junit-xml"
    assert cfg.source_dirs == ["./src", "./backend"]
    assert cfg.llm.agent_model == "openai:gpt-4o"
    assert cfg.llm.max_retries == 5
    assert cfg.analysis.max_failures == 20
    assert cfg.analysis.collapse_threshold == 3
    assert cfg.analysis.skip_reruns is True


def test_missing_config_file():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yml")


def test_parse_llm_model_with_provider():
    cfg = FailChainConfig()
    provider, model = cfg.parse_llm_model("anthropic:claude-opus-4-6")
    assert provider == "anthropic"
    assert model == "claude-opus-4-6"


def test_parse_llm_model_without_provider():
    cfg = FailChainConfig()
    provider, model = cfg.parse_llm_model("gpt-4o")
    assert provider == "openai"
    assert model == "gpt-4o"


def test_resolve_parser_auto_xml():
    cfg = FailChainConfig(parser="auto", report_path="results.xml")
    assert cfg.resolve_parser() == "junit-xml"


def test_resolve_parser_auto_json():
    cfg = FailChainConfig(parser="auto", report_path="playwright-report/results.json")
    assert cfg.resolve_parser() == "playwright-json"


def test_resolve_parser_explicit():
    cfg = FailChainConfig(parser="playwright-json", report_path="results.xml")
    assert cfg.resolve_parser() == "playwright-json"
