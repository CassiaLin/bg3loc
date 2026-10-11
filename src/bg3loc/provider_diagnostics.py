"""Allowlisted diagnostic channels: never inspect or stringify provider content.

Failure request IDs are untrusted free text too. Retry signals and token counts
are separate typed fields, not redacted messages. No raw debug fallback exists.
"""
import re
import socket
from urllib.error import URLError

_MESSAGES = {
    'PROVIDER_ERROR': 'Provider failed; unrecognized diagnostic code suppressed',
    'PROVIDER_CONFIG_INVALID': 'Provider configuration is invalid',
    'PROMPT_ASSEMBLY_ERROR': 'Prompt assembly failed',
    'PROMPT_PROVENANCE_ERROR': 'Prompt provenance validation failed',
    'PROVIDER_TRANSPORT_ERROR': 'Provider transport failed',
    'PROVIDER_EXCEPTION': 'Provider raised an exception',
    'PROVIDER_RESPONSE_INVALID': 'Provider response structure is invalid',
    'PROVIDER_OUTPUT_EMPTY': 'Provider returned empty translated text',
    'OUTPUT_VALIDATION_FAILED': 'Provider output failed protected syntax validation',
    'MATERIAL_RESOLUTION_ERROR': 'Translation material resolution failed',
    'CONTEXT_CONTRACT_MISMATCH': 'Dialogue production execution remains disabled pending full workspace and activation gates',
    'LEASE_EXPIRED': 'Worker lease expired before terminal result',
    'OFFLINE_TRANSPORT_FAILURE': 'Offline fixture failure',
    'TEMP': 'Temporary failure',
}
_TRANSPORT_MESSAGES = frozenset({
    'Provider transport timed out', 'Provider connection failed',
    'Provider DNS resolution failed',
    'Provider transport failed (WinError 10013)',
})


def safe_error_code(code: object) -> str:
    if type(code) is str:
        if code in _MESSAGES or re.fullmatch(r'HTTP_[1-5][0-9]{2}', code):
            return code
    return 'PROVIDER_ERROR'


def safe_error_message(code: object, message: object = None) -> str:
    code = safe_error_code(code)
    if code == 'PROVIDER_TRANSPORT_ERROR' and type(message) is str and message in _TRANSPORT_MESSAGES:
        return message
    if code.startswith('HTTP_'):
        return f'Provider returned HTTP {code[5:]}; response details suppressed'
    return _MESSAGES[code]


def transport_error_message(exc: BaseException) -> str:
    # Inspect only known exception categories / one documented OS error number.
    # Do not read args, str, repr, custom class names, URLs, headers or bodies.
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, OSError) and getattr(reason, 'winerror', None) == 10013:
        return 'Provider transport failed (WinError 10013)'
    if isinstance(reason, TimeoutError):
        return 'Provider transport timed out'
    if isinstance(reason, socket.gaierror):
        return 'Provider DNS resolution failed'
    if isinstance(reason, ConnectionError):
        return 'Provider connection failed'
    return safe_error_message('PROVIDER_TRANSPORT_ERROR')


def safe_attempt_diagnostics(row: dict) -> dict:
    """Read-time protection for historical failures; never rewrite history/NULL."""
    if row.get('error_code') is not None:
        row['error_code'] = safe_error_code(row['error_code'])
    if row.get('error_message') is not None:
        row['error_message'] = safe_error_message(row.get('error_code'), row['error_message'])
    if str(row.get('outcome', '')).startswith('failed'):
        row['provider_request_id'] = None
    return row
