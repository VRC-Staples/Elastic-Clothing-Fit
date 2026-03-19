# suite_ux_tabs.py
# Run via: blender --background --python tests/blender_suites/suite_ux_tabs.py
# Optional: blender --background --python tests/blender_suites/suite_ux_tabs.py -- --blend-root <repo_root>
#
# REQUIRES: elastic_fit addon installed and enabled.
#           No active preview (fresh scene or after cancel/apply).
#           No .blend file is needed for these tests.
#
# Exit codes:
#   0 — all assertions passed
#   1 — one or more [FAIL] lines were printed

import sys

# ---- parse CLI args (accept --blend-root for interface consistency) ----
_blend_root = None
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_i = 0
while _i < len(_argv):
    if _argv[_i] == "--blend-root" and _i + 1 < len(_argv):
        _blend_root = _argv[_i + 1]
        _i += 2
    else:
        _i += 1

# ---- failure counter ----
_failed = 0

# ---- test helpers ----
def _assert_true(condition, label):
    global _failed
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        _failed += 1
    return condition

def _assert_equal(actual, expected, label):
    global _failed
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual!r}, expected {expected!r})"
    print(f"  [{status}] {label}{extra}")
    if not ok:
        _failed += 1
    return ok

def _assert_in_range(value, lo, hi, label):
    global _failed
    ok = lo <= value <= hi
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {value!r}, expected [{lo}, {hi}])"
    print(f"  [{status}] {label}{extra}")
    if not ok:
        _failed += 1
    return ok

def _assert_all_in_range(mapping, lo, hi, label):
    global _failed
    bad = {k: v for k, v in mapping.items() if not (lo <= v <= hi)}
    ok = len(bad) == 0
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  ({len(bad)} out of range, e.g. {list(bad.items())[:3]})"
    print(f"  [{status}] {label}{extra}")
    if not ok:
        _failed += 1
    return ok
# ---- end helpers ----

import bpy

p = bpy.context.scene.efit_props

print("\n=== STEP 1: Verify defaults ===")
_assert_equal(type(p).bl_rna.properties['ui_tab'].default,   'FULL', "ui_tab default is FULL")
_assert_equal(type(p).bl_rna.properties['fit_mode'].default, 'FULL', "fit_mode default is FULL")

print("\n=== STEP 2: Switch to EXCLUSIVE tab ===")
p.ui_tab = 'EXCLUSIVE'
_assert_equal(p.ui_tab,   'EXCLUSIVE', "ui_tab is EXCLUSIVE")
_assert_equal(p.fit_mode, 'EXCLUSIVE', "fit_mode synced to EXCLUSIVE")

print("\n=== STEP 3: Switch to UPDATE tab ===")
p.ui_tab = 'UPDATE'
_assert_equal(p.ui_tab, 'UPDATE', "ui_tab is UPDATE")
# fit_mode should be unchanged (UPDATE does not map to a fit_mode)
_assert_equal(p.fit_mode, 'EXCLUSIVE', "fit_mode unchanged when switching to UPDATE")

print("\n=== STEP 4: Switch back to FULL tab ===")
p.ui_tab = 'FULL'
_assert_equal(p.ui_tab,   'FULL', "ui_tab is FULL")
_assert_equal(p.fit_mode, 'FULL', "fit_mode synced back to FULL")

print("\n=== STEP 5: Verify collapse toggles exist and respond ===")
toggle_props = [
    "show_fit_settings",
    "show_shape_preservation",
    "show_preserve_group",
    "show_displacement_smoothing",
    "show_offset_fine_tuning",
    "show_misc",
]
for prop in toggle_props:
    _assert_true(hasattr(p, prop), f"property {prop!r} exists")
    original = getattr(p, prop)
    setattr(p, prop, not original)
    _assert_equal(getattr(p, prop), not original, f"{prop!r} toggles correctly")
    setattr(p, prop, original)  # restore

print("\n=== STEP 6: show_advanced is the master advanced toggle ===")
_assert_true(hasattr(p, 'show_advanced'), "show_advanced property present (master advanced toggle)")

print("\n=== ALL UX TAB TESTS COMPLETE ===")

sys.exit(0 if _failed == 0 else 1)
