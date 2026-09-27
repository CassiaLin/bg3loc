from __future__ import annotations

import unittest
from datetime import datetime, timezone
from urllib import error

from bg3loc.execution_runner import TranslationFailure, TranslationSuccess
from bg3loc.prompt_assembly import TranslationRuleSet
from bg3loc.providers.openai_compatible import (
    OpenAICompatibleChatConfig,
    OpenAICompatibleChatProvider,
)
from bg3loc.translation_request import TranslationRequest


class FakeTransport:
    def __init__(self, status=200, payload=None, exc=None, headers=None):
        self.status = status
        self.payload = payload if payload is not None else {}
        self.exc = exc
        self.headers = headers
        self.calls = []

    def post_json(self, *, url, headers, payload, timeout_seconds):
        self.calls.append({
            "url": url,
            "headers": dict(headers),
            "payload": payload,
            "timeout_seconds": timeout_seconds,
        })
        if self.exc is not None:
            raise self.exc
        if self.headers is None:
            return self.status, self.payload
        return self.status, self.payload, self.headers


def request_for(text="Hello {PLAYER} %s") -> TranslationRequest:
    return TranslationRequest(
        content_uid="uid-a",
        batch_id="bark-0001",
        attempt_number=1,
        input_hash="input-a",
        source_text=text,
        primary_category="bark",
        canonical_group_key="dialog:act1/foo",
        context_group_keys=("dialog:act1/foo", "speaker:a"),
        protected_tokens=("{PLAYER}", "%s") if "{PLAYER}" in text else (),
    )


def ruleset() -> TranslationRuleSet:
    return TranslationRuleSet(
        version="rules-v1",
        common_rules=("Preserve meaning.", "Preserve protected tokens exactly."),
        category_rules={"bark": ("Keep bark lines concise.",)},
    )


class TestOpenAICompatibleProvider(unittest.TestCase):
    def test_provider_usage_is_exposed_with_canonical_and_alias_fields(self):
        cases = (
            (
                {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                (100, 20, 120),
            ),
            ({"input_tokens": 75, "output_tokens": 15}, (75, 15, None)),
            ({}, None),
        )
        for usage, expected in cases:
            with self.subTest(usage=usage):
                provider = OpenAICompatibleChatProvider(
                    config=OpenAICompatibleChatConfig(
                        base_url="https://example.test", model="m"
                    ),
                    ruleset=ruleset(),
                    transport=FakeTransport(
                        payload={
                            "id": "req-usage",
                            "choices": [
                                {"message": {"content": "你好 {PLAYER} %s"}}
                            ],
                            "usage": usage,
                        }
                    ),
                )
                result = provider(request_for())
                assert isinstance(result, TranslationSuccess)
                actual = (
                    None
                    if result.usage is None
                    else (
                        result.usage.prompt_tokens,
                        result.usage.completion_tokens,
                        result.usage.total_tokens,
                    )
                )
                self.assertEqual(actual, expected)

    def test_failure_usage_is_exposed_only_when_provider_reports_it(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test", model="m"
            ),
            ruleset=ruleset(),
            transport=FakeTransport(
                status=429,
                payload={
                    "error": {"message": "temporary"},
                    "usage": {"prompt_tokens": 9, "completion_tokens": 0},
                },
            ),
        )
        result = provider(request_for())
        assert isinstance(result, TranslationFailure)
        self.assertIsNotNone(result.usage)
        assert result.usage is not None
        self.assertEqual(result.usage.prompt_tokens, 9)
        self.assertEqual(result.usage.completion_tokens, 0)
        self.assertIsNone(result.usage.total_tokens)

    def test_success_builds_standard_chat_request(self):
        transport = FakeTransport(
            status=200,
            payload={
                "id": "req-123",
                "choices": [
                    {"message": {"content": "你好 {PLAYER} %s"}}
                ],
            },
        )
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="http://localhost:8080",
                model="local-model",
                api_key="secret-key",
                timeout_seconds=12.5,
                max_output_tokens=256,
                temperature=0.2,
            ),
            ruleset=ruleset(),
            transport=transport,
        )

        result = provider(request_for())

        self.assertIsInstance(result, TranslationSuccess)
        assert isinstance(result, TranslationSuccess)
        self.assertEqual(result.text, "你好 {PLAYER} %s")
        self.assertEqual(result.provider_request_id, "req-123")

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["url"], "http://localhost:8080/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["timeout_seconds"], 12.5)

        payload = call["payload"]
        self.assertEqual(payload["model"], "local-model")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(
            [message["role"] for message in payload["messages"]],
            ["system", "user"],
        )
        system = payload["messages"][0]["content"]
        user = payload["messages"][1]["content"]
        self.assertIn("Preserve meaning.", system)
        self.assertIn("Keep bark lines concise.", system)
        self.assertIn("{PLAYER}", system)
        self.assertIn("%s", system)
        self.assertIn('"sourceText":"Hello {PLAYER} %s"', user)
        self.assertNotIn("secret-key", str(payload))

    def test_429_and_5xx_are_retryable(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                provider = OpenAICompatibleChatProvider(
                    config=OpenAICompatibleChatConfig(
                        base_url="https://example.test",
                        model="m",
                    ),
                    ruleset=ruleset(),
                    transport=FakeTransport(
                        status=status,
                        payload={"error": {"message": "temporary"}},
                    ),
                )
                result = provider(request_for())
                self.assertIsInstance(result, TranslationFailure)
                assert isinstance(result, TranslationFailure)
                self.assertTrue(result.retryable)
                self.assertEqual(result.error_code, f"HTTP_{status}")

    def test_retry_after_delta_seconds_is_exposed_as_signal(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(base_url="https://example.test", model="m"),
            ruleset=ruleset(),
            transport=FakeTransport(
                status=429,
                payload={"error": {"message": "temporary"}},
                headers={"Retry-After": "10"},
            ),
        )
        result = provider(request_for())
        assert isinstance(result, TranslationFailure)
        self.assertEqual(result.retry_after_seconds, 10)

    def test_retry_after_http_date_is_exposed_as_signal(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(base_url="https://example.test", model="m"),
            ruleset=ruleset(),
            transport=FakeTransport(
                status=503,
                payload={"error": {"message": "temporary"}},
                headers={"retry-after": "Mon, 28 Sep 2026 00:00:15 GMT"},
            ),
            clock=lambda: datetime(2026, 9, 28, tzinfo=timezone.utc),
        )
        result = provider(request_for())
        assert isinstance(result, TranslationFailure)
        self.assertEqual(result.retry_after_seconds, 15)

    def test_4xx_configuration_failure_is_final(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test",
                model="m",
            ),
            ruleset=ruleset(),
            transport=FakeTransport(
                status=400,
                payload={"error": {"message": "bad request"}},
            ),
        )
        result = provider(request_for())
        self.assertIsInstance(result, TranslationFailure)
        assert isinstance(result, TranslationFailure)
        self.assertFalse(result.retryable)
        self.assertEqual(result.error_code, "HTTP_400")

    def test_transport_error_is_retryable(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test",
                model="m",
            ),
            ruleset=ruleset(),
            transport=FakeTransport(exc=error.URLError("offline")),
        )
        result = provider(request_for())
        self.assertIsInstance(result, TranslationFailure)
        assert isinstance(result, TranslationFailure)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "PROVIDER_TRANSPORT_ERROR")

    def test_invalid_response_is_retryable(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test",
                model="m",
            ),
            ruleset=ruleset(),
            transport=FakeTransport(status=200, payload={"choices": []}),
        )
        result = provider(request_for())
        self.assertIsInstance(result, TranslationFailure)
        assert isinstance(result, TranslationFailure)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "PROVIDER_RESPONSE_INVALID")

    def test_empty_output_is_retryable(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test",
                model="m",
            ),
            ruleset=ruleset(),
            transport=FakeTransport(
                status=200,
                payload={"choices": [{"message": {"content": "   "}}]},
            ),
        )
        result = provider(request_for())
        self.assertIsInstance(result, TranslationFailure)
        assert isinstance(result, TranslationFailure)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "PROVIDER_OUTPUT_EMPTY")

    def test_protected_token_loss_is_retryable_validation_failure(self):
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test",
                model="m",
            ),
            ruleset=ruleset(),
            transport=FakeTransport(
                status=200,
                payload={
                    "id": "req-bad",
                    "choices": [{"message": {"content": "你好"}}],
                },
            ),
        )
        result = provider(request_for())
        self.assertIsInstance(result, TranslationFailure)
        assert isinstance(result, TranslationFailure)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "OUTPUT_VALIDATION_FAILED")
        self.assertEqual(result.provider_request_id, "req-bad")

    def test_missing_category_rule_fails_before_transport(self):
        transport = FakeTransport(
            status=200,
            payload={"choices": [{"message": {"content": "unused"}}]},
        )
        provider = OpenAICompatibleChatProvider(
            config=OpenAICompatibleChatConfig(
                base_url="https://example.test",
                model="m",
            ),
            ruleset=TranslationRuleSet(
                version="rules-v1",
                common_rules=("Preserve meaning.",),
                category_rules={"item": ("Item rule.",)},
            ),
            transport=transport,
        )
        result = provider(request_for())
        self.assertIsInstance(result, TranslationFailure)
        assert isinstance(result, TranslationFailure)
        self.assertFalse(result.retryable)
        self.assertEqual(result.error_code, "PROMPT_ASSEMBLY_ERROR")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
