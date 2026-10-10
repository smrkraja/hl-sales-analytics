"""Optional Claude-written narrative over the rule-based insights.

Only runs when ANTHROPIC_API_KEY is set; the dashboard works fully without it.
Claude only sees aggregated metrics and headlines - no loan-level records.
"""
import os

import anthropic

from hl.core.insights import Insight

MODEL = "claude-opus-5-5"
SYSTEM_PROMPT = (
    "You are a mortgage market analyst briefing home lending advisers at a bank. "
    "Using only the facts provided, write a short briefing (under 200 words): the 2-3 most "
    "actionable takeaways, which product to push where, and what to watch. Do not invent numbers."
)


def is_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _facts(insights: list[Insight]) -> str:
    lines = []
    for insight in insights:
        line = f"- [{insight.kind}] {insight.title}. {insight.detail}"
        if insight.drivers:
            line += " Drivers: " + "; ".join(insight.drivers)
        lines.append(line)
    return "\n".join(lines)


def write_briefing(area: str, insights: list[Insight]) -> str:
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": "low"},  # short summarisation - low effort is plenty
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Area: {area}\n\nFacts:\n{_facts(insights)}"}],
        )
    except anthropic.AuthenticationError:
        return "Narrative unavailable: ANTHROPIC_API_KEY was rejected."
    except anthropic.RateLimitError:
        return "Narrative unavailable: rate limited - try again shortly."
    except anthropic.APIStatusError as error:
        return f"Narrative unavailable: API error {error.status_code}."
    except anthropic.APIConnectionError:
        return "Narrative unavailable: could not reach the Claude API."

    if response.stop_reason == "refusal":
        return "Narrative unavailable for this area."
    return "".join(block.text for block in response.content if block.type == "text")
