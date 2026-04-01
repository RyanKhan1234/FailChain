"""Vision model screenshot analysis.

Uses a vision-capable model (default: gpt-4o) to analyze failure screenshots
with test context (test name + error message) for context-aware visual analysis.

Each screenshot is analyzed independently and the result is attached to the
FailureGroup for the agent to reference.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from failchain.analysis.retry import with_retry


def analyze_screenshots(
    screenshots: list[str],
    test_title: str,
    error_message: Optional[str],
    vision_model: str = "gpt-4o",
    max_screenshots: int = 5,
    max_retries: int = 3,
    on_progress: Optional[callable] = None,
) -> list[str]:
    """Analyze failure screenshots with a vision model.

    Args:
        screenshots: List of screenshot file paths.
        test_title: Name of the failing test (provides context to the model).
        error_message: Error message from the test failure (provides context).
        vision_model: OpenAI model ID to use for vision analysis.
        max_screenshots: Maximum number of screenshots to analyze.
        max_retries: Retry attempts on rate-limit errors.
        on_progress: Optional callback(screenshot_path) called before each analysis.

    Returns:
        List of text descriptions — one per screenshot analyzed.
    """
    if not screenshots:
        return []

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package is required for screenshot analysis: pip install openai")

    client = OpenAI()
    results: list[str] = []

    for screenshot_path in screenshots[:max_screenshots]:
        if on_progress:
            on_progress(screenshot_path)

        try:
            analysis = with_retry(
                lambda: _analyze_one(client, screenshot_path, test_title, error_message, vision_model),
                max_retries=max_retries,
            )
            results.append(analysis)
        except Exception as exc:
            results.append(f"[Screenshot analysis failed: {exc}]")

    return results


def _analyze_one(
    client,
    screenshot_path: str,
    test_title: str,
    error_message: Optional[str],
    model: str,
) -> str:
    """Analyze a single screenshot."""
    image_data = _load_image_base64(screenshot_path)
    if image_data is None:
        return f"[Could not load screenshot: {screenshot_path}]"

    media_type = _detect_media_type(screenshot_path)
    error_context = f"\nError message: {error_message[:500]}" if error_message else ""

    prompt = (
        f"You are analyzing a screenshot from a failing automated test.\n\n"
        f"Test name: {test_title}{error_context}\n\n"
        "Describe what you see in the screenshot that is relevant to understanding "
        "why this test failed. Be specific about:\n"
        "- The visible UI state (what page/component is shown)\n"
        "- Any error messages, alerts, or unexpected UI elements\n"
        "- Whether the UI looks like it's in an incomplete/loading state\n"
        "- Anything that doesn't match what the test would expect\n\n"
        "Keep your response to 3-5 sentences."
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=300,
    )
    return response.choices[0].message.content or "[No analysis returned]"


def _load_image_base64(path: str) -> Optional[str]:
    try:
        return base64.b64encode(Path(path).read_bytes()).decode("utf-8")
    except Exception:
        return None


def _detect_media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")
