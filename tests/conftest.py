# conftest.py
# Shared assertion helpers for Elastic Clothing Fit test scripts.
#
# These helpers are used in two ways:
#   1. Imported directly in pytest-compatible test modules.
#   2. Pasted inline into Blender headless scripts via the HELPERS_INLINE constant.
#
# To run a headless Blender test:
#   blender --background --python tests/test_<name>.py
#
# To import in a pytest module:
#   import sys, os
#   sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
#   from tests.conftest import assert_equal, assert_true, ...


def assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition


def assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    if ok:
        print(f"  [{status}] {label}")
    else:
        print(f"  [{status}] {label}  (got {actual!r}, expected {expected!r})")
    return ok


def assert_in_range(value, lo, hi, label):
    ok = lo <= value <= hi
    status = "PASS" if ok else "FAIL"
    if ok:
        print(f"  [{status}] {label}")
    else:
        print(f"  [{status}] {label}  (got {value!r}, expected [{lo}, {hi}])")
    return ok


def assert_all_in_range(mapping, lo, hi, label):
    bad = {k: v for k, v in mapping.items() if not (lo <= v <= hi)}
    ok = len(bad) == 0
    status = "PASS" if ok else "FAIL"
    if ok:
        print(f"  [{status}] {label}")
    else:
        print(f"  [{status}] {label}  ({len(bad)} values out of range, e.g. {list(bad.items())[:3]})")
    return ok


# Inline-paste version of the helpers for use inside Blender headless scripts.
# Copy everything between the START/END markers.

HELPERS_INLINE = '''
# ---- test helpers ----
def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_equal(actual, expected, label):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    return ok

def _assert_in_range(value, lo, hi, label):
    ok = lo <= value <= hi
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {value!r}, expected [{lo}, {hi}])"
    print(f"  [{status}] {label}{extra}")
    return ok

def _assert_all_in_range(mapping, lo, hi, label):
    bad = {k: v for k, v in mapping.items() if not (lo <= v <= hi)}
    ok = len(bad) == 0
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  ({len(bad)} out of range, e.g. {list(bad.items())[:3]})"
    print(f"  [{status}] {label}{extra}")
    return ok
# ---- end helpers ----
'''
