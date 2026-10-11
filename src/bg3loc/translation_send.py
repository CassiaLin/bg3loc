"""Single-render actual-send preparation; this module never calls transport."""
from dataclasses import dataclass

from bg3loc.chat_prompt import ChatMessage, render_chat_messages, chat_messages_fingerprint
from bg3loc.prompt_assembly import AssembledTranslationPrompt, TranslationRuleSet, assemble_translation_prompt, SAME_ENTITY_PROMPT_VERSION
from bg3loc.dialogue_prompt import DIALOGUE_PROMPT_VERSION
from bg3loc.prompt_provenance import PromptProvenance
from bg3loc.translation_request import TranslationRequest


def provenance_for_prepared_send(request: TranslationRequest, prompt: AssembledTranslationPrompt,
                                 messages: tuple[ChatMessage, ...], *, input_parameters=None) -> PromptProvenance:
    dialogue = request.dialogue_context
    same = request.same_entity_context
    if dialogue is not None:
        from bg3loc.translation_identity import translation_input_hash
        if input_parameters is None:
            raise ValueError("HD prepared send requires bound input parameters")
        expected = translation_input_hash(content_uid=request.content_uid, source_text=request.source_text,
            category=request.primary_category, protected_syntax=None,
            parameters=input_parameters, dialogue_context=dialogue)
        if expected != request.input_hash:
            raise ValueError("prepared send input identity mismatch")
    return PromptProvenance(request.input_hash, None if same is None else same.context_fingerprint,
        prompt.effective_prompt_hash, chat_messages_fingerprint(messages),
        DIALOGUE_PROMPT_VERSION if dialogue is not None else SAME_ENTITY_PROMPT_VERSION if same is not None else None,
        None if dialogue is None else dialogue.context_fingerprint)


@dataclass(frozen=True, slots=True)
class PreparedTranslationSend:
    prompt: AssembledTranslationPrompt
    messages: tuple[ChatMessage, ...]
    provenance: PromptProvenance


def prepare_translation_send(request: TranslationRequest, ruleset: TranslationRuleSet) -> PreparedTranslationSend:
    from bg3loc.translation_identity import TranslationInputParameters
    prompt = assemble_translation_prompt(request, ruleset)
    messages = render_chat_messages(prompt)
    provenance = provenance_for_prepared_send(request, prompt, messages, input_parameters=TranslationInputParameters(
        ruleset.version, ruleset.fingerprint(), ruleset.source_locale, ruleset.target_locale))
    return PreparedTranslationSend(prompt, messages, provenance)
