"""Runner verdicts use actual execution, not just printed check counts."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests import run_all
from tools.verify_run_all_json import DEFAULT_REQUIRED_SUITES, verify_payload


@pytest.fixture
def runner(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run_all.deploy, '_find_blender', lambda _override: 'test-blender')
    monkeypatch.setattr(run_all.deploy, '_read_version', lambda: '1.0.0')
    monkeypatch.setattr(run_all.deploy, '_build_zip', lambda _version: tmp_path / 'addon.zip')
    monkeypatch.setattr(run_all.deploy, '_run_install', lambda *_args: 0)
    healthy_output = '[PASS] a completed check\n' * 40

    def invoke(outcomes=None, transport=None):
        outcomes = outcomes or {}
        calls = []

        def execute(command, **kwargs):
            calls.append(command)
            if transport:
                return transport(command, **kwargs)
            script = Path(command[command.index('--python') + 1]).name
            if '--skip' in command:
                return subprocess.CompletedProcess(command, 0, '[SKIP] Fit Pipeline did not pass\n', '')
            outcome = outcomes.get(script, (0, healthy_output))
            if isinstance(outcome, Exception):
                raise outcome
            return subprocess.CompletedProcess(command, outcome[0], outcome[1], '')

        monkeypatch.setattr(run_all.subprocess, 'run', execute)
        destination = tmp_path / 'result.json'
        monkeypatch.setattr(sys, 'argv', ['run_all.py', '--programmatic', '--json-out', str(destination)])
        with pytest.raises(SystemExit) as exit_info:
            run_all.main()
        return exit_info.value.code, json.loads(destination.read_text()), capsys.readouterr().out, calls

    return invoke


@pytest.mark.parametrize('outcome', [
    (1, '[PASS] before abnormal exit\n'),
    (0, ''),
    subprocess.TimeoutExpired('test-blender', 300, output=b'[PASS] before timeout\n'),
    OSError('executable could not start'),
], ids=['nonzero-after-pass', 'empty-success', 'timeout-after-pass', 'could-not-start'])
def test_incomplete_suite_fails_despite_other_suites_exceeding_minimum(runner, outcome):
    code, payload, text, _calls = runner({'suite_ux_tabs.py': outcome})
    assert code == 1
    assert payload['total_passed'] >= 240
    assert payload['total_failed'] == 0  # Execution failure is not a failed assertion.
    assert 'ALL SUITES PASSED' not in text
    assert verify_payload(payload, expected_suites=7, min_checks=240,
                          required_suite_names=DEFAULT_REQUIRED_SUITES)


def test_failed_install_fails_and_records_suites_that_did_not_run(runner, monkeypatch):
    monkeypatch.setattr(run_all.deploy, '_run_install', lambda *_args: 1)
    code, payload, text, calls = runner()
    assert code == 1
    assert not calls
    assert payload['total_failed'] == 0
    assert all(suite['skipped'] and suite['skip_reason'] for suite in payload['suites'])
    assert payload['setup']['returncode'] == 1
    assert 'ALL SUITES PASSED' not in text


def test_install_timeout_still_writes_a_failing_artifact(runner, monkeypatch):
    def timeout(*_args):
        raise subprocess.TimeoutExpired('test-blender', 180)

    monkeypatch.setattr(run_all.deploy, '_run_install', timeout)
    code, payload, text, calls = runner()
    assert code == 1
    assert not calls
    assert payload['setup']['timed_out'] is True
    assert 'ALL SUITES PASSED' not in text


def test_abnormal_fit_execution_prevents_dependent_suite(runner):
    code, payload, _text, _calls = runner({'suite_fit_pipeline.py': (1, '[PASS] before exit\n')})
    assert code == 1
    proximity = next(s for s in payload['suites'] if s['name'] == 'Proximity')
    assert proximity['skipped'] and proximity['skip_reason']
    assert proximity['passed'] == 0


def test_complete_success_remains_accepted_by_independent_verifier(runner):
    code, payload, text, _calls = runner()
    assert code == 0
    assert payload['total_passed'] == 280
    assert payload['total_failed'] == 0
    assert 'ALL SUITES PASSED' in text
    assert verify_payload(payload, expected_suites=7, min_checks=240,
                          required_suite_names=DEFAULT_REQUIRED_SUITES) == []


def test_real_child_that_prints_pass_then_exits_one_fails_run(runner):
    real_run = subprocess.run
    first = True

    def transport(command, **kwargs):
        nonlocal first
        if first:
            first = False
            return real_run([sys.executable, '-c', "print('[PASS] real child check');raise SystemExit(1)"],
                            **kwargs)
        return subprocess.CompletedProcess(command, 0, '[PASS] other completed check\n' * 40, '')

    code, payload, text, _calls = runner(transport=transport)
    assert code == 1
    assert payload['total_passed'] == 241
    assert payload['total_failed'] == 0
    assert '[PASS] real child check' in text
    assert payload['suites'][0]['returncode'] == 1
