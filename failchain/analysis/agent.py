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

Your job is to INVESTIGATE each failure using your tools and produce evidence-backed \
root-cause analysis. Do NOT write your analysis until you have found concrete evidence \
from the source code.

## Mandatory Investigation Steps

For EVERY failure group, you MUST do ALL of the following before writing analysis:

**Step 1 — Read the test source**
Call `read_test_source` with the spec file path. This returns the test file AND its \
related files (page objects, fixtures, helpers). Read them carefully.

**Step 2 — Search the application source (required, not optional)**
You MUST call `search_source_code` at least once per failure. Use the specific \
error detail as your search term — a selector, a URL, an element ID, a function name.

**Step 3 — Apply error-pattern-specific searches**
Different error types require different searches. Follow these rules:

- **Selector / element not found (`resolved to 0 elements`, `not found`)**
  Search for the EXACT selector string (e.g. `add-to-cart`). If no results, the \
  element was renamed — search for partial matches and variations (e.g. `add-to-cart-btn`, \
  `addToCart`). Look for comments documenting renames (e.g. `data-testid migration`).

- **Element not visible / timeout waiting for element**
  Search for the element's `id` or `data-testid` in the source. Look specifically \
  for conditional rendering: feature flags, `&&` operators, `if` statements, \
  `ternary` expressions, or CSS `display:none`. A timeout usually means the element \
  exists in code but is conditionally hidden.

- **URL mismatch (`Expected: /x, Received: /y`)**
  Search for BOTH the expected URL AND the received URL in the source. Find where \
  the redirect is configured and read the surrounding comments — they often explain \
  why it changed.

- **Text content assertion (`getByText`, `:text-is()`, `toContainText`)**
  Extract the exact string or regex being checked. Search for that literal text in \
  the application source files. If the text does NOT appear anywhere in the source, \
  the test was written against text that was never rendered by the app — this is \
  **TEST CODE FIX** (wrong assertion). Do not conclude application code is broken \
  just because a progress message or label isn't visible; first verify the text \
  actually exists in the codebase.

- **Wrong text / assertion value mismatch**
  Search for the expected value in the source to find where it's set. Compare \
  expected vs actual to determine if the test or the app is wrong.

**Step 4 — Keep searching until you have a specific answer**
If your first search returns no results or is too broad, try narrower or alternative \
terms. Never write "investigation was inconclusive" — keep searching.

## Output Format

Produce one markdown section per failure group using EXACTLY this structure:

## Failure N: [Test Title(s)]

**File:** `path/to/spec`
**Category:** TEST CODE FIX | APPLICATION CODE FIX
**Error:** `brief error message`

### Root Cause
2–4 sentences. You MUST cite specific evidence: file path, line number, and the \
exact code or comment that proves your conclusion. Generic statements like "the \
element may not be rendering" are not acceptable — find the proof.

### Recommendation
A specific, actionable fix with a code example where possible. If TEST CODE FIX, \
show the exact line to change and what to change it to. If APPLICATION CODE FIX, \
name the specific file, flag, or API that needs to be updated.

---

## Categorization Rules

**Always check test comments first.** Before deciding a category, read the inline \
comments in the test source. Tests are sometimes annotated with their intended \
failure category (e.g. `Category: TEST CODE FIX`). If you find an explicit comment \
like this, it is strong evidence — use it.

**TEST CODE FIX** — the test itself is the problem:
- A comment in the test file explicitly labels this as a test code issue
- A selector, testid, or URL was intentionally renamed/moved in the app — the test \
  is using the old value (check comments/commit messages for evidence of intent)
- The selector is clearly invalid or over-engineered: using structural CSS combinators \
  like `nth-child(N)` where N is implausibly large, deep nesting 4+ levels, or \
  selectors that don't appear anywhere in the application source
- A CSS class in the selector does not exist anywhere in the source files — \
  overspecified locators that check implementation details of styling
- A timeout value that is unreasonably small (e.g. 200ms, 500ms) for the operation \
  being awaited — the test is too impatient, not the app too slow
- `toHaveCount` with `timeout: 0` — zero timeout means no retry at all, racing \
  the DOM before React can commit state
- Wrong assertion — the test is checking the wrong thing
- Race condition or missing wait — the test is too fast for the UI
- Hardcoded test data that is no longer valid

**APPLICATION CODE FIX** — the application has a bug or is missing something:
- A feature is gated behind a flag that isn't enabled in the test environment
- An element that should always be present is missing from the DOM
- An API returns an unexpected status code or response shape
- A route or endpoint was removed or changed without backward compatibility

**Key distinction:** If the test selector, timeout, or assertion is the part that \
is wrong (and the app is behaving correctly), that is TEST CODE FIX. If the test \
is correct but the application is not behaving as it should, that is \
APPLICATION CODE FIX. When in doubt, search the application source — if the \
element or class the test is looking for simply doesn't exist anywhere in the \
codebase, that is strong evidence of TEST CODE FIX (the test was written against \
something that was never there or was removed from the test, not the app).
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
    on_tool_call: Optional[Callable[[str, dict], None]] = None,
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

    input_data = {"messages": [HumanMessage(content=human_message)]}

    def _invoke():
        return _run_agent(agent, input_data, on_tool_call)

    raw_output: str = with_retry(
        _invoke,
        max_retries=max_retries,
        on_retry=on_retry,
    )

    return _parse_agent_output(raw_output, batch)


def _run_agent(
    agent,
    input_data: dict,
    on_tool_call: Optional[Callable[[str, dict], None]] = None,
) -> str:
    """Run the agent with streaming so tool calls surface in real time.

    Falls back to agent.invoke() if streaming raises unexpectedly.
    """
    final_content = ""

    try:
        for chunk in agent.stream(input_data, stream_mode="updates"):
            for node_name, node_data in chunk.items():
                messages = node_data.get("messages", [])
                for msg in messages:
                    if node_name == "agent":
                        # tool_calls may be dicts or objects depending on LangChain build
                        raw_calls = getattr(msg, "tool_calls", None) or []
                        for tc in raw_calls:
                            if on_tool_call:
                                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                                on_tool_call(name, args)
                        # Final response: has content and no pending tool calls
                        content = getattr(msg, "content", "")
                        if content and not raw_calls:
                            final_content = content
    except Exception:
        # Streaming unavailable — fall back to invoke()
        result = agent.invoke(input_data)
        for msg in reversed(result.get("messages", [])):
            content = getattr(msg, "content", "")
            if content and not getattr(msg, "tool_calls", None):
                return content
        return ""

    # Safety net: streaming completed but captured nothing — fall back to invoke()
    if not final_content:
        result = agent.invoke(input_data)
        for msg in reversed(result.get("messages", [])):
            content = getattr(msg, "content", "")
            if content and not getattr(msg, "tool_calls", None):
                return content

    return final_content


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
