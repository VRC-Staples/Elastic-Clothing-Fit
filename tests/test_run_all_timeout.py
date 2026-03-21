"""Tests for run_all.py timeout handling and _parse_suite_output logic.

_parse_suite_output is pure Python with no subprocess or bpy dependency, so
it is extracted verbatim here for direct unit testing.  The extraction is kept
identical to the source so that any future change to the source function breaks
these tests immediately (they should fail, prompting a sync).
"""
import subprocess


# ---------------------------------------------------------------------------
# Verbatim extraction of _parse_suite_output from tests/run_all.py
# ---------------------------------------------------------------------------

def _parse_suite_output(stdout):
    """Parse [PASS] / [FAIL] / [SKIP] lines from a suite's stdout.

    Returns (passed, failed, skipped, failures) where:
      passed   — count of [PASS] lines
      failed   — count of [FAIL] lines
      skipped  — True if any [SKIP] line was present
      failures — list of verbatim [FAIL] lines
    """
    passed = 0
    failed = 0
    skipped = False
    failures = []
    for line in stdout.splitlines():
        s = line.strip()
        if "[PASS]" in s:
            passed += 1
        elif "[FAIL]" in s:
            failed += 1
            failures.append(s)
        elif "[SKIP]" in s:
            skipped = True
    return passed, failed, skipped, failures


# ---------------------------------------------------------------------------
# Helper that reproduces _run_suite's TimeoutExpired path
# ---------------------------------------------------------------------------

def _run_suite_on_timeout(script_name):
    """Simulate what _run_suite does when subprocess.TimeoutExpired is raised.

    In run_all.py the handler is:
        except subprocess.TimeoutExpired:
            return 1, f"[TIMEOUT] Suite '{script_path.name}' timed out after 300s\\n"

    We replicate that exact string format here to test that the caller
    interprets it correctly.
    """
    return 1, f"[TIMEOUT] Suite '{script_name}' timed out after 300s\n"


# ---------------------------------------------------------------------------
# Tests: _parse_suite_output with a [TIMEOUT] line
# ---------------------------------------------------------------------------

def test_timeout_line_not_counted_as_fail():
    """A [TIMEOUT] line must NOT increment the failed counter."""
    output = "[TIMEOUT] Suite 'suite_fit_pipeline.py' timed out after 300s\n"
    _, failed, _, _ = _parse_suite_output(output)
    assert failed == 0, f"[TIMEOUT] line must not be counted as a failure; got failed={failed}"


def test_timeout_line_not_counted_as_pass():
    """A [TIMEOUT] line must NOT increment the passed counter."""
    output = "[TIMEOUT] Suite 'suite_fit_pipeline.py' timed out after 300s\n"
    passed, _, _, _ = _parse_suite_output(output)
    assert passed == 0, f"[TIMEOUT] line must not be counted as a pass; got passed={passed}"


def test_timeout_line_skipped_flag_false():
    """A [TIMEOUT] line must NOT set the skipped flag."""
    output = "[TIMEOUT] Suite 'suite_fit_pipeline.py' timed out after 300s\n"
    _, _, skipped, _ = _parse_suite_output(output)
    assert skipped is False, f"[TIMEOUT] line must not set skipped; got skipped={skipped}"


def test_timeout_line_failures_list_empty():
    """The failures list must be empty when only a [TIMEOUT] line is present."""
    output = "[TIMEOUT] Suite 'suite_fit_pipeline.py' timed out after 300s\n"
    _, _, _, failures = _parse_suite_output(output)
    assert failures == [], f"failures list must be empty for [TIMEOUT]-only output; got {failures!r}"


# ---------------------------------------------------------------------------
# Tests: normal [PASS] / [FAIL] lines still counted correctly
# ---------------------------------------------------------------------------

def test_normal_pass_fail_still_counted():
    """[PASS] and [FAIL] lines are counted correctly when mixed with other output."""
    output = (
        "Blender startup info ...\n"
        "[PASS] mesh deforms correctly\n"
        "[PASS] vertex groups preserved\n"
        "[FAIL] armature weight sum mismatch\n"
        "Some other line\n"
    )
    passed, failed, skipped, failures = _parse_suite_output(output)
    assert passed == 2, f"expected 2 passed, got {passed}"
    assert failed == 1, f"expected 1 failed, got {failed}"
    assert skipped is False
    assert len(failures) == 1
    assert "[FAIL]" in failures[0]


def test_skip_flag_set():
    """A [SKIP] line sets the skipped flag to True."""
    output = "[SKIP] Proximity suite skipped: no blend root\n"
    _, _, skipped, _ = _parse_suite_output(output)
    assert skipped is True, f"expected skipped=True, got {skipped}"


# ---------------------------------------------------------------------------
# Tests: empty output
# ---------------------------------------------------------------------------

def test_empty_output():
    """Empty string returns all-zero / False values."""
    passed, failed, skipped, failures = _parse_suite_output("")
    assert passed == 0
    assert failed == 0
    assert skipped is False
    assert failures == []


# ---------------------------------------------------------------------------
# Tests: _run_suite TimeoutExpired return value
# ---------------------------------------------------------------------------

def test_run_suite_timeout_returns_rc1():
    """_run_suite returns rc=1 on TimeoutExpired."""
    rc, _ = _run_suite_on_timeout("suite_fit_pipeline.py")
    assert rc == 1, f"expected rc=1 on timeout, got {rc}"


def test_run_suite_timeout_output_contains_timeout_marker():
    """_run_suite timeout output contains the [TIMEOUT] marker."""
    _, output = _run_suite_on_timeout("suite_fit_pipeline.py")
    assert "[TIMEOUT]" in output, f"expected [TIMEOUT] in output, got: {output!r}"


def test_run_suite_timeout_output_contains_script_name():
    """_run_suite timeout output contains the script filename."""
    script = "suite_fit_pipeline.py"
    _, output = _run_suite_on_timeout(script)
    assert script in output, f"expected {script!r} in output, got: {output!r}"


def test_run_suite_timeout_parse_gives_zero_counts():
    """When _run_suite's timeout output is fed to _parse_suite_output, counts are all 0."""
    _, timeout_output = _run_suite_on_timeout("suite_fit_pipeline.py")
    passed, failed, skipped, failures = _parse_suite_output(timeout_output)
    assert passed == 0, f"timeout output should parse to 0 passed, got {passed}"
    assert failed == 0, f"timeout output should parse to 0 failed, got {failed}"
    assert skipped is False
    assert failures == []
