import json
from pathlib import Path

import pytest

from tools.verify_run_all_json import DEFAULT_REQUIRED_SUITES, verify_json_file, verify_payload


_KNOWN_GOOD_JSON = Path(__file__).parent / "fixtures" / "run_all_known_good.json"


def _read_known_good_payload() -> dict:
    return json.loads(_KNOWN_GOOD_JSON.read_text(encoding="utf-8"))


def _contains(errors: list[str], text: str) -> bool:
    return any(text in error for error in errors)


def test_accepts_known_good_fixture_artifact():
    errors = verify_json_file(
        _KNOWN_GOOD_JSON,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )
    assert errors == []


def test_rejects_unreadable_file():
    errors = verify_json_file(
        _KNOWN_GOOD_JSON.parent / "does-not-exist.json",
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )
    assert _contains(errors, "Unable to read JSON file")


def test_rejects_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json }", encoding="utf-8")

    errors = verify_json_file(
        bad,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )
    assert _contains(errors, "Invalid JSON")


def test_rejects_missing_required_suite_name():
    payload = _read_known_good_payload()
    payload["suites"] = [suite for suite in payload["suites"] if suite["name"] != "Proxy Hull"]

    errors = verify_payload(
        payload,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )

    assert _contains(errors, "Suite count mismatch")
    assert _contains(errors, "Missing required suites: Proxy Hull")


def test_rejects_duplicate_suite_name():
    payload = _read_known_good_payload()
    payload["suites"][-1]["name"] = "UX Tabs"

    errors = verify_payload(
        payload,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )

    assert _contains(errors, "Duplicate suite names: UX Tabs")


def test_rejects_low_total_check_count_false_green_shape():
    payload = {
        "suites": [
            {"name": name, "passed": 0, "failed": 0, "skipped": False, "failures": []}
            for name in DEFAULT_REQUIRED_SUITES
        ],
        "total_passed": 0,
        "total_failed": 0,
    }

    errors = verify_payload(
        payload,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )
    assert _contains(errors, "Total check count below minimum: 0 < min_checks=240")


def test_rejects_nonzero_total_failed():
    payload = _read_known_good_payload()
    payload["total_failed"] = 1

    errors = verify_payload(
        payload,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )
    assert _contains(errors, "Run reported failing checks: total_failed=1")


def test_rejects_missing_totals_and_wrong_types():
    payload = _read_known_good_payload()
    payload.pop("total_passed")
    payload["total_failed"] = "zero"
    payload["suites"][0]["passed"] = "37"

    errors = verify_payload(
        payload,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )

    assert _contains(errors, "Missing required key: total_passed")
    assert _contains(errors, "Invalid type/value for total_failed")
    assert _contains(errors, "suites[0].passed must be a non-negative int")


def test_rejects_missing_suites_key():
    payload = _read_known_good_payload()
    payload.pop("suites")

    errors = verify_payload(
        payload,
        expected_suites=7,
        min_checks=240,
        required_suite_names=DEFAULT_REQUIRED_SUITES,
    )

    assert errors == ["Missing required key: suites"]


@pytest.mark.parametrize('change', [
    'nonzero-exit', 'timeout', 'missing-exit', 'boolean-exit',
    'empty-required-suite', 'failed-setup', 'missing-setup', 'skip-without-reason',
])
def test_execution_evidence_cannot_be_hidden_by_passing_totals(change):
    payload = _read_known_good_payload()
    payload['setup'] = {'returncode': 0, 'timed_out': False, 'error': None}
    for suite in payload['suites']:
        suite.update(returncode=0, timed_out=False, skip_reason=None)
    arguments = {'expected_suites': 7, 'min_checks': 240,
                 'required_suite_names': DEFAULT_REQUIRED_SUITES}
    assert verify_payload(payload, **arguments) == []
    suite = payload['suites'][0]
    if change == 'nonzero-exit':
        suite['returncode'] = 1
    elif change == 'timeout':
        suite['timed_out'] = True
    elif change == 'missing-exit':
        suite.pop('returncode')
    elif change == 'boolean-exit':
        suite['returncode'] = False
    elif change == 'empty-required-suite':
        payload['suites'][1]['passed'] += suite['passed']
        suite['passed'] = 0
    elif change == 'failed-setup':
        payload['setup']['returncode'] = 1
    elif change == 'missing-setup':
        payload.pop('setup')
    elif change == 'skip-without-reason':
        suite['skipped'] = True
    assert verify_payload(payload, **arguments)
