#!/usr/bin/env python
"""Check updater thread boundaries and production state outcomes.

The missing-digest and snapshot checks run the actual updater with controlled
transport and Blender services. Other existing static checks remain in place.
Exit 0 if all five checks pass, or 1 if any check fails.
"""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _bpy_attrs_in_func(tree, func_name):
    """Return a list of source lines where bpy.* is accessed inside func_name.

    Walks the full AST of the function body looking for any ast.Attribute whose
    *root* (leftmost) Name is 'bpy'.  Returns a list of (lineno, snippet)
    tuples; empty list means the invariant holds.
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute):
                    # Walk to the root of the attribute chain.
                    root = child
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id == 'bpy':
                        hits.append((child.lineno, ast.dump(child)[:80]))
    return hits


def _func_exists(tree, func_name):
    """Return True if a top-level (or nested) FunctionDef with func_name exists."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return True
    return False


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_no_bpy_in_threads(source, tree):
    """(a) Zero bpy.* accesses inside _check_thread and _download_thread."""
    all_hits = []
    for fn in ('_check_thread', '_download_thread'):
        hits = _bpy_attrs_in_func(tree, fn)
        for lineno, snippet in hits:
            all_hits.append(f"  {fn}:{lineno} — {snippet}")
    if all_hits:
        print("FAIL (a) bpy.* found in thread functions:")
        for h in all_hits:
            print(h)
        return False
    print("PASS (a) Zero bpy.* in _check_thread and _download_thread")
    return True


def check_state_lock_count(source, tree):
    """(b) _state_lock referenced ≥ 5 times (1 def + ≥ 4 usages)."""
    count = source.count('_state_lock')
    if count < 5:
        print(f"FAIL (b) _state_lock count = {count}, expected >= 5")
        return False
    print(f"PASS (b) _state_lock referenced {count} times (>= 5)")
    return True


@contextlib.contextmanager
def _runtime_updater():
    completed = threading.Event()
    previous_bpy = sys.modules.get('bpy')
    previous_threads = set(threading.enumerate())
    name = 'ecf_updater_verification'
    with tempfile.TemporaryDirectory(prefix='ecf-updater-verification-') as directory:
        bpy = SimpleNamespace(
            app=SimpleNamespace(background=False, version=(5, 1, 0)),
            context=SimpleNamespace(scene=SimpleNamespace(efit_props=SimpleNamespace(
                use_nightly_channel=False, dev_update_url=''))),
            utils=SimpleNamespace(user_resource=lambda kind: directory))
        sys.modules['bpy'] = bpy
        try:
            path = Path(__file__).resolve().parents[1] / 'elastic_fit' / 'updater.py'
            spec = importlib.util.spec_from_file_location(name, path)
            updater = importlib.util.module_from_spec(spec)
            sys.modules[name] = updater
            spec.loader.exec_module(updater)

            def response(_opener, *, req, timeout, cancellation=None):
                if req.full_url.startswith('https://api.github.com/'):
                    body = json.dumps({'tag_name': 'v99.0.0', 'body': '', 'assets': [
                        {'name': 'test.zip', 'browser_download_url': 'https://github.com/test/test.zip'}]}).encode()
                else:
                    body = b'controlled unverified bytes'
                result = io.BytesIO(body)
                result.headers = {'Content-Length': str(len(body))}
                return result

            def redraw():
                if updater.get_status() in ('available', 'ready', 'error'):
                    completed.set()

            updater._urlopen_with_retry = response
            updater._schedule_redraw = redraw
            yield updater, completed
        finally:
            for thread in set(threading.enumerate()) - previous_threads:
                thread.join(5)
            sys.modules.pop(name, None)
            if previous_bpy is None:
                sys.modules.pop('bpy', None)
            else:
                sys.modules['bpy'] = previous_bpy


def check_sha256_error_path(source, tree):
    """(c) Missing SHA-256 rejects actual downloaded bytes without readiness."""
    with _runtime_updater() as (updater, completed):
        updater.check_for_update()
        if not completed.wait(5) or updater.get_status() != 'available':
            print('FAIL (c) Controlled release discovery did not complete')
            return False
        completed.clear()
        updater.download_and_prepare()
        if not completed.wait(5):
            print('FAIL (c) Controlled download did not complete')
            return False
        result = updater.get_state()
        if (result['status'] != 'error' or result['zip_path']
                or 'Release has no SHA-256 hash' not in result['error']):
            print(f'FAIL (c) Missing digest did not reject readiness: {result}')
            return False
    print("PASS (c) Actual missing-digest download rejected with status='error'")
    return True


def check_validate_dev_url_exists(source, tree):
    """(d) _validate_dev_url function definition exists."""
    if not _func_exists(tree, '_validate_dev_url'):
        print("FAIL (d) _validate_dev_url function not found in AST")
        return False
    print("PASS (d) _validate_dev_url function exists")
    return True


def check_get_state_returns_copy(source, tree):
    """(e) A caller cannot mutate updater state through a returned snapshot."""
    with _runtime_updater() as (updater, _):
        snapshot = updater.get_state()
        snapshot['status'] = 'ready'
        snapshot['tag'] = 'caller mutation'
        if updater.get_status() != 'idle' or updater.get_state()['tag']:
            print('FAIL (e) Mutating a snapshot changed production updater state')
            return False
    print('PASS (e) Caller snapshot mutations leave production updater state unchanged')
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    target = 'elastic_fit/updater.py'
    try:
        source = _load(target)
    except FileNotFoundError:
        print(f"ERROR: could not read {target}")
        sys.exit(2)

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"ERROR: syntax error in {target}: {exc}")
        sys.exit(2)

    checks = [
        check_no_bpy_in_threads,
        check_state_lock_count,
        check_sha256_error_path,
        check_validate_dev_url_exists,
        check_get_state_returns_copy,
    ]

    passed = 0
    failed = 0
    for check in checks:
        ok = check(source, tree)
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
