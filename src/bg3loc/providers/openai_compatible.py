from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import socket
from typing import Callable, Mapping, Protocol
from urllib import error, request

from bg3loc.chat_prompt import render_chat_messages
from bg3loc.execution_runner import (
    ProviderTokenUsage,
    TranslationFailure,
    TranslationOutcome,
    TranslationSuccess,
)
from bg3loc.prompt_assembly import TranslationRuleSet, assemble_translation_prompt
from bg3loc.protected_syntax import validate_protected_syntax
from bg3loc.translation_request import TranslationRequest


class JsonHttpTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> (
        tuple[int, dict[str, object]]
        | tuple[int, dict[str, object], Mapping[str, str]]
    ):
        ...


class UrllibJsonTransport:
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, object]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("provider response must be a JSON object")
                return int(response.status), parsed, dict(response.headers.items())
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"error": raw}
            if not isinstance(parsed, dict):
                parsed = {"error": parsed}
            response_headers = dict(exc.headers.items()) if exc.headers is not None else {}
            return int(exc.code), parsed, response_headers


@dataclass(frozen=True, slots=True)
class OpenAICompatibleChatConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 120.0
    max_output_tokens: int | None = None
    temperature: float | None = None


def openai_compatible_execution_config_hash(
    config: OpenAICompatibleChatConfig,
    ruleset: TranslationRuleSet,
) -> str:
    payload = {
        "provider": "openai-compatible",
        "baseUrl": config.base_url.rstrip("/"),
        "model": config.model,
        "timeoutSeconds": float(config.timeout_seconds),
        "maxOutputTokens": config.max_output_tokens,
        "temperature": config.temperature,
        "rulesetFingerprint": ruleset.fingerprint(),
        "rulesetVersion": ruleset.version,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class OpenAICompatibleChatProvider:
    def __init__(
        self,
        *,
        config: OpenAICompatibleChatConfig,
        ruleset: TranslationRuleSet,
        transport: JsonHttpTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.ruleset = ruleset
        self.transport = transport or UrllibJsonTransport()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def __call__(self, translation_request: TranslationRequest) -> TranslationOutcome:
        if not self.config.base_url.strip():
            return TranslationFailure(
                error_code="PROVIDER_CONFIG_INVALID",
                error_message="base_url is empty",
                retryable=False,
            )
        if not self.config.model.strip():
            return TranslationFailure(
                error_code="PROVIDER_CONFIG_INVALID",
                error_message="model is empty",
                retryable=False,
            )

        try:
            assembled = assemble_translation_prompt(translation_request, self.ruleset)
            messages = render_chat_messages(assembled)
        except Exception as exc:
            return TranslationFailure(
                error_code="PROMPT_ASSEMBLY_ERROR",
                error_message=f"{type(exc).__name__}: {exc}",
                retryable=False,
            )

        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": False,
        }
        if self.config.max_output_tokens is not None:
            payload["max_tokens"] = int(self.config.max_output_tokens)
        if self.config.temperature is not None:
            payload["temperature"] = float(self.config.temperature)

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        url = self.config.base_url.rstrip("/") + "/v1/chat/completions"

        try:
            transport_result = self.transport.post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_seconds=float(self.config.timeout_seconds),
            )
            if len(transport_result) == 2:
                status, response = transport_result
                response_headers: Mapping[str, str] = {}
            else:
                status, response, response_headers = transport_result
        except (error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            return TranslationFailure(
                error_code="PROVIDER_TRANSPORT_ERROR",
                error_message=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )
        except Exception as exc:
            return TranslationFailure(
                error_code="PROVIDER_TRANSPORT_ERROR",
                error_message=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )

        request_id = str(response.get("id", "")) or None
        usage = _provider_usage(response)

        if status == 429 or 500 <= status <= 599:
            return TranslationFailure(
                error_code=f"HTTP_{status}",
                error_message=_provider_error_message(response, status),
                retryable=True,
                provider_request_id=request_id,
                retry_after_seconds=_retry_after_seconds(
                    response_headers, now=self.clock()
                ),
                usage=usage,
            )
        if status < 200 or status >= 300:
            return TranslationFailure(
                error_code=f"HTTP_{status}",
                error_message=_provider_error_message(response, status),
                retryable=False,
                provider_request_id=request_id,
                usage=usage,
            )

        try:
            text = _extract_chat_content(response)
        except ValueError as exc:
            return TranslationFailure(
                error_code="PROVIDER_RESPONSE_INVALID",
                error_message=str(exc),
                retryable=True,
                provider_request_id=request_id,
                usage=usage,
            )

        if not text.strip():
            return TranslationFailure(
                error_code="PROVIDER_OUTPUT_EMPTY",
                error_message="provider returned empty translated text",
                retryable=True,
                provider_request_id=request_id,
                usage=usage,
            )

        issues = validate_protected_syntax(
            translation_request.protected_tokens,
            text,
        )
        if issues:
            detail = "; ".join(
                f"{issue.kind}:{','.join(issue.details)}"
                for issue in issues
            )
            return TranslationFailure(
                error_code="OUTPUT_VALIDATION_FAILED",
                error_message=detail or "protected syntax validation failed",
                retryable=True,
                provider_request_id=request_id,
                usage=usage,
            )

        return TranslationSuccess(
            text=text,
            provider_request_id=request_id,
            usage=usage,
        )


def _extract_chat_content(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("provider response missing choices[0]")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("provider response choices[0] is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("provider response missing choices[0].message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("provider response missing string choices[0].message.content")
    return content


def _provider_error_message(payload: dict[str, object], status: int) -> str:
    err = payload.get("error")
    if isinstance(err, dict):
        message = err.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(err, str) and err:
        return err
    return f"provider returned HTTP {status}"


def _retry_after_seconds(
    headers: Mapping[str, str], *, now: datetime
) -> float | None:
    raw = next(
        (str(value).strip() for key, value in headers.items() if key.casefold() == "retry-after"),
        "",
    )
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - current).total_seconds())


def _provider_usage(payload: dict[str, object]) -> ProviderTokenUsage | None:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return None

    def token_value(primary: str, alias: str | None = None) -> int | None:
        value = raw.get(primary)
        if value is None and alias is not None:
            value = raw.get(alias)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    usage = ProviderTokenUsage(
        prompt_tokens=token_value("prompt_tokens", "input_tokens"),
        completion_tokens=token_value("completion_tokens", "output_tokens"),
        total_tokens=token_value("total_tokens"),
    )
    if (
        usage.prompt_tokens is None
        and usage.completion_tokens is None
        and usage.total_tokens is None
    ):
        return None
    return usage
