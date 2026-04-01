"""LangChain agent that investigates failure batches and produces root-cause analysis.

Uses LangChain 1.x's create_agent (LangGraph-backed) API.
The agent receives a batch of FailureGroups, uses its tools to investigate,
and outputs a structured markdown section for each failure.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from failchain.analysis.batching import group_to_prompt_text
from failchain.analysis.retry import with_retry
from failchain.config import FailChainConfig
from failchain.models import AnalysisResult, FailureGroup


_SYSTEM_PROMPT = """\
You are FailChain, an expert test failure root-cause analyzer.

Your job is to investigate each failing test group and produce a precise markdown \
root-cause analysis section.

## Investigation Process

For EACH failure group:
1. Call `read_test_source` with the spec file path to read the test code and its \
related files (page objects, fixtures, helpers).
2. If the error references an API, component, or function name, call \
`search_source_code` to find it in the application source.
3. If the failure looks potentially flaky (timing, network, intermittent), \
optionally call `rerun_test` to confirm.

## Output Format

Produce one markdown section per failure group using EXACTLY this structure:

## Failure N: [Test Title(s)]

**File:** `path/to/spec`
**Category:** TEST CODE FIX | APPLICATION CODE FIX
**Error:** `brief error message`

### Root Cause
2–4 sentences explaining the precise cause. Reference file paths and line numbers \
where possible. Be specific — avoid generic statements like "the test failed."

### Recommendation
A specific, actionable fix. If it's a TEST CODE FIX, show what to change in the \
test. If it's APPLICATION CODE FIX, describe what the application needs to implement \
or fix.

---

## Categorization Guide

**TEST CODE FIX** — the test itself is wrong:
- Fragile or outdated CSS selectors / XPath
- Wrong assertion (testing the wrong thing)
- Race condition / missing `waitFor`
- Hardcoded data that has changed
- Test setup/teardown issue
- Missing or incorrect mock/stub

**APPLICATION CODE FIX** — the application has a bug or missing feature:
- Actual UI regression (element missing, wrong text, wrong behavior)
- API returning unexpected response or status code
- Missing feature that the test expects
- Performance issue causing timeout
- Data/state issue caused by application logic

When in doubt, lean toward APPLICATION CODE FIX — it's better to flag a real bug \
than to dismiss a valid failure.
"""

_HUMAN_TEMPLATE = """\
Analyze the following {count} test failure group(s) and produce a root-cause analysis \
section for each one.

{failure_summaries}

Start with Failure 1 and work through all {count} groups. Use your tools to investigate \
before writing your analysis. Produce the full markdown output when done.
"""


def build_agent(
    config: FailChainConfig,
    tools: list[BaseTool],
):
    """Build a LangChain 1.x agent graph configured for failure analysis."""
    from langchain.agents import create_agent

    model_string = _normalize_model_string(config)
    return create_agent(
        model=model_string,
        tools=tools,
        system_prompt=_SYSTEM_PROMPT,
    )


def analyze_batch(
    agent,
    batch: list[FailureGroup],
    batch_index: int = 0,
    max_retries: int = 3,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> list[AnalysisResult]:
    """Run the agent on one batch of failure groups.

    Returns one AnalysisResult per group in the batch.
    """
    failure_summaries = "\n\n".join(
        f"{i + 1}. {group_to_prompt_text(group)}"
        for i, group in enumerate(batch)
    )

    human_message = _HUMAN_TEMPLATE.format(
        count=len(batch),
        failure_summaries=failure_summaries,
    )

    def _invoke():
        result = agent.invoke({"messages": [HumanMessage(content=human_message)]})
        # LangChain 1.x returns {"messages": [...]} — last message is the final response
        messages = result.get("messages", [])
        if not messages:
            return ""
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)

    raw_output: str = with_retry(
        _invoke,
        max_retries=max_retries,
        on_retry=on_retry,
    )

    return _parse_agent_output(raw_output, batch)


def _parse_agent_output(
    output: str,
    batch: list[FailureGroup],
) -> list[AnalysisResult]:
    """Extract one AnalysisResult per failure group from the agent's markdown output."""
    # Split on ## Failure N: headers
    sections = re.split(r"(?=^##\s+Failure\s+\d+)", output, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip() and re.match(r"^##\s+Failure", s)]

    results: list[AnalysisResult] = []
    for i, (group, section) in enumerate(
        zip(batch, sections if sections else [output] * len(batch))
    ):
        fix_type = _extract_fix_type(section)
        results.append(
            AnalysisResult(
                group=group,
                markdown=section,
                fix_type=fix_type,
                failure_index=i,
            )
        )

    # If the agent didn't produce separate sections, wrap entire output for the first group
    if not results:
        for i, group in enumerate(batch):
            results.append(
                AnalysisResult(
                    group=group,
                    markdown=(
                        output
                        if i == 0
                        else f"## Failure {i + 1}: {group.representative.title}\n\n[See Failure 1 analysis]"
                    ),
                    fix_type="APPLICATION CODE FIX",
                    failure_index=i,
                )
            )

    return results


def _extract_fix_type(markdown: str) -> str:
    if "TEST CODE FIX" in markdown:
        return "TEST CODE FIX"
    if "APPLICATION CODE FIX" in markdown:
        return "APPLICATION CODE FIX"
    return "APPLICATION CODE FIX"


def _normalize_model_string(config: FailChainConfig) -> str:
    """Convert our 'provider:model' format to LangChain 1.x's 'provider/model' format.

    LangChain 1.x create_agent accepts strings like 'openai:gpt-4o-mini' directly —
    same format as our config, so no transformation needed.
    """
    return config.llm.agent_model
