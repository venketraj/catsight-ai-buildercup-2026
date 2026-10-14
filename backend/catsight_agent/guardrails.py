"""Prompt and response screening for follow-up questions (FR-ASK, WAF security).

Two layers, and every result says which one decided:

1. ``local``: a small regex filter for the most common prompt-injection
   phrasings, plus a check that the answer does not echo credential names.
   Free, instant, offline, and the only layer in tests and local runs.
2. ``model-armor``: Google Cloud Model Armor. When ``MODEL_ARMOR_TEMPLATE`` is
   set, the question goes to ``sanitizeUserPrompt`` and the answer to
   ``sanitizeModelResponse`` on that template (prompt injection and jailbreak,
   malicious URLs, responsible-AI filters, as the template configures them).

Fail-open by design: if Model Armor errors or times out, the request is
allowed on the local layer's verdict and ``model_armor_unavailable`` is
logged. CatSight's answers are grounded in the engine's figures and checked
citations, so a short Model Armor outage should degrade screening, not take
the question feature down. The choice is recorded in ARCHITECTURE.md.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("catsight.guardrails")

__all__ = ["GuardrailResult", "PromptGuard", "LOCAL", "MODEL_ARMOR"]

#: Layer names, as they appear in results, logs and /health.
LOCAL = "local"
MODEL_ARMOR = "model-armor"

#: Common prompt-injection and override phrasings. Deliberately narrow: this
#: layer exists to catch the obvious cases for free, not to be a classifier.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I),
    re.compile(r"(?:reveal|show|print|leak)\s+(?:the\s+)?(?:system\s+prompt|hidden\s+instructions?)", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a\s+|an\s+)?(?:unfiltered|jailbroken|dan|evil|developer\s+mode)", re.I),
    re.compile(r"<system>.*?</system>", re.I | re.S),
    re.compile(r"assistant\s*:\s*let's\s+bypass", re.I),
    re.compile(r"base64\s+decode\s+and\s+execute", re.I),
]

#: Names that must never appear in an answer shown to a user.
_SECRET_MARKERS = ("catsight-run-key", "SERVICE_ACCOUNT_KEY")


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str = ""
    #: What matched: LOCAL_INJECTION_FILTER, LOCAL_SECRET_FILTER or MODEL_ARMOR.
    filter_type: str = ""
    #: The layer that decided a block, or the layers that ran on an allow
    #: ("local", "local+model-armor").
    layer: str = LOCAL
    #: True when Model Armor was configured but could not be reached.
    model_armor_unavailable: bool = False


class PromptGuard:
    """The local filter, then Model Armor when a template is configured.

    ``client`` is a ``google.cloud.modelarmor_v1.ModelArmorClient`` or any
    object with the same two methods; tests pass a fake. When it is omitted
    and a template is set, the real client is built on first use.
    """

    def __init__(
        self,
        *,
        project: str | None = None,
        location: str = "us-central1",
        template_id: str | None = None,
        client: Any = None,
        timeout_s: float = 3.0,
    ) -> None:
        self.project = project
        self.location = location
        self.template_id = template_id or None
        self.timeout_s = timeout_s
        self._client = client

    @classmethod
    def from_settings(cls, config: Any) -> "PromptGuard":
        return cls(project=config.project, location=config.model_armor_location,
                   template_id=config.model_armor_template)

    # ------------------------------------------------------------------ #

    @property
    def model_armor_enabled(self) -> bool:
        return bool(self.project and self.template_id)

    @property
    def layers(self) -> str:
        """What /health reports: which layers screen a question."""
        return f"{LOCAL}+{MODEL_ARMOR}" if self.model_armor_enabled else LOCAL

    @property
    def template_name(self) -> str:
        return f"projects/{self.project}/locations/{self.location}/templates/{self.template_id}"

    def _armor(self):
        if self._client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import modelarmor_v1

            self._client = modelarmor_v1.ModelArmorClient(
                transport="rest",
                client_options=ClientOptions(
                    api_endpoint=f"modelarmor.{self.location}.rep.googleapis.com"),
            )
        return self._client

    def _armor_match(self, text: str, *, prompt: bool) -> tuple[bool | None, list[str]]:
        """(matched, filter names) from Model Armor; (None, []) if unreachable."""
        try:
            from google.cloud import modelarmor_v1

            client = self._armor()
            item = modelarmor_v1.DataItem(text=text)
            if prompt:
                response = client.sanitize_user_prompt(
                    request=modelarmor_v1.SanitizeUserPromptRequest(
                        name=self.template_name, user_prompt_data=item),
                    timeout=self.timeout_s)
            else:
                response = client.sanitize_model_response(
                    request=modelarmor_v1.SanitizeModelResponseRequest(
                        name=self.template_name, model_response_data=item),
                    timeout=self.timeout_s)
            result = response.sanitization_result
            matched = result.filter_match_state == modelarmor_v1.FilterMatchState.MATCH_FOUND
            return matched, _matched_filters(result) if matched else []
        except Exception as exc:  # noqa: BLE001 - fail open, logged
            logger.warning("model_armor_unavailable: %s", type(exc).__name__)
            return None, []

    # ------------------------------------------------------------------ #

    def screen_prompt(self, text: str, *, context: str = "ask") -> GuardrailResult:
        """Screen a user's question before it reaches Gemini."""
        if not text:
            return GuardrailResult(allowed=True)
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                msg = (f"Question blocked by the local prompt-injection filter ({context}): "
                       "it reads as an attempt to override instructions.")
                logger.warning(msg)
                return GuardrailResult(False, msg, "LOCAL_INJECTION_FILTER", LOCAL)
        return self._screen_with_armor(text, context=context, prompt=True)

    def screen_response(self, text: str, *, context: str = "ask") -> GuardrailResult:
        """Screen Gemini's answer before it is shown."""
        if not text:
            return GuardrailResult(allowed=True)
        if any(marker in text for marker in _SECRET_MARKERS):
            msg = f"Answer withheld by the local secret filter ({context}): it names a credential."
            logger.warning(msg)
            return GuardrailResult(False, msg, "LOCAL_SECRET_FILTER", LOCAL)
        return self._screen_with_armor(text, context=context, prompt=False)

    def _screen_with_armor(self, text: str, *, context: str, prompt: bool) -> GuardrailResult:
        if not self.model_armor_enabled:
            return GuardrailResult(allowed=True, layer=LOCAL)
        matched, filters = self._armor_match(text, prompt=prompt)
        if matched is None:
            return GuardrailResult(allowed=True, layer=LOCAL, model_armor_unavailable=True)
        if matched:
            what = "Question" if prompt else "Answer"
            msg = (f"{what} blocked by Google Cloud Model Armor ({context}"
                   + (f": {', '.join(filters)}" if filters else "") + ").")
            logger.warning(msg)
            return GuardrailResult(False, msg, "MODEL_ARMOR", MODEL_ARMOR)
        return GuardrailResult(allowed=True, layer=f"{LOCAL}+{MODEL_ARMOR}")


def _matched_filters(result: Any) -> list[str]:
    """Names of the Model Armor filters that matched, e.g. pi_and_jailbreak."""
    names: list[str] = []
    try:
        for name, entry in dict(result.filter_results).items():
            for field_name in ("pi_and_jailbreak_filter_result", "malicious_uri_filter_result",
                               "rai_filter_result", "sdp_filter_result", "csam_filter_filter_result"):
                sub = getattr(entry, field_name, None)
                state = getattr(sub, "match_state", None)
                if state is not None and getattr(state, "name", str(state)) == "MATCH_FOUND":
                    names.append(field_name.removesuffix("_filter_result"))
    except Exception:  # noqa: BLE001 - names are a nicety, never a failure
        return names
    return sorted(set(names))
