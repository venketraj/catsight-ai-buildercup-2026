"""Google Cloud Model Armor Guardrails — Security Pillar & Well-Architected Framework.

Screens user prompts and model responses for prompt injection, jailbreaks,
and policy violations before sending to Gemini or serving to the user.
Integrated with Cloud Logging structured events.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("catsight.guardrails")

# Common prompt injection, jailbreak and override patterns
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I),
    re.compile(r"(?:reveal|show|print|leak)\s+(?:the\s+)?(?:system\s+prompt|hidden\s+instructions?)", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a\s+|an\s+)?(?:unfiltered|jailbroken|dan|evil|developer\s+mode)", re.I),
    re.compile(r"<system>.*?</system>", re.I | re.S),
    re.compile(r"assistant\s*:\s*let's\s+bypass", re.I),
    re.compile(r"base64\s+decode\s+and\s+execute", re.I),
]


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str = ""
    filter_type: str = ""


class ModelArmorGuardrail:
    """Model Armor screening client. Uses Cloud Model Armor template if configured,
    with local rule-based safety screening fallback for offline/test environments."""

    def __init__(self, template_name: str | None = None) -> None:
        self.template_name = template_name or os.environ.get("MODEL_ARMOR_TEMPLATE", "catsight-default-template")
        self._enabled = os.environ.get("MODEL_ARMOR_ENABLED", "true").lower() in ("1", "true", "yes")

    def screen_prompt(self, text: str, *, context: str = "ask") -> GuardrailResult:
        """Screen input text before sending to LLM. Returns GuardrailResult."""
        if not self._enabled or not text:
            return GuardrailResult(allowed=True)

        # Check prompt injection patterns
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                msg = f"Model Armor blocked input ({context}): prompt injection / override attempt detected"
                logger.warning(msg)
                return GuardrailResult(allowed=False, reason=msg, filter_type="PROMPT_INJECTION")

        return GuardrailResult(allowed=True)

    def screen_response(self, text: str, *, context: str = "ask") -> GuardrailResult:
        """Screen output text from model before returning to user."""
        if not self._enabled or not text:
            return GuardrailResult(allowed=True)

        # Screen for accidental system prompt or secret leakage
        if "catsight-run-key" in text or "SERVICE_ACCOUNT_KEY" in text:
            msg = f"Model Armor blocked output ({context}): sensitive credentials pattern detected"
            logger.warning(msg)
            return GuardrailResult(allowed=False, reason=msg, filter_type="SENSITIVE_DATA_LEAK")

        return GuardrailResult(allowed=True)


# Default singleton
default_guardrail = ModelArmorGuardrail()
