"""Only fictional markers; no sockets or paid provider requests."""
from dataclasses import asdict
import io
import json
import sqlite3
import socket
import traceback
from email.message import Message
from contextlib import redirect_stdout
from urllib import error
from unittest.mock import patch, MagicMock

import pytest

from bg3loc.cli import main
from bg3loc.execution_runner import TranslationFailure, RetryPacingPolicy, run_worker
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.providers.openai_compatible import (
    OpenAICompatibleChatConfig, OpenAICompatibleChatProvider, UrllibJsonTransport,
)
from test_openai_compatible_provider import FakeTransport, request_for, ruleset
import test_production_execution as execution_fixture

MARKERS = ('FICTIONAL_KEY_A2_927', 'FICTIONAL_PROMPT_A2_831',
           'FICTIONAL_SOURCE_A2_513', 'FICTIONAL_TRANSLATION_A2_624')
ECHO = 'Authorization: Bearer ' + ' '.join(MARKERS)


def provider(transport):
    return OpenAICompatibleChatProvider(
        config=OpenAICompatibleChatConfig(base_url='https://example.invalid',
                                         model='synthetic', api_key=MARKERS[0]),
        ruleset=ruleset(), transport=transport)


def assert_private(value):
    text = str(value)
    for marker in MARKERS:
        assert marker not in text


@pytest.mark.parametrize('status', [400, 401, 403, 429, 500])
@pytest.mark.parametrize('body', [
    {'error': {'message': ECHO, 'custom': ECHO}, 'id': ECHO},
    {'error': ECHO * 10000, 'id': ECHO},
    {'unknownEchoField': ECHO, 'id': {'nested': ECHO}},
], ids=['echo-message', 'huge-error', 'unknown-custom-echo'])
def test_http_failure_is_private_with_unchanged_classification(status, body):
    result = provider(FakeTransport(status=status, payload=body,
                                   headers={'Retry-After': '7', 'Authorization': ECHO}))(request_for())
    assert isinstance(result, TranslationFailure)
    assert result.error_code == f'HTTP_{status}'
    assert result.retryable == (status == 429 or status >= 500)
    assert result.retry_after_seconds == (7 if result.retryable else None)
    assert len(result.error_message) <= 160
    assert_private(repr(result))
    assert_private(json.dumps(asdict(result)))


@pytest.mark.parametrize('exc', [TimeoutError(ECHO), error.URLError(ECHO),
                               ConnectionError(ECHO), OSError(ECHO), ValueError(ECHO)])
def test_transport_exception_is_private(exc):
    result = provider(FakeTransport(exc=exc))(request_for())
    assert result.error_code == 'PROVIDER_TRANSPORT_ERROR'
    assert result.retryable
    assert_private(result)


def test_cli_failure_persistence_report_and_resume(tmp_path, caplog):
    captured = io.StringIO()
    with redirect_stdout(captured):
        workspace, db = execution_fixture.TestProductionExecution()._workspace(tmp_path)
        args = ['production', 'execute-openai-compatible', '--workspace', str(workspace),
                '--base-url', 'https://example.invalid', '--model', 'synthetic',
                '--run-id', 'privacy-run', '--worker-id', 'privacy-worker',
                '--max-items', '1', '--max-attempts', '3']
        with patch.object(UrllibJsonTransport, 'post_json', return_value=(
                500, {'error': {'message': ECHO}, 'id': ECHO})):
            assert main(args) == 0
        # Resume an actual failed-retryable item, then fail finally at its limit.
        args[args.index('privacy-run')] = 'privacy-resume'
        args[args.index('3')] = '2'
        with patch.object(UrllibJsonTransport, 'post_json', side_effect=TimeoutError(ECHO)):
            assert main(args) == 0
        report = tmp_path / 'report.json'
        assert main(['production', 'report', '--workspace', str(workspace), '--json', str(report)]) == 0
        assert_private(report.read_text(encoding='utf-8'))
    with sqlite3.connect(db) as conn:
        attempts = conn.execute('SELECT * FROM attempts').fetchall()
        assert len(attempts) == 2
        assert [r[0] for r in conn.execute('SELECT outcome FROM attempts ORDER BY attempt_id')] == [
            'failed-retryable', 'failed-final']
        assert_private(attempts)
    assert_private(db.read_bytes())
    assert_private(captured.getvalue())
    assert_private(caplog.text)


@pytest.mark.parametrize('fragment', [marker[:17] for marker in MARKERS] + ['unknown_custom_echo_761'])
def test_partial_and_unrecognized_content_is_not_redacted_by_secret_matching(fragment):
    result = provider(FakeTransport(status=500, payload={
        'id': fragment, 'error': {'message': fragment, 'custom': fragment}}))(request_for())
    assert fragment not in repr(result)
    assert result.error_code == 'HTTP_500' and result.retryable


@pytest.mark.parametrize('body', [b'not json', b'\xff\xfe', b'[]'])
def test_malformed_native_success_body_has_safe_exception_and_original_retry_route(body):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = body + (ECHO.encode() if body == b'not json' else b'')
    response.status = 200
    with patch('bg3loc.providers.openai_compatible.request.urlopen', return_value=response):
        result = provider(UrllibJsonTransport())(request_for())
    assert result.error_code == 'PROVIDER_TRANSPORT_ERROR'
    assert result.retryable
    assert_private(result)


def test_failure_dto_and_direct_store_cannot_bypass_boundary(tmp_path):
    result = TranslationFailure(ECHO, ECHO, True, ECHO, retry_after_seconds=7)
    assert_private(result)
    assert RetryPacingPolicy().retry_delay(result, streak=1) == 7
    with redirect_stdout(io.StringIO()):
        _, db = execution_fixture.TestProductionExecution()._workspace(tmp_path)
    store = TranslationExecutionStore(db)
    store.start_run(run_id='direct', batch_plan_fingerprint='fp-production-execution',
                    provider='synthetic', model='synthetic',
                    prompt_version='synthetic', execution_config_hash='synthetic', started_at='2026-10-11T00:00:00Z')
    claim = store.claim_next(run_id='direct', worker_id='w', started_at='2026-10-11T00:00:00Z',
                             lease_expires_at='2026-10-11T00:05:00Z', max_attempts=3)
    store.complete_failure(attempt_id=claim.attempt_id, worker_id='w', error_code=ECHO,
                           error_message=ECHO, provider_request_id=ECHO, retryable=True,
                           max_attempts=3, finished_at='2026-10-11T00:00:01Z')
    assert_private(store.get_attempts(claim.content_uid))
    assert_private(db.read_bytes())


@pytest.mark.parametrize('status', [400, 401, 403, 429, 500])
@pytest.mark.parametrize('body', [ECHO.encode(), b'[{"bad": true}]',
                                json.dumps({'error': ECHO, 'usage': {'prompt_tokens': 9}}).encode(),
                                ECHO.encode() * 10000], ids=['non-json', 'non-object', 'json-usage', 'oversized'])
def test_native_http_error_discards_body_headers_and_id(status, body):
    headers = Message()
    headers['Retry-After'] = '11'
    headers['Authorization'] = ECHO
    native = error.HTTPError('https://example.invalid/' + ECHO, status, ECHO,
                             headers, io.BytesIO(body))
    with patch('bg3loc.providers.openai_compatible.request.urlopen', side_effect=native):
        result = provider(UrllibJsonTransport())(request_for())
    assert result.error_code == f'HTTP_{status}'
    assert result.retryable == (status == 429 or status == 500)
    assert result.retry_after_seconds == (11 if result.retryable else None)
    assert_private(result)
    assert native.closed


@pytest.mark.parametrize('exc', [error.URLError(ECHO), TimeoutError(ECHO),
                               socket.gaierror(ECHO), ConnectionError(ECHO)])
def test_native_transport_exception_serialization_has_no_echo(exc):
    with patch('bg3loc.providers.openai_compatible.request.urlopen', side_effect=exc):
        with pytest.raises(OSError) as caught:
            UrllibJsonTransport().post_json(url='https://example.invalid', headers={},
                                           payload={}, timeout_seconds=1)
    assert_private(repr(caught.value))
    assert_private(traceback.format_exception(caught.value))


def test_windows_denied_socket_diagnostic_remains_classifiable():
    exc = OSError(ECHO)
    exc.winerror = 10013
    result = provider(FakeTransport(exc=error.URLError(exc)))(request_for())
    assert 'WinError 10013' in result.error_message
    assert_private(result)


def test_prompt_provenance_and_validation_do_not_echo_details():
    def bad_callback(_):
        raise ValueError(ECHO)
    result = provider(FakeTransport()).translate_with_provenance(request_for(), bad_callback)
    assert result.error_code == 'PROMPT_PROVENANCE_ERROR'
    assert not result.retryable
    assert_private(result)
    result = provider(FakeTransport(payload={
        'id': ECHO, 'choices': [{'message': {'content': ECHO}}]}))(request_for())
    assert result.error_code == 'OUTPUT_VALIDATION_FAILED'
    assert_private(result)


@pytest.mark.parametrize('body', [None, [], ECHO, {'choices': [{'message': {'content': { 'echo': ECHO }}}]}])
def test_malformed_response_is_private(body):
    result = provider(FakeTransport(payload=body))(request_for())
    assert result.error_code == 'PROVIDER_RESPONSE_INVALID'
    assert result.retryable
    assert_private(result)


def test_history_read_and_report_redaction_does_not_rewrite_history(tmp_path):
    with redirect_stdout(io.StringIO()):
        workspace, db = execution_fixture.TestProductionExecution()._workspace(tmp_path)
        args = ['production', 'execute-openai-compatible', '--workspace', str(workspace),
                '--base-url', 'https://example.invalid', '--model', 'synthetic',
                '--run-id', 'history', '--worker-id', 'w', '--max-items', '1']
        with patch.object(UrllibJsonTransport, 'post_json', return_value=(500, {})):
            assert main(args) == 0
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE attempts SET error_code=?, error_message=?, provider_request_id=?',
                     (ECHO, ECHO, ECHO))
        before = conn.execute('SELECT * FROM attempts').fetchall()
    assert_private(TranslationExecutionStore(db).get_attempts('uid-a'))
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(['production', 'report', '--workspace', str(workspace)]) == 0
    assert_private(output.getvalue())
    with sqlite3.connect(db) as conn:
        assert before == conn.execute('SELECT * FROM attempts').fetchall()
        conn.execute('UPDATE attempts SET error_code=NULL,error_message=NULL,provider_request_id=NULL')
    attempt = TranslationExecutionStore(db).get_attempts('uid-a')[0]
    assert attempt['error_code'] is None and attempt['error_message'] is None


def test_custom_provider_exception_worker_boundary(tmp_path, caplog):
    with redirect_stdout(io.StringIO()):
        _, db = execution_fixture.TestProductionExecution()._workspace(tmp_path)
    store = TranslationExecutionStore(db)
    store.start_run(run_id='custom', batch_plan_fingerprint='fp-production-execution',
                    provider='synthetic', model='synthetic', prompt_version='synthetic',
                    execution_config_hash='synthetic', started_at='2026-10-11T00:00:00Z')
    def raises(_):
        raise RuntimeError(ECHO)
    summary = run_worker(store, run_id='custom', worker_id='w', provider=raises, max_items=1)
    assert summary.failed_final == 1  # Preserve the existing worker exception classification.
    assert store.get_attempts('uid-a')[0]['error_code'] == 'PROVIDER_EXCEPTION'
    assert_private(db.read_bytes())
    assert_private(caplog.text)
