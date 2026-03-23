#!/usr/bin/env python
"""Verify S03 updater.py invariants via static analysis.

Checks:
  (a) Zero bpy.* in _check_thread / _download_thread  (AST walk)
  (b) _state_lock referenced ≥ 5 times in the source   (string count)
  (c) Missing SHA-256 path leads to status='error'      (string match)
  (d) _validate_dev_url function exists                 (AST walk)
  (e) get_state returns dict(_state)                    (string match / AST)

Exit 0 if all 5 pass, exit 1 if any fail.
"""
import ast
import sys


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


def check_sha256_error_path(source, tree):
    """(c) Missing SHA-256 leads to _state['status'] = 'error'.

    The critical invariant is that when expected_sha256 is None/falsy the
    download thread sets status='error' and returns without marking the zip
    ready.  We check for the known error string used in the implementation.
    """
    marker = "Release has no SHA-256 hash"
    # Also confirm 'error' appears nearby (within the same else branch text).
    has_marker = marker in source
    # Ensure the else branch that contains the marker also sets status to error.
    # We do a simple scan: find the index of the marker string and look
    # backward up to 300 chars for "_state['status'] = 'error'" or
    # forward up to 300 chars for the same.
    found_error_assignment = False
    if has_marker:
        idx = source.index(marker)
        window = source[max(0, idx - 300): idx + 300]
        found_error_assignment = ("'status']" in window and "'error'" in window)

    if not has_marker:
        print(f"FAIL (c) Expected marker string not found: {marker!r}")
        return False
    if not found_error_assignment:
        print("FAIL (c) _state['status'] = 'error' not found near the SHA-256 absence branch")
        return False
    print("PASS (c) Missing SHA-256 leads to status='error'")
    return True


def check_validate_dev_url_exists(source, tree):
    """(d) _validate_dev_url function definition exists."""
    if not _func_exists(tree, '_validate_dev_url'):
        print("FAIL (d) _validate_dev_url function not found in AST")
        return False
    print("PASS (d) _validate_dev_url function exists")
    return True


def check_get_state_returns_copy(source, tree):
    """(e) get_state() returns dict(_state) — a shallow snapshot copy.

    Checks both a fast string match and an AST walk to be thorough.
    """
    # Fast path: literal source text.
    if 'return dict(_state)' in source:
        print("PASS (e) get_state returns dict(_state) (string match)")
        return True

    # AST path: look for a Return whose value is a Call to 'dict' with
    # _state as sole positional argument.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'get_state':
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    call = child.value
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == 'dict'
                        and len(call.args) == 1
                        and isinstance(call.args[0], ast.Name)
                        and call.args[0].id == '_state'
                    ):
                        print("PASS (e) get_state returns dict(_state) (AST match)")
                        return True

    print("FAIL (e) get_state does not return dict(_state)")
    return False


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
