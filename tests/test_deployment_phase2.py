# tests/test_deployment_phase2.py
#
# Deployment test Phase 2: reinstall after clean state, verify registration.
# Simulates a post-restart Blender session (fresh process = no prior addon state).
#
# Run via:
#   blender --background --python tests/test_deployment_phase2.py -- --zip <path>
#
# Prints [PASS] / [FAIL] lines to stdout.

import os
import sys

import bpy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _get_zip_path():
    argv = sys.argv
    if "--" in argv:
        rest = argv[argv.index("--") + 1:]
        for i, a in enumerate(rest):
            if a == "--zip" and i + 1 < len(rest):
                return rest[i + 1]
    print("[FAIL] --zip argument not provided to phase2 script")
    sys.exit(1)


def _uninstall_addon(module_name):
    """
    Remove the addon directory from the user addon path.
    Used instead of bpy.ops.preferences.addon_remove which requires UI context.
    """
    import addon_utils
    import shutil

    for base_path in addon_utils.paths():
        addon_dir = os.path.join(base_path, module_name)
        if os.path.isdir(addon_dir):
            shutil.rmtree(addon_dir)
            return True
    return False


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

ZIP_PATH = _get_zip_path()

print("\n=== STEP 8: Reinstall after restart ===")
_assert_true(
    "elastic_fit" not in bpy.context.preferences.addons,
    "clean state after restart",
)
bpy.ops.preferences.addon_install(filepath=ZIP_PATH, overwrite=True)
bpy.ops.preferences.addon_enable(module="elastic_fit")

print("\n=== STEP 9: Verify registration after reinstall ===")
_assert_true(
    "elastic_fit" in bpy.context.preferences.addons,
    "elastic_fit in addons after reinstall",
)
_assert_true(
    hasattr(bpy.context.scene, "efit_props"),
    "efit_props registered after reinstall",
)
p = bpy.context.scene.efit_props
_assert_equal(p.ui_tab, "FULL", "ui_tab default is FULL after reinstall")
_assert_equal(p.fit_mode, "FULL", "fit_mode default is FULL after reinstall")

print("\n=== STEP 10: Cleanup ===")
result = bpy.ops.preferences.addon_disable(module="elastic_fit")
_assert_equal(result, {"FINISHED"}, "addon_disable returned FINISHED")
removed = _uninstall_addon("elastic_fit")
_assert_true(removed, "addon directory removed after phase2")

print("\n=== PHASE 2 COMPLETE ===")
