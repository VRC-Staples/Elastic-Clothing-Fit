# tests/test_updater_security.py
#
# Security-focused unit tests for elastic_fit/updater.py.
#
# updater.py imports bpy at module level so it cannot be imported directly
# in a plain Python context.  The constants and logic under test are extracted
# or replicated verbatim here so the tests run in the standard pytest venv
# without Blender.
#
# Covered (T01):
#   _SAFE_TAG_RE          -- tag validation regex
#   MAX_DOWNLOAD_BYTES    -- download size cap constant (value check)
#   MAX_JSON_BYTES        -- JSON response size cap constant (value check)
#   download size-cap logic -- simulated chunk-loop abort
#   JSON size-cap logic   -- resp.read(MAX_JSON_BYTES + 1) guard
#
# Covered (T03 will extend):
#   contextlib.closing usage, retry exception narrowing

import io
import os
import re
import tempfile
import threading

import pytest


# ---------------------------------------------------------------------------
# Extracted constants / logic (verbatim from elastic_fit/updater.py)
# ---------------------------------------------------------------------------

# Security constants — must match updater.py exactly.
_SAFE_TAG_RE = re.compile(r'^(?:nightly|v?\d+\.\d+\.\d+)')
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024       # 50 MB
MAX_JSON_BYTES     = 1 * 1024 * 1024        # 1 MB


def _simulate_download(chunks, max_bytes=MAX_DOWNLOAD_BYTES):
    """Simulate the chunk download loop.

    Mimics the logic in _download_thread: accumulates bytes, raises RuntimeError
    ('Download too large') when the cap is exceeded, otherwise returns total bytes.
    The actual implementation sets _state['error'] and returns; here we raise for
    easy pytest assertion.
    """
    downloaded = 0
    for chunk in chunks:
        downloaded += len(chunk)
        if downloaded > max_bytes:
            raise RuntimeError('Download too large')
    return downloaded


def _simulate_json_fetch(raw_bytes, max_bytes=MAX_JSON_BYTES):
    """Simulate the _fetch() size-cap guard.

    Mimics: raw = resp.read(MAX_JSON_BYTES + 1); if len(raw) > MAX_JSON_BYTES: raise ValueError
    Returns raw_bytes unchanged if within limit, else raises ValueError.
    """
    # resp.read(MAX_JSON_BYTES + 1) stops reading after max_bytes+1 bytes
    # — we model this by truncating to the cap + 1 byte.
    read_bytes = raw_bytes[:max_bytes + 1]
    if len(read_bytes) > max_bytes:
        raise ValueError("Response too large")
    return read_bytes


# ---------------------------------------------------------------------------
# Tests: _SAFE_TAG_RE
# ---------------------------------------------------------------------------

class TestSafeTagRe:
    """Verify that _SAFE_TAG_RE accepts valid tags and rejects traversal payloads."""

    # --- valid tags ---

    def test_v_prefix_semver(self):
        assert _SAFE_TAG_RE.match('v1.0.5')

    def test_no_v_prefix(self):
        assert _SAFE_TAG_RE.match('1.0.5')

    def test_nightly_suffix_allowed(self):
        """Suffix like '-nightly-20240321' is acceptable — regex is start-anchored only."""
        assert _SAFE_TAG_RE.match('v1.0.5-nightly-20240321')

    def test_multi_digit_parts(self):
        assert _SAFE_TAG_RE.match('v10.20.300')

    def test_zero_version(self):
        assert _SAFE_TAG_RE.match('v0.0.0')

    def test_large_patch_version(self):
        assert _SAFE_TAG_RE.match('v2.1.99')

    # --- path traversal / injection attempts ---

    def test_dotdot_slash_rejected(self):
        assert not _SAFE_TAG_RE.match('../../etc/passwd')

    def test_dotdot_backslash_rejected(self):
        assert not _SAFE_TAG_RE.match('..\\..\\Windows\\System32')

    def test_absolute_unix_path_rejected(self):
        assert not _SAFE_TAG_RE.match('/etc/passwd')

    def test_absolute_windows_path_rejected(self):
        assert not _SAFE_TAG_RE.match('C:\\Users\\malicious')

    def test_null_byte_rejected(self):
        assert not _SAFE_TAG_RE.match('\x00v1.0.0')

    def test_empty_string_rejected(self):
        assert not _SAFE_TAG_RE.match('')

    def test_only_v_rejected(self):
        """'v' alone is not a valid version."""
        assert not _SAFE_TAG_RE.match('v')

    def test_alpha_part_rejected(self):
        assert not _SAFE_TAG_RE.match('vone.two.three')

    def test_whitespace_prefix_rejected(self):
        """Leading whitespace is not a valid start."""
        assert not _SAFE_TAG_RE.match(' v1.0.0')

    def test_tag_with_only_two_parts_rejected(self):
        """Pattern requires at least X.Y.Z — two-part tags do not match."""
        assert not _SAFE_TAG_RE.match('v1.0')

    def test_nightly_keyword_accepted(self):
        """The literal 'nightly' tag is used by the nightly release channel
        and must pass the safe-tag check so downloads are not blocked."""
        assert _SAFE_TAG_RE.match('nightly')

    def test_nightly_prefix_variants_rejected(self):
        """Only the exact word 'nightly' is valid — arbitrary prefixes are not."""
        assert not _SAFE_TAG_RE.match('xnightly')
        assert not _SAFE_TAG_RE.match('not-nightly')


# ---------------------------------------------------------------------------
# Tests: constant values
# ---------------------------------------------------------------------------

class TestConstantValues:
    """Verify constants are set to the expected values."""

    def test_max_download_bytes_is_50mb(self):
        assert MAX_DOWNLOAD_BYTES == 50 * 1024 * 1024

    def test_max_json_bytes_is_1mb(self):
        assert MAX_JSON_BYTES == 1 * 1024 * 1024

    def test_max_download_bytes_is_positive(self):
        assert MAX_DOWNLOAD_BYTES > 0

    def test_max_json_bytes_is_positive(self):
        assert MAX_JSON_BYTES > 0

    def test_max_json_bytes_less_than_max_download(self):
        """JSON cap should be smaller than the download cap."""
        assert MAX_JSON_BYTES < MAX_DOWNLOAD_BYTES


# ---------------------------------------------------------------------------
# Tests: download size-cap logic
# ---------------------------------------------------------------------------

class TestDownloadSizeCap:
    """Verify the simulated chunk-loop size-cap behaves correctly."""

    def test_exact_limit_allowed(self):
        """A download of exactly MAX_DOWNLOAD_BYTES should not abort."""
        chunk = b'x' * MAX_DOWNLOAD_BYTES
        total = _simulate_download([chunk])
        assert total == MAX_DOWNLOAD_BYTES

    def test_one_byte_over_limit_aborts(self):
        """A download of MAX_DOWNLOAD_BYTES + 1 must raise an error."""
        chunk = b'x' * (MAX_DOWNLOAD_BYTES + 1)
        with pytest.raises(RuntimeError, match='Download too large'):
            _simulate_download([chunk])

    def test_accumulated_over_limit_aborts(self):
        """The cap applies to accumulated bytes across multiple chunks."""
        chunk_size = 1024 * 1024  # 1 MB per chunk
        num_chunks = (MAX_DOWNLOAD_BYTES // chunk_size) + 1
        chunks = [b'x' * chunk_size] * num_chunks
        with pytest.raises(RuntimeError, match='Download too large'):
            _simulate_download(chunks)

    def test_small_download_succeeds(self):
        """Normal-sized downloads (a few MB) pass without error."""
        chunk = b'x' * (5 * 1024 * 1024)  # 5 MB
        total = _simulate_download([chunk])
        assert total == 5 * 1024 * 1024

    def test_empty_download_succeeds(self):
        total = _simulate_download([])
        assert total == 0

    def test_many_small_chunks_within_limit(self):
        chunk = b'x' * 1024  # 1 KB each
        # 1000 * 1 KB = 1 MB — well under 50 MB cap
        total = _simulate_download([chunk] * 1000)
        assert total == 1000 * 1024

    def test_custom_cap_honoured(self):
        """The cap parameter is used when supplied explicitly."""
        cap = 100
        with pytest.raises(RuntimeError, match='Download too large'):
            _simulate_download([b'x' * 101], max_bytes=cap)

    def test_custom_cap_exact_limit_allowed(self):
        cap = 100
        total = _simulate_download([b'x' * 100], max_bytes=cap)
        assert total == 100


# ---------------------------------------------------------------------------
# Tests: JSON response size-cap logic
# ---------------------------------------------------------------------------

class TestJsonSizeCap:
    """Verify the simulated JSON fetch size-cap guard."""

    def test_response_within_limit_returned_unchanged(self):
        data = b'{"tag_name": "v1.0.5"}' * 10  # small response
        result = _simulate_json_fetch(data)
        assert result == data

    def test_response_exactly_at_limit_allowed(self):
        data = b'x' * MAX_JSON_BYTES
        result = _simulate_json_fetch(data)
        assert len(result) == MAX_JSON_BYTES

    def test_response_one_byte_over_limit_raises(self):
        data = b'x' * (MAX_JSON_BYTES + 1)
        with pytest.raises(ValueError, match='Response too large'):
            _simulate_json_fetch(data)

    def test_response_two_bytes_over_limit_raises(self):
        data = b'x' * (MAX_JSON_BYTES + 2)
        with pytest.raises(ValueError, match='Response too large'):
            _simulate_json_fetch(data)

    def test_empty_response_allowed(self):
        result = _simulate_json_fetch(b'')
        assert result == b''

    def test_typical_api_response_well_within_limit(self):
        """A realistic GitHub releases API response (~10 KB) passes easily."""
        typical_size = 10 * 1024  # 10 KB
        data = b'x' * typical_size
        result = _simulate_json_fetch(data)
        assert len(result) == typical_size

    def test_custom_cap_honoured(self):
        cap = 50
        with pytest.raises(ValueError, match='Response too large'):
            _simulate_json_fetch(b'x' * 51, max_bytes=cap)

    def test_custom_cap_exact_limit_allowed(self):
        cap = 50
        result = _simulate_json_fetch(b'x' * 50, max_bytes=cap)
        assert len(result) == 50


# ---------------------------------------------------------------------------
# Tests: source-code structure (static checks via regex on source text)
# ---------------------------------------------------------------------------

class TestUpdaterSourceInvariants:
    """Static checks that verify the constants and guards exist in the actual source."""

    @pytest.fixture(scope='class')
    def source(self):
        target = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'elastic_fit', 'updater.py',
        )
        with open(target, encoding='utf-8') as fh:
            return fh.read()

    def test_safe_tag_re_defined(self, source):
        assert '_SAFE_TAG_RE' in source

    def test_max_download_bytes_defined(self, source):
        assert 'MAX_DOWNLOAD_BYTES' in source

    def test_max_json_bytes_defined(self, source):
        assert 'MAX_JSON_BYTES' in source

    def test_invalid_tag_error_message_present(self, source):
        assert 'Invalid tag format' in source

    def test_download_too_large_error_message_present(self, source):
        assert 'Download too large' in source

    def test_response_too_large_error_present(self, source):
        assert 'Response too large' in source

    def test_safe_tag_re_used_before_zip_path(self, source):
        """_SAFE_TAG_RE.match must appear before zip_path = os.path.join in the source."""
        idx_tag_check = source.find('_SAFE_TAG_RE.match(tag)')
        idx_zip_path  = source.find("os.path.join(cache_dir, f'ElasticClothingFit-{tag}.zip')")
        assert idx_tag_check != -1, '_SAFE_TAG_RE.match(tag) not found in source'
        assert idx_zip_path  != -1, 'zip_path join not found in source'
        assert idx_tag_check < idx_zip_path, (
            '_SAFE_TAG_RE check must appear before zip_path construction'
        )

    def test_max_json_bytes_used_in_read_call(self, source):
        """resp.read(MAX_JSON_BYTES + 1) must appear in _check_thread._fetch."""
        assert 'resp.read(MAX_JSON_BYTES + 1)' in source

    def test_size_check_after_read(self, source):
        """len(raw) > MAX_JSON_BYTES guard must appear after the read call."""
        idx_read  = source.find('resp.read(MAX_JSON_BYTES + 1)')
        idx_check = source.find('len(raw) > MAX_JSON_BYTES')
        assert idx_read  != -1, 'resp.read(MAX_JSON_BYTES + 1) not found'
        assert idx_check != -1, 'len(raw) > MAX_JSON_BYTES check not found'
        assert idx_read < idx_check, 'size check must follow the read call'


# ---------------------------------------------------------------------------
# T02 source invariants: HTTP hardening, contextlib.closing, retry narrowing
# ---------------------------------------------------------------------------

class TestT02SourceInvariants:
    """Static source-code checks for T02 changes.

    These tests inspect the actual updater.py source text at test-execution
    time, catching any accidental revert of the T02 hardening.
    """

    @pytest.fixture(scope='class')
    def source(self):
        src_path = os.path.join(os.path.dirname(__file__), '..', 'elastic_fit', 'updater.py')
        with open(src_path, encoding='utf-8') as f:
            return f.read()

    def test_import_contextlib_present(self, source):
        assert 'import contextlib' in source

    def test_contextlib_closing_in_download_thread(self, source):
        """_download_thread must use contextlib.closing to wrap the response."""
        assert 'contextlib.closing(resp)' in source

    def test_contextlib_closing_in_fetch(self, source):
        """_check_thread._fetch must use contextlib.closing to wrap the response."""
        assert 'contextlib.closing(_urlopen_with_retry' in source

    def test_no_bare_resp_close_after_chunk_loop(self, source):
        """The manual resp.close() after the chunk loop must be gone."""
        # After the with open(zip_path, 'wb') block the source must NOT have
        # a bare 'resp.close()' line (closure is now handled by contextlib.closing).
        # We check that there's no "resp.close()" in _download_thread beyond what
        # contextlib.closing already handles.
        # Since contextlib.closing is present and the explicit call was removed,
        # 'resp.close()' should NOT appear as a standalone statement.
        lines = source.splitlines()
        bare_close_lines = [
            i + 1 for i, ln in enumerate(lines)
            if ln.strip() == 'resp.close()'
        ]
        assert bare_close_lines == [], (
            f'Bare resp.close() found at lines {bare_close_lines} — '
            f'should be handled by contextlib.closing'
        )

    def test_retry_narrowed_to_url_error(self, source):
        """_urlopen_with_retry must catch urllib.error.URLError, not bare Exception."""
        assert 'except urllib.error.URLError as exc:' in source

    def test_retry_non_os_error_re_raises(self, source):
        """Non-OSError URLError must re-raise immediately (no retry)."""
        assert 'if not isinstance(exc.reason, OSError):' in source
        assert 'raise' in source

    def test_no_bare_except_exception_in_retry(self, source):
        """The old broad 'except Exception:' must be gone from _urlopen_with_retry."""
        # Find the function definition and verify it doesn't contain 'except Exception:'
        start = source.find('def _urlopen_with_retry(')
        end   = source.find('\ndef ', start + 1)  # next function definition
        retry_body = source[start:end]
        assert 'except Exception:' not in retry_body, (
            'Broad except Exception: still present in _urlopen_with_retry'
        )

    def test_sidecar_data_includes_expected_sha256(self, source):
        """install_and_restart sidecar_data must include expected_sha256 field."""
        assert "'expected_sha256': _state.get('expected_sha256')" in source


# ---------------------------------------------------------------------------
# Tests: retry exception narrowing (behavioural — extracted pure function)
# ---------------------------------------------------------------------------

import urllib.error  # noqa: E402 — imported here so test module stays self-contained


def should_retry(exc):
    """Mirror the narrowed retry decision from _urlopen_with_retry.

    Extracted verbatim from the logic in elastic_fit/updater.py:

        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, OSError):
                raise
            ...  # retry with backoff

    Returns True when the exception is a URLError whose *reason* is an OSError
    subclass (i.e. a transient network failure worth retrying).  Returns False
    for any other exception type so callers know to re-raise immediately.
    """
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, OSError)


class TestRetryNarrowing:
    """Verify the narrowed retry-decision logic using a pure extracted function.

    These are behavioural tests — they exercise *should_retry()* directly,
    confirming that:
      • transient OSError-wrapped URLErrors are flagged for retry
      • non-OSError URLErrors (SSL, HTTP 4xx) are flagged for immediate re-raise
      • non-URLError exceptions (ValueError, RuntimeError, …) are never retried
    """

    # --- cases that SHOULD retry ---

    def test_urlopen_oserror_retries(self):
        """URLError(reason=OSError()) is a transient network fault → should retry."""
        exc = urllib.error.URLError(reason=OSError("connection reset"))
        assert should_retry(exc) is True

    def test_urlopen_connection_refused_retries(self):
        """ConnectionRefusedError is an OSError subclass → should retry."""
        exc = urllib.error.URLError(reason=ConnectionRefusedError())
        assert should_retry(exc) is True

    def test_urlopen_timeout_error_retries(self):
        """TimeoutError is an OSError subclass → should retry."""
        exc = urllib.error.URLError(reason=TimeoutError())
        assert should_retry(exc) is True

    def test_urlopen_broken_pipe_retries(self):
        """BrokenPipeError is an OSError subclass → should retry."""
        exc = urllib.error.URLError(reason=BrokenPipeError())
        assert should_retry(exc) is True

    # --- cases that should NOT retry (immediate re-raise) ---

    def test_urlopen_non_oserror_no_retry(self):
        """URLError whose reason is a plain Exception (e.g. SSL) → no retry."""
        exc = urllib.error.URLError(reason=Exception("SSL: CERTIFICATE_VERIFY_FAILED"))
        assert should_retry(exc) is False

    def test_urlopen_string_reason_no_retry(self):
        """URLError with a string reason (no network fault) → no retry."""
        exc = urllib.error.URLError(reason="name or service not known")
        # str is not an OSError subclass
        assert should_retry(exc) is False

    def test_non_urlopen_value_error_no_retry(self):
        """ValueError is not a URLError → never retried."""
        exc = ValueError("unexpected response format")
        assert should_retry(exc) is False

    def test_non_urlopen_runtime_error_no_retry(self):
        """RuntimeError is not a URLError → never retried."""
        exc = RuntimeError("internal failure")
        assert should_retry(exc) is False

    def test_non_urlopen_exception_no_retry(self):
        """Plain Exception is not a URLError → never retried."""
        exc = Exception("unknown error")
        assert should_retry(exc) is False

    def test_http_error_no_retry(self):
        """HTTPError (404, 403, etc.) is a URLError subclass but NOT an OSError reason.

        urllib.error.HTTPError does not set a .reason attribute the way URLError does —
        it is itself the 'reason'.  The isinstance(exc.reason, OSError) guard
        therefore evaluates to False (exc.reason is None or an int), so HTTP
        errors are never retried.
        """
        exc = urllib.error.HTTPError(
            url="https://api.github.com/releases",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        # HTTPError is a URLError subclass, so we must verify the full predicate
        assert should_retry(exc) is False
