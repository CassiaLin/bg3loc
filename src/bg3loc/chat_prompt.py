from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable

from bg3loc.prompt_assembly import AssembledTranslationPrompt


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


def render_chat_messages(prompt: AssembledTranslationPrompt) -> tuple[ChatMessage, ChatMessage]:
    locale_line = "Translate the supplied Baldur's Gate 3 localization text."
    if prompt.source_locale and prompt.target_locale:
        locale_line = (
            f"Translate the supplied Baldur's Gate 3 localization text "
            f"from {prompt.source_locale} to {prompt.target_locale}."
        )

    system_lines = [
        locale_line,
        "Return only the translated text. Do not add explanations, labels, or quotation marks.",
        "",
        "Rules:",
    ]
    system_lines.extend(f"- {rule}" for rule in prompt.instructions)

    if prompt.glossary:
        system_lines.extend(("", "Glossary:"))
        system_lines.extend(
            f"- {entry.source} => {entry.target}"
            for entry in prompt.glossary
        )

    if prompt.protected_tokens:
        system_lines.extend(("", "Protected runtime tokens (preserve exactly):"))
        system_lines.extend(f"- {token}" for token in prompt.protected_tokens)

    user_payload = {
        "ContentUid": prompt.content_uid,
        "primaryCategory": prompt.primary_category,
        "contextGroupKeys": list(prompt.context_group_keys),
        "sourceText": prompt.source_text,
    }

    return (
        ChatMessage(role="system", content="\n".join(system_lines)),
        ChatMessage(
            role="user",
            content=json.dumps(
                user_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )


def chat_messages_fingerprint(messages: tuple[ChatMessage, ...]) -> str:
    import hashlib

    raw = json.dumps(
        [{"role": message.role, "content": message.content} for message in messages],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
