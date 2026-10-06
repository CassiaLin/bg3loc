"""Immutable identities of the actual messages about to enter transport."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptProvenance:
    input_hash: str
    context_fingerprint: str | None
    effective_prompt_hash: str
    chat_messages_fingerprint: str
    prompt_renderer_version: str | None
