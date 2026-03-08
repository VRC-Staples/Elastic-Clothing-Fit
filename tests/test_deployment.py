# test_deployment.py
# Deployment test: install, enable, verify, disable, uninstall, restart, reinstall.
#
# REQUIRES: A packaged .zip of the addon at ZIP_PATH (set below).
# RESTART NOTE: This test has a break point after uninstall (step 7).
#   Phase 1 (steps 1-7) runs in MCP session A.
#   Restart Blender, then run Phase 2 (steps 8-9) in MCP session B.

ZIP_PATH = r"C:\path\to\elastic_fit.zip"   # Update before running.

# ============================================================
# PHASE 1 -- Run in MCP session A
# ============================================================
PHASE_1 = '''
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

ZIP_PATH = r"C:\\path\\to\\elastic_fit.zip"  # Update before running.

print("\\n=== STEP 1: Verify addon not installed ===")
_assert_true(
    'elastic_fit' not in bpy.context.preferences.addons,
    "elastic_fit not in addons before install"
)

print("\\n=== STEP 2: Install from zip ===")
result = bpy.ops.preferences.addon_install(filepath=ZIP_PATH, overwrite=True)
_assert_equal(result, {'FINISHED'}, "addon_install returned FINISHED")

print("\\n=== STEP 3: Enable addon ===")
result = bpy.ops.preferences.addon_enable(module='elastic_fit')
_assert_equal(result, {'FINISHED'}, "addon_enable returned FINISHED")

print("\\n=== STEP 4: Verify registration ===")
_assert_true(
    'elastic_fit' in bpy.context.preferences.addons,
    "elastic_fit in addons after enable"
)
_assert_true(
    hasattr(bpy.context.scene, 'efit_props'),
    "efit_props registered on scene"
)
p = bpy.context.scene.efit_props
_assert_equal(p.ui_tab,   'FULL', "ui_tab default is FULL")
_assert_equal(p.fit_mode, 'FULL', "fit_mode default is FULL")
_assert_true(
    bpy.utils.find_spec('elastic_fit') is not None or
    'SVRC_PT_elastic_fit' in dir(bpy.types),
    "panel class registered"
)

print("\\n=== STEP 5: Disable addon ===")
result = bpy.ops.preferences.addon_disable(module='elastic_fit')
_assert_equal(result, {'FINISHED'}, "addon_disable returned FINISHED")

print("\\n=== STEP 6: Verify cleanup ===")
_assert_true(
    'elastic_fit' not in bpy.context.preferences.addons,
    "elastic_fit removed from addons after disable"
)
_assert_true(
    not hasattr(bpy.context.scene, 'efit_props'),
    "efit_props unregistered from scene"
)

print("\\n=== STEP 7: Uninstall addon ===")
result = bpy.ops.preferences.addon_remove(module='elastic_fit')
_assert_equal(result, {'FINISHED'}, "addon_remove returned FINISHED")

print("\\n=== PHASE 1 COMPLETE -- Restart Blender, then run PHASE_2 ===")
'''

# ============================================================
# PHASE 2 -- Run in MCP session B (after Blender restart)
# ============================================================
PHASE_2 = '''
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

ZIP_PATH = r"C:\\path\\to\\elastic_fit.zip"  # Update before running.

print("\\n=== STEP 8: Reinstall after restart ===")
_assert_true(
    'elastic_fit' not in bpy.context.preferences.addons,
    "clean state after restart"
)
bpy.ops.preferences.addon_install(filepath=ZIP_PATH, overwrite=True)
bpy.ops.preferences.addon_enable(module='elastic_fit')

print("\\n=== STEP 9: Verify registration after reinstall ===")
_assert_true(
    'elastic_fit' in bpy.context.preferences.addons,
    "elastic_fit in addons after reinstall"
)
_assert_true(
    hasattr(bpy.context.scene, 'efit_props'),
    "efit_props registered after reinstall"
)
p = bpy.context.scene.efit_props
_assert_equal(p.ui_tab,   'FULL', "ui_tab default is FULL after reinstall")
_assert_equal(p.fit_mode, 'FULL', "fit_mode default is FULL after reinstall")

print("\\n=== PHASE 2 COMPLETE ===")
'''
