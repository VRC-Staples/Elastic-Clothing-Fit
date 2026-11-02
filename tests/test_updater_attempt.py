"""Exercise production updater decisions with controlled transport and Blender effects."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest


ARCHIVE_A = b'known release A archive bytes'
ARCHIVE_B = b'different release B archive bytes'
URL_A = 'https://github.com/VRC-Staples/Elastic-Clothing-Fit/releases/download/v9.0.0/release.zip'
URL_B = 'https://github.com/VRC-Staples/Elastic-Clothing-Fit/releases/download/v9.1.0/release.zip'
RELEASE_A = {'tag': 'v9.0.0', 'version': (9, 0, 0), 'url': URL_A,
             'expected_sha256': hashlib.sha256(ARCHIVE_A).hexdigest(),
             'blender_min': (4, 2, 0), 'blender_min_required': (4, 2, 0), 'blender_blocked': False}
RELEASE_B = {'tag': 'v9.1.0', 'version': (9, 1, 0), 'url': URL_B,
             'expected_sha256': hashlib.sha256(ARCHIVE_B).hexdigest(),
             'blender_min': (6, 0, 0), 'blender_min_required': (6, 0, 0), 'blender_blocked': True}


def release(tag, archive, blender_min='4.2.0'):
    return {'tag_name': tag, 'body': 'SHA256: ' + hashlib.sha256(archive).hexdigest() + '\nBLENDER_MIN=' + blender_min,
            'assets': [{'name': f'ElasticClothingFit-{tag}.zip',
                        'browser_download_url': f'https://github.com/VRC-Staples/Elastic-Clothing-Fit/releases/download/{tag}/release.zip'}]}


class Response(io.BytesIO):
    def __init__(self, body, transport=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}
        self.transport = transport

    def read(self, size=-1):
        if self.transport is not None:
            self.transport.started.set()
            assert self.transport.resume.wait(10), 'Controlled download was not released'
        return super().read(size)


class Transport:
    def __init__(self):
        self.release = release('v9.0.0', ARCHIVE_A)
        self.started = threading.Event()
        self.resume = threading.Event()
        self.resume.set()
        self.download_requests = 0
        self.check_started = threading.Event()
        self.check_resume = threading.Event()
        self.check_resume.set()

    def open(self, _opener, *, req, timeout, cancellation=None):
        if req.full_url.startswith('https://api.github.com/'):
            self.check_started.set()
            assert self.check_resume.wait(10), 'Controlled discovery was not released'
            return Response(json.dumps(self.release).encode())
        archives = {URL_A: ARCHIVE_A, URL_B: ARCHIVE_B}
        assert req.full_url in archives
        self.download_requests += 1
        return Response(archives[req.full_url], self)


def finished(thread):
    thread.join(10)
    assert not thread.is_alive(), 'Updater worker did not finish'


@pytest.fixture
def subject(monkeypatch, tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    bpy = SimpleNamespace(
        app=SimpleNamespace(background=False, version=(5, 1, 0), binary_path=sys.executable),
        utils=SimpleNamespace(user_resource=lambda kind: str(scripts)),
        context=SimpleNamespace(scene=SimpleNamespace(efit_props=SimpleNamespace(
            use_nightly_channel=False, dev_update_url=''))),
        ops=SimpleNamespace(wm=SimpleNamespace(quit_blender=lambda: pytest.fail('Unexpected quit'))))
    monkeypatch.setitem(sys.modules, 'bpy', bpy)
    source = Path(__file__).resolve().parents[1] / 'elastic_fit' / 'updater.py'
    spec = importlib.util.spec_from_file_location('ecf_updater_subject', source)
    updater = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, updater)
    spec.loader.exec_module(updater)
    transport = Transport()
    transport.production_retry = updater._urlopen_with_retry
    monkeypatch.setattr(updater, '_urlopen_with_retry', transport.open)
    monkeypatch.setattr(updater, '_schedule_redraw', lambda: None)
    try:
        yield updater, transport, scripts
    finally:
        transport.resume.set()
        transport.check_resume.set()
        for thread in [updater._owner.check_thread, updater._owner.download_thread]:
            if thread is not None:
                finished(thread)


def discover(updater):
    updater.check_for_update()
    finished(updater._owner.check_thread)
    assert updater.get_status() == 'available'


def download(updater):
    updater.download_and_prepare()
    finished(updater._owner.download_thread)


def test_matching_bytes_are_ready_for_the_selected_release(subject):
    updater, transport, _ = subject
    discover(updater)
    download(updater)
    state = updater.get_state()
    assert state['status'] == 'ready'
    assert state['tag'] == 'v9.0.0'
    assert Path(state['zip_path']).read_bytes() == ARCHIVE_A
    assert state['expected_sha256'] == hashlib.sha256(ARCHIVE_A).hexdigest()
    assert state['progress'] == 1.
    assert transport.download_requests == 1


@pytest.mark.parametrize('digest', [None, '0' * 64])
def test_missing_or_wrong_digest_never_publishes_readiness(subject, digest, monkeypatch):
    updater, transport, _ = subject
    transport.release['body'] = '' if digest is None else 'SHA256: ' + digest
    discover(updater)
    download(updater)
    state = updater.get_state()
    assert state['status'] == 'error'
    assert state['zip_path'] == ''
    assert 'SHA-256' in state['error']
    launches = []
    monkeypatch.setattr(updater.subprocess, 'Popen', lambda *args, **kwargs: launches.append(args))
    updater.install_and_restart()
    assert not launches
    assert updater.get_status() == 'error'
    assert not (subject[2] / 'startup').exists()


def test_repeated_request_during_download_does_not_start_another_transfer(subject):
    updater, transport, _ = subject
    discover(updater)
    transport.resume.clear()
    updater.download_and_prepare()
    assert transport.started.wait(10)
    updater.download_and_prepare()
    transport.resume.set()
    finished(updater._owner.download_thread)
    assert updater.get_status() == 'ready'
    assert transport.download_requests == 1


def test_later_discovery_does_not_replace_the_active_release_digest(subject):
    updater, transport, _ = subject
    discover(updater)
    transport.resume.clear()
    updater.download_and_prepare()
    assert transport.started.wait(10)
    transport.release = release('v9.1.0', ARCHIVE_B, blender_min='6.0.0')
    updater.check_for_update()
    finished(updater._owner.check_thread)
    displayed = updater.get_state()
    assert {key: displayed[key] for key in RELEASE_B} == RELEASE_B
    transport.resume.set()
    finished(updater._owner.download_thread)
    state = updater.get_state()
    assert state['status'] == 'ready', (state['status'], state['tag'], state['error'], state['expected_sha256'])
    assert {key: state[key] for key in RELEASE_A} == RELEASE_A
    assert Path(state['zip_path']).read_bytes() == ARCHIVE_A


@pytest.mark.parametrize('reregister', [False, True])
def test_unregister_cancellation_prevents_a_blocked_worker_publishing_ready(subject, reregister):
    updater, transport, scripts = subject
    discover(updater)
    transport.resume.clear()
    updater.download_and_prepare()
    assert transport.started.wait(10)
    updater.shutdown()
    if reregister:
        updater.activate()
        updater.download_and_prepare()
        assert updater.get_status() == 'idle'
    transport.resume.set()
    finished(updater._owner.download_thread)
    state = updater.get_state()
    assert state['status'] != 'ready', (state['status'], state['tag'], bool(state['zip_path']))
    assert state['zip_path'] == ''
    assert transport.download_requests == 1
    assert not list((scripts / 'efit_update_cache').glob('*.zip'))


def test_old_discovery_cannot_publish_into_a_registered_new_lifetime(subject):
    updater, transport, _ = subject
    transport.check_resume.clear()
    updater.check_for_update()
    assert transport.check_started.wait(10)
    updater.shutdown()
    updater.activate()
    transport.check_resume.set()
    finished(updater._owner.check_thread)
    assert updater.get_status() == 'idle'
    assert updater.get_state()['tag'] == ''
    discover(updater)
    assert updater.get_state()['tag'] == 'v9.0.0'


def test_retry_wait_uses_the_retired_lifetime_after_registration_changes(subject):
    updater, transport, _ = subject
    retired = updater._owner.lifetime
    updater.shutdown()
    updater.activate()
    calls = []

    def unavailable(request, timeout):
        calls.append(request)
        raise updater.urllib.error.URLError(OSError('controlled unavailable transport'))

    result = transport.production_retry(SimpleNamespace(open=unavailable), req='controlled request',
                                        cancellation=retired)
    assert result is None
    assert calls == ['controlled request']
    assert not updater._owner.lifetime.is_set()


@pytest.mark.parametrize('download', [False, True])
def test_retired_worker_does_not_retry_under_a_new_registration(subject, monkeypatch, download):
    updater, transport, scripts = subject
    discover(updater)
    started, resume = threading.Event(), threading.Event()
    requests = []

    def unavailable(request, timeout):
        requests.append(request.full_url)
        started.set()
        assert resume.wait(10), 'Controlled connection was not released'
        raise updater.urllib.error.URLError(OSError('controlled unavailable transport'))

    monkeypatch.setattr(updater, '_urlopen_with_retry', transport.production_retry)
    monkeypatch.setattr(updater.urllib.request, 'build_opener',
                        lambda *handlers: SimpleNamespace(open=unavailable))
    if download:
        updater.download_and_prepare()
        thread = updater._owner.download_thread
    else:
        updater.check_for_update()
        thread = updater._owner.check_thread
    try:
        assert started.wait(10), 'Worker did not start its connection'
        updater.shutdown()
        updater.activate()
    finally:
        resume.set()
    finished(thread)
    assert len(requests) == 1
    assert updater.get_status() == 'idle'
    assert updater.get_state()['zip_path'] == ''
    assert not list((scripts / 'efit_update_cache').glob('*.zip'))


def test_retry_keeps_three_attempts_and_the_existing_backoff(subject):
    updater, transport, _ = subject
    calls, waits = [], []
    expected = object()

    def flaky(request, timeout):
        calls.append(request)
        if len(calls) < 3:
            raise updater.urllib.error.URLError(OSError('controlled unavailable transport'))
        return expected

    def wait(timeout):
        waits.append(timeout)
        return False

    result = transport.production_retry(SimpleNamespace(open=flaky), req='controlled request',
                                        cancellation=SimpleNamespace(wait=wait))
    assert result is expected
    assert calls == ['controlled request'] * 3
    assert waits == [1, 2]


def test_unregister_during_preparation_prevents_install_handoff(subject, monkeypatch):
    updater, _, scripts = subject
    discover(updater)
    download(updater)
    replace = updater.os.replace
    launches = []

    def unregister_after_script_write(source, target):
        replace(source, target)
        if str(target).endswith('_efit_pending_update.py'):
            updater.shutdown()

    monkeypatch.setattr(updater.os, 'replace', unregister_after_script_write)
    monkeypatch.setattr(updater.subprocess, 'Popen', lambda *args, **kwargs: launches.append(args))
    updater.install_and_restart()
    assert not launches
    assert updater.get_status() == 'idle'
    assert not list((scripts / 'startup').iterdir())


def test_install_handoff_keeps_verified_digest_after_another_discovery(subject, monkeypatch):
    updater, transport, scripts = subject
    discover(updater)
    download(updater)
    verified_path = updater.get_state()['zip_path']
    transport.release = release('v9.1.0', ARCHIVE_B, blender_min='6.0.0')
    discover(updater)
    displayed = updater.get_state()
    assert {key: displayed[key] for key in RELEASE_B} == RELEASE_B
    observed = {}

    def observe_launch(*args, **kwargs):
        observed.update(json.loads((scripts / 'startup' / '_efit_update_paths.json').read_text()))
        raise OSError('controlled observation')

    monkeypatch.setattr(updater.subprocess, 'Popen', observe_launch)
    updater.install_and_restart()
    assert observed['zip_path'] == verified_path
    assert observed['expected_sha256'] == hashlib.sha256(ARCHIVE_A).hexdigest()
    assert Path(verified_path).read_bytes() == ARCHIVE_A
    assert not list((scripts / 'startup').iterdir())


def test_launch_failure_reports_error_and_removes_pending_install_files(subject, monkeypatch):
    updater, _, scripts = subject
    discover(updater)
    download(updater)

    def refuse_launch(*args, **kwargs):
        raise OSError('controlled launch refusal')

    monkeypatch.setattr(updater.subprocess, 'Popen', refuse_launch)
    updater.install_and_restart()
    state = updater.get_state()
    assert state['status'] == 'error'
    assert state['error'] == 'Could not launch Blender: controlled launch refusal'
    assert Path(state['zip_path']).read_bytes() == ARCHIVE_A
    assert {key: state[key] for key in RELEASE_A} == RELEASE_A
    assert not list((scripts / 'startup').iterdir())


@pytest.mark.parametrize('ready', [False, True])
def test_populated_snapshot_is_isolated_from_caller_changes(subject, ready):
    updater, _, _ = subject
    assert updater.get_state() == {
        'status': 'idle', 'tag': '', 'version': None, 'url': '', 'zip_path': '',
        'progress': 0., 'error': '', 'blender_min': None, 'blender_blocked': False,
        'blender_min_required': None, 'expected_sha256': None}
    discover(updater)
    if ready:
        download(updater)
    snapshot = updater.get_state()
    expected = dict(RELEASE_A, status='ready' if ready else 'available',
                    zip_path=snapshot['zip_path'] if ready else '', progress=1. if ready else 0., error='')
    assert snapshot == expected
    if ready:
        assert Path(snapshot['zip_path']).read_bytes() == ARCHIVE_A
    snapshot.update(tag='caller', version=(0,), url='caller', expected_sha256='caller',
                    blender_min=(99,), blender_min_required=(99,), blender_blocked=True,
                    status='error', zip_path='caller', progress=-1., error='caller')
    snapshot.clear()
    assert updater.get_state() == expected


@pytest.mark.parametrize('digest', [None, '0' * 64])
def test_failed_later_download_keeps_legacy_path_without_install_authority(subject, monkeypatch, digest):
    updater, transport, scripts = subject
    discover(updater)
    download(updater)
    verified_path = updater.get_state()['zip_path']
    transport.release = release('v9.1.0', ARCHIVE_B, blender_min='6.0.0')
    transport.release['body'] = 'BLENDER_MIN=6.0.0' + ('' if digest is None else '\nSHA256: ' + digest)
    discover(updater)
    download(updater)
    state = updater.get_state()
    assert state['status'] == 'error' and 'SHA-256' in state['error']
    assert state['zip_path'] == verified_path
    assert state['tag'] == 'v9.1.0' and state['expected_sha256'] == digest
    assert Path(verified_path).read_bytes() == ARCHIVE_A
    launches = []
    monkeypatch.setattr(updater.subprocess, 'Popen', lambda *args, **kwargs: launches.append(args))
    updater.install_and_restart()
    assert not launches and not (scripts / 'startup').exists()
    assert updater.get_state()['zip_path'] == verified_path
    assert updater.get_state()['error'] == 'Downloaded zip not found'


def test_success_after_discovery_error_preserves_legacy_error_text(subject):
    updater, transport, _ = subject
    discover(updater)
    transport.resume.clear()
    updater.download_and_prepare()
    assert transport.started.wait(10)
    transport.release = {'tag_name': 'v9.1.0', 'assets': []}
    updater.check_for_update()
    finished(updater._owner.check_thread)
    assert updater.get_state()['error'] == 'No zip asset in release'
    transport.resume.set()
    finished(updater._owner.download_thread)
    state = updater.get_state()
    assert state['status'] == 'ready' and state['error'] == 'No zip asset in release'
    assert {key: state[key] for key in RELEASE_A} == RELEASE_A
    assert Path(state['zip_path']).read_bytes() == ARCHIVE_A


@pytest.mark.parametrize('nightly,installed,version,remote_stamp,installed_stamp,expected', [
    (False, 'stable', '1.0.5', '', '', 'available'),
    (False, 'stable', '1.0.4', '', '', 'up_to_date'),
    (False, 'stable', '1.0.3', '', '', 'up_to_date'),
    (False, 'nightly', '1.0.4', '', '', 'available'),
    (False, 'nightly', '1.0.3', '', '', 'up_to_date'),
    (True, 'stable', '1.0.4', '202611011200', '', 'available'),
    (True, 'stable', '1.0.3', '202611011200', '', 'up_to_date'),
    (True, 'nightly', '1.0.4', '202611011200', '202610301200', 'available'),
    (True, 'nightly', '1.0.4', '202611011200', '202611011200', 'up_to_date'),
    (True, 'nightly', '1.0.4', '202611011200', '202611021200', 'up_to_date'),
    (True, 'nightly', '1.0.5', '202610301200', '202611021200', 'available'),
    (True, 'nightly', '1.0.3', '202611021200', '202610301200', 'up_to_date'),
])
def test_discovery_keeps_channel_and_version_comparison_policy(
        subject, monkeypatch, nightly, installed, version, remote_stamp, installed_stamp, expected):
    updater, transport, _ = subject
    monkeypatch.setattr(updater, '_CURRENT_VERSION', (1, 0, 4))
    monkeypatch.setattr(updater, '_installed_channel', lambda: installed)
    monkeypatch.setattr(updater, '_installed_nightly_ts', lambda: installed_stamp)
    updater.bpy.context.scene.efit_props.use_nightly_channel = nightly
    tag = 'nightly' if nightly else 'v' + version
    transport.release = release(tag, ARCHIVE_A)
    if nightly:
        transport.release['assets'][0]['name'] = f'ElasticClothingFit-v{version}-nightly-{remote_stamp}.zip'
    updater.check_for_update()
    finished(updater._owner.check_thread)
    state = updater.get_state()
    assert state['status'] == expected
    assert state['tag'] == tag
    assert state['expected_sha256'] == hashlib.sha256(ARCHIVE_A).hexdigest()
