# FailChain

**AI-powered test failure root-cause analysis for any testing framework.**


---

## Why this exists

Anyone who has maintained a large E2E test suite knows the drill: CI goes red, you open the report, and you spend the next 30 minutes manually reading stack traces, cross-referencing source code, and trying to decide whether each failure is a real bug or a flaky test. It's slow, repetitive work — and it scales badly as the suite grows.

FailChain was designed from the ground up to automate that triage loop. Inspired by real-world experience working with E2E test suites at scale, it reimplements the core ideas of AI-assisted failure analysis as a clean, general-purpose, open-source tool — built fresh, with no framework lock-in and no assumptions about your stack.

The pipeline parses your test report, runs vision-model analysis on failure screenshots, groups similar failures to eliminate redundant work, and sends each group to a LangChain agent equipped with tools to read your test source and search your application code. The result is a structured Markdown report that categorizes every failure as either a real application bug or a test code issue — with specific, actionable recommendations.

---

## What it does

FailChain runs a multi-phase AI pipeline against your test report:

```
Parse  →  Screenshots  →  Group  →  Vision  →  Static   →  Batch  →  Agent  →  Report
  │            │            │       Analysis    Pre-Analysis    │          │          │
Read       Discover     Cluster   GPT-4V per  Deterministic  Token-   LangGraph   Markdown
test      screenshots   by file   group       selector/       aware    agent +      with
results   per failure + error     screenshots timeout checks  packing    tools      categories
```

The agent investigates each failure using tools — reading test source files, searching your application code, optionally re-running the test — and produces a report that categorizes every failure as either:

- **APPLICATION CODE FIX** — a real bug in the application
- **TEST CODE FIX** — a problem with the test itself (bad selector, wrong assertion, race condition)

---

## Example output

```markdown
## Failure 1: should complete checkout after adding to cart

**File:** `tests/checkout/purchase.spec.ts`
**Category:** APPLICATION CODE FIX
**Error:** `locator('button[data-testid="add-to-cart"]') not found`

### Root Cause
The `add-to-cart` button's `data-testid` attribute was renamed to `data-testid="add-item"`
in `src/components/ProductCard.tsx` (line 47) as part of the design system migration.
The test is targeting a selector that no longer exists in the rendered DOM.

### Recommendation
Update the selector at `purchase.spec.ts:22` to `button[data-testid="add-item"]` to match
the current attribute value, and audit other specs in the suite that may reference the old
`add-to-cart` testid.
```

---

## Features

- **Multi-framework** — JUnit XML (output of Playwright, Cypress, Jest, pytest, and virtually every CI system) and Playwright JSON natively; trivial to add more
- **Vision analysis** — GPT-4o analyzes failure screenshots with test context (test name + error) before the agent runs
- **Smart grouping** — clusters failures by file + error signature to eliminate redundant analysis; collapses files with many distinct errors into a single group
- **Token-aware batching** — greedy bin-packing keeps large test suites within your model's context window; multi-batch reports are merged and renumbered automatically
- **Structured categories** — every failure gets `APPLICATION CODE FIX` or `TEST CODE FIX` with a specific recommendation
- **Pluggable everything** — parsers, screenshot strategies, related-file resolvers, and agent tools are all extensible via subclassing or entry points
- **Exponential backoff** — automatic retry on 429 rate-limit and transient 5xx errors (30s → 60s → 120s)
- **YAML or TOML config** — project-specific settings in `test-analyzer.yml`

---

## Installation

```bash
git clone https://github.com/RyanKhan1234/FailChain.git
cd FailChain
pip install -e .
```

Set your API key:

```bash
export OPENAI_API_KEY=sk-...
# or for Anthropic models:
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Quick start

**1. Generate a config file**

```bash
failchain init --framework playwright
# also supports: cypress, pytest, jest
```

**2. Edit `test-analyzer.yml`** to point at your test report, source directories, and test runner:

```yaml
report_path: ./playwright-report/results.xml
source_dirs:
  - ./src
framework:
  runner_command: "npx playwright test"
```

**3. Run the analysis**

```bash
failchain analyze
# with verbose phase-by-phase output:
failchain analyze --verbose
# write report to a specific file:
failchain analyze --output ci-report.md
```

The Markdown report is written to `failchain-report.md` by default.

---

## Configuration reference

All fields are optional — FailChain has sensible defaults for everything.

```yaml
# Parser: auto | junit-xml | playwright-json
# auto = detect from report_path extension (.xml → junit-xml, .json → playwright-json)
parser: auto
report_path: ./test-results/results.xml

# Test framework settings
framework:
  name: playwright          # playwright | cypress | pytest | jest
  test_dir: ./tests
  runner_command: "npx playwright test"
  screenshot_dir: ./playwright-screenshots

# Directories searched by the agent's search_source_code tool
source_dirs:
  - ./src
  - ./backend

# Strategy for finding related files (page objects, fixtures, etc.)
related_files:
  strategy: playwright-pom  # playwright-pom | cypress-commands | pytest-fixtures | none
  page_objects_dir: ./tests/pages

# LLM settings — format: "provider:model-name"
llm:
  agent_model: openai:gpt-4o-mini   # used for agent analysis
  vision_model: gpt-4o              # used for screenshot analysis
  max_prompt_tokens: 90000
  max_retries: 3

# Analysis behavior
analysis:
  max_failures: null        # null = all failures; set a number to limit scope
  max_screenshots: 5        # screenshots to analyze per failure group
  skip_reruns: false        # disable the rerun_test agent tool
  skip_screenshots: false   # disable vision analysis (faster, cheaper)
  collapse_threshold: 5     # collapse spec files with >= N distinct error groups
```

---

## Supported frameworks

| Framework | Parser | Screenshot strategy | Related files |
|-----------|--------|---------------------|---------------|
| Playwright | `junit-xml` or `playwright-json` | `playwright` | `playwright-pom` |
| Cypress | `junit-xml` | `cypress` | `cypress-commands` |
| pytest | `junit-xml` | — | `pytest-fixtures` |
| Jest | `junit-xml` | — | `none` |
| Any CI system | `junit-xml` | — | `none` |

The JUnit XML format is the common denominator — if your framework can output it (most can), FailChain can analyze it.

---

## Extending FailChain

### Add a custom parser

```python
from failchain.parsers.base import BaseParser
from failchain.parsers.registry import ParserRegistry
from failchain.models import TestResult, TestStatus

class MyFrameworkParser(BaseParser):
    name = "my-framework"
    extensions = [".json"]

    def parse(self) -> list[TestResult]:
        data = json.loads(self._read_text())
        return [
            TestResult(
                title=t["name"],
                spec_file=t["file"],
                status=TestStatus.FAILED,
                error=t["message"],
            )
            for t in data["failures"]
        ]

ParserRegistry.register("my-framework", MyFrameworkParser)
```

Or register via `pyproject.toml` entry point so it's available as a pip package:

```toml
[project.entry-points."failchain.parsers"]
"my-framework" = "my_package.parser:MyFrameworkParser"
```

### Add a custom agent tool

```python
from langchain_core.tools import tool
from failchain.tools.registry import ToolRegistry

@tool
def check_runtime_flag(flag_name: str) -> str:
    """Check whether a runtime configuration flag is currently enabled."""
    # ... your implementation
    return f"Flag '{flag_name}' is: enabled"

ToolRegistry.register(check_runtime_flag)
```

The tool is automatically included in every subsequent agent run.

### Add a custom related-file resolver

```python
from failchain.related_files.base import BaseRelatedFilesResolver
from failchain.related_files.registry import RelatedFilesRegistry

class MyResolver(BaseRelatedFilesResolver):
    name = "my-resolver"

    def resolve(self, test_file_path) -> list[str]:
        # Return paths of files related to the test
        return ["/path/to/shared/helpers.ts"]

RelatedFilesRegistry.register("my-resolver", MyResolver)
```

Then set `related_files.strategy: my-resolver` in your config.

---

## CLI reference

| Command | Description |
|---------|-------------|
| `failchain analyze` | Run the full analysis pipeline |
| `failchain analyze --config path/to/config.yml` | Use a specific config file |
| `failchain analyze --report results.xml` | Override the report path |
| `failchain analyze --max-failures 20` | Limit to first N failures |
| `failchain analyze --skip-screenshots` | Skip vision analysis |
| `failchain analyze --verbose` | Print phase-by-phase progress |
| `failchain init --framework playwright` | Generate a starter config |
| `failchain list-parsers` | Show available parsers |
| `failchain list-tools` | Show tools available to the agent |

---

## Architecture

FailChain is a linear pipeline of independent, testable phases. Each phase produces a clean output that feeds the next — nothing is stateful between phases.

```
failchain/
├── parsers/           Pluggable: parse any test report into TestResult objects
├── screenshots/       Pluggable: discover screenshot files per framework convention
├── related_files/     Pluggable: resolve page objects, fixtures, support files
├── tools/             LangChain tools + registry for the agent
├── analysis/
│   ├── grouping.py    Cluster failures by (spec_file, error_signature)
│   ├── batching.py    Greedy token-aware bin-packing into batches
│   ├── screenshot_analysis.py  Vision model pre-analysis (GPT-4V per group)
│   ├── static_hints.py         Deterministic pre-analysis injected into prompt
│   ├── agent.py       LangGraph react agent (temperature=0, tool-calling)
│   └── retry.py       Exponential backoff for rate limits
├── reporting/         Assemble, merge, renumber, and write the Markdown report
├── pipeline.py        Orchestrates all phases
└── cli.py             Click CLI entry point
```

---

## Contributing

Contributions are welcome. The most useful additions right now are:

- New parsers for additional frameworks (Vitest, NUnit, Mocha TAP, etc.)
- New screenshot discovery strategies
- New related-file resolvers
- Improvements to the agent's system prompt

Please include tests. The test suite lives in `tests/` and runs with `pytest`.

---

## License

This project is licensed under the [MIT License](./LICENSE).

Copyright (c) 2026 Ryan Khan

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
