"""Configuration loading and validation for FailChain.

Supports both YAML (.yml / .yaml) and TOML (.toml) config files.
All fields have sensible defaults so minimal config works out of the box.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Sub-config models
# ---------------------------------------------------------------------------


class FrameworkConfig(BaseModel):
    name: str = "playwright"
    test_dir: str = "./tests"
    runner_command: str = "npx playwright test"
    screenshot_dir: str = "./playwright-screenshots"


class RelatedFilesConfig(BaseModel):
    strategy: str = "playwright-pom"
    page_objects_dir: str = "./pom/pages"
    fixtures_dir: Optional[str] = None
    # Manually specified extra files to always include
    extra_files: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    # Format: "provider:model-name"  e.g. "openai:gpt-4.1-nano", "anthropic:claude-opus-4-6"
    agent_model: str = "openai:gpt-4o-mini"
    # Bare OpenAI model ID — used directly via the OpenAI SDK, not LangChain
    vision_model: str = "gpt-4o"
    max_prompt_tokens: int = 90_000
    max_retries: int = 3


class AnalysisConfig(BaseModel):
    max_failures: Optional[int] = None
    max_screenshots: int = 5
    skip_reruns: bool = False
    skip_screenshots: bool = False
    # When a single spec file has >= this many distinct error groups, collapse into one
    collapse_threshold: int = 5


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class FailChainConfig(BaseModel):
    parser: str = "auto"
    report_path: str = "./test-results/results.xml"
    framework: FrameworkConfig = Field(default_factory=FrameworkConfig)
    source_dirs: list[str] = Field(default_factory=lambda: ["./src"])
    related_files: RelatedFilesConfig = Field(default_factory=RelatedFilesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    def resolve_parser(self) -> str:
        """Return the parser type, auto-detecting from report_path if needed."""
        if self.parser != "auto":
            return self.parser
        ext = Path(self.report_path).suffix.lower()
        if ext == ".xml":
            return "junit-xml"
        if ext == ".json":
            return "playwright-json"
        return "junit-xml"

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: Optional[str | Path] = None) -> FailChainConfig:
    """Load config from file, falling back to defaults if none found.

    Search order if no path given:
      1. test-analyzer.yml
      2. test-analyzer.yaml
      3. test-analyzer.toml
      4. failchain.yml
      5. failchain.yaml
      6. failchain.toml
    """
    search_paths = [
        "test-analyzer.yml",
        "test-analyzer.yaml",
        "test-analyzer.toml",
        "failchain.yml",
        "failchain.yaml",
        "failchain.toml",
    ]

    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        return _load_file(config_path)

    for candidate in search_paths:
        p = Path(candidate)
        if p.exists():
            return _load_file(p)

    # No config file found — use all defaults
    return FailChainConfig()


def _load_file(path: Path) -> FailChainConfig:
    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif suffix == ".toml":
        if tomllib is None:
            raise ImportError(
                "TOML config requires Python 3.11+ or 'tomli' package: pip install tomli"
            )
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        raise ValueError(f"Unsupported config format: {suffix}")

    return FailChainConfig.model_validate(data)


def generate_example_config() -> str:
    """Return a well-commented example YAML config string."""
    return """\
# FailChain configuration
# https://github.com/RyanKhan1234/FailChain

# Parser: junit-xml | playwright-json | auto (detect from report_path extension)
parser: auto
report_path: ./test-results/results.xml

# Test framework settings
framework:
  name: playwright          # playwright | cypress | pytest | jest
  test_dir: ./tests
  runner_command: "npx playwright test"
  screenshot_dir: ./playwright-screenshots

# Directories to search for application source code
source_dirs:
  - ./src
  - ./backend

# How to resolve files related to a failing test (imports, page objects, fixtures)
related_files:
  strategy: playwright-pom  # playwright-pom | cypress-commands | pytest-fixtures | none
  page_objects_dir: ./pom/pages

# LLM configuration
llm:
  # Format: "provider:model-name"
  # Supported providers: openai, anthropic
  agent_model: openai:gpt-4o-mini
  vision_model: gpt-4o
  max_prompt_tokens: 90000
  max_retries: 3

# Analysis settings
analysis:
  max_failures: null        # null = analyze all failures
  max_screenshots: 5        # max screenshots to analyze per failure group
  skip_reruns: false        # set true to skip test re-runs
  skip_screenshots: false   # set true to skip vision analysis
  collapse_threshold: 5     # collapse spec files with >= N distinct error groups
"""
