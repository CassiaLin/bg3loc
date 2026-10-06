"""Canonical item and sealed execution identities; no input lookup or migration."""
from dataclasses import dataclass
import hashlib
import json

from bg3loc import prompt_assembly
from bg3loc.same_entity_context import (
    SCHEMA_VERSION, POLICY_VERSION, SameEntityContext, validate_same_entity_context,
)

INPUT_IDENTITY_VERSION = "translation-input/2"


def identity_fingerprint(payload: dict) -> str:
    # This is the exact legacy serialization, retained for the absent branch.
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def prompt_policy_fingerprint() -> str:
    from bg3loc import chat_prompt
    if chat_prompt.SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS != prompt_assembly.SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS:
        raise RuntimeError("inconsistent local context rendering safety policy")
    return identity_fingerprint({"promptRendererVersion": prompt_assembly.SAME_ENTITY_PROMPT_VERSION,
                                 "safetyInstructions": list(prompt_assembly.SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS)})


@dataclass(frozen=True, slots=True)
class TranslationInputParameters:
    prompt_version: str
    ruleset_fingerprint: str = ""
    source_locale: str = ""
    target_locale: str = ""


def translation_input_hash(*, content_uid: str, source_text: str, category: str,
                           protected_syntax: object, parameters: TranslationInputParameters,
                           context: SameEntityContext | None = None) -> str:
    """Absent: exact old payload. Present: conditional versioned context binding.

    No workspace paths, timestamps, summary, partition or global corpus digest
    enter the item hash. The prepared fingerprint binds the canonical context;
    rendering version and fixed policy digest bind its effective prompt semantics.
    """
    validate_same_entity_context(context, content_uid=content_uid, category=category, source_text=source_text)
    payload = {"ContentUid": content_uid, "SourceText": source_text, "primaryCategory": category,
               "protectedSyntax": protected_syntax, "promptVersion": parameters.prompt_version,
               "rulesetFingerprint": parameters.ruleset_fingerprint,
               "sourceLocale": parameters.source_locale, "targetLocale": parameters.target_locale}
    if context is not None:
        payload.update(inputIdentityVersion=INPUT_IDENTITY_VERSION, sameEntityContext={
            "schemaVersion": context.schema_version, "policyVersion": context.policy_version,
            "contextFingerprint": context.context_fingerprint,
            "promptRendererVersion": prompt_assembly.SAME_ENTITY_PROMPT_VERSION,
            "promptPolicyFingerprint": prompt_policy_fingerprint(),
        })
    return identity_fingerprint(payload)


def execution_context_contract(material_fingerprint: str) -> dict:
    result = {"inputIdentityVersion": INPUT_IDENTITY_VERSION, "schemaVersion": SCHEMA_VERSION,
              "policyVersion": POLICY_VERSION, "promptRendererVersion": prompt_assembly.SAME_ENTITY_PROMPT_VERSION,
              "promptPolicyFingerprint": prompt_policy_fingerprint(),
              "sameEntityContextMaterialFingerprint": material_fingerprint}
    return {**result, "contextContractFingerprint": identity_fingerprint(result)}


def validate_execution_context_contract(value: dict, material_fingerprint: str) -> None:
    if value != execution_context_contract(material_fingerprint):
        raise RuntimeError("unsupported/mismatched execution context contract; use fresh prepare")
