# test_ux_tabs.py
# UX tab switching and section collapse toggle tests.
#
# REQUIRES: elastic_fit addon installed and enabled.
#           No active preview (fresh scene or after cancel/apply).
#
# Run the single TEST_UX_TABS block via mcp__blender__execute_blender_code.

TEST_UX_TABS = '''
import bpy

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

p = bpy.context.scene.efit_props

print("\\n=== STEP 1: Verify defaults ===")
_assert_equal(p.ui_tab,   'FULL', "ui_tab default is FULL")
_assert_equal(p.fit_mode, 'FULL', "fit_mode default is FULL")

print("\\n=== STEP 2: Switch to EXCLUSIVE tab ===")
p.ui_tab = 'EXCLUSIVE'
_assert_equal(p.ui_tab,   'EXCLUSIVE', "ui_tab is EXCLUSIVE")
_assert_equal(p.fit_mode, 'EXCLUSIVE', "fit_mode synced to EXCLUSIVE")

print("\\n=== STEP 3: Switch to UPDATE tab ===")
p.ui_tab = 'UPDATE'
_assert_equal(p.ui_tab, 'UPDATE', "ui_tab is UPDATE")
# fit_mode should be unchanged (UPDATE does not map to a fit_mode)
_assert_equal(p.fit_mode, 'EXCLUSIVE', "fit_mode unchanged when switching to UPDATE")

print("\\n=== STEP 4: Switch back to FULL tab ===")
p.ui_tab = 'FULL'
_assert_equal(p.ui_tab,   'FULL', "ui_tab is FULL")
_assert_equal(p.fit_mode, 'FULL', "fit_mode synced back to FULL")

print("\\n=== STEP 5: Verify collapse toggles exist and respond ===")
toggle_props = [
    "show_fit_settings",
    "show_shape_preservation",
    "show_preserve_group",
    "show_displacement_smoothing",
    "show_offset_fine_tuning",
    "show_post_fit",
    "show_misc",
]
for prop in toggle_props:
    _assert_true(hasattr(p, prop), f"property {prop!r} exists")
    original = getattr(p, prop)
    setattr(p, prop, not original)
    _assert_equal(getattr(p, prop), not original, f"{prop!r} toggles correctly")
    setattr(p, prop, original)  # restore

print("\\n=== STEP 6: show_advanced is the master advanced toggle ===")
_assert_true(hasattr(p, 'show_advanced'), "show_advanced property present (master advanced toggle)")

print("\\n=== ALL UX TAB TESTS COMPLETE ===")
'''
