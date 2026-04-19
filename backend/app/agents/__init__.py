"""Long-running AI agents: Planner (M1), Target (M3), Analyst (M6), Optimizer (M6)."""
from __future__ import annotations


class MalformedLLMResponse(ValueError):
    """Raised when an agent can't parse structured output (JSON) from the model.

    A ValueError subclass so legacy callers that already `except ValueError`
    keep working. Surfaced by the API layer as HTTP 502 (upstream problem).
    """
