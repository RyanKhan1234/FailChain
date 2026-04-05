"""Token-aware batch packing.

Estimates prompt token usage per failure group and greedily packs groups
into batches that stay under the configured token limit. This prevents
context-window overflow when analyzing large test suites.

Token estimation: ~4 characters per token (rough but framework-agnostic).
"""

from __future__ import annotations

from failchain.models import FailureGroup

_CHARS_PER_TOKEN = 4
# Overhead for system prompt, agent instructions, tool schemas, etc.
_SYSTEM_OVERHEAD_TOKENS = 3000


def estimate_tokens(text: str) -> int:
    """Estimate token count from character count."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def group_to_prompt_text(group: FailureGroup) -> str:
    """Serialize a FailureGroup to the text that will appear in the agent prompt."""
    lines = [
        f"### Failure: {', '.join(group.titles[:3])}",
        f"**File:** `{group.spec_file}`",
        f"**Error signature:** {group.error_signature}",
    ]
    # Include full error detail so the agent sees exact selectors, locator
    # strings, and line numbers without needing to call tools first.
    rep = group.representative
    if rep.error and rep.error != group.error_signature:
        full_error = rep.error[:1500].strip()
        lines.append(f"**Full error:**\n```\n{full_error}\n```")
    if group.is_collapsed:
        lines.append(f"*Note: {len(group.failures)} failures collapsed from this file.*")
    for hint in group.static_hints:
        lines.append(f"**Pre-analysis finding:** {hint}")
    for analysis in group.screenshot_analyses:
        lines.append(f"**Screenshot analysis:** {analysis}")
    return "\n".join(lines)


def pack_into_batches(
    groups: list[FailureGroup],
    max_tokens: int = 90_000,
) -> list[list[FailureGroup]]:
    """Greedy bin-packing: fit as many groups as possible into each batch.

    Args:
        groups: Ordered list of failure groups.
        max_tokens: Token budget per batch (system overhead already subtracted).

    Returns:
        List of batches, where each batch is a list of FailureGroup.
    """
    effective_limit = max_tokens - _SYSTEM_OVERHEAD_TOKENS

    batches: list[list[FailureGroup]] = []
    current_batch: list[FailureGroup] = []
    current_tokens = 0

    for group in groups:
        group_text = group_to_prompt_text(group)
        group_tokens = estimate_tokens(group_text)

        if group_tokens > effective_limit:
            # Single group exceeds budget — give it its own batch (will truncate in agent)
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            batches.append([group])
            continue

        if current_tokens + group_tokens > effective_limit:
            # Start a new batch
            batches.append(current_batch)
            current_batch = [group]
            current_tokens = group_tokens
        else:
            current_batch.append(group)
            current_tokens += group_tokens

    if current_batch:
        batches.append(current_batch)

    return batches
