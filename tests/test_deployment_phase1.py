# tests/test_deployment_phase1.py
#
# Deployment test Phase 1: install, enable, verify, disable, verify cleanup, uninstall.
#
# Run via:
#   blender --background --python tests/test_deployment_phase1.py -- --zip <path>
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
    print("[FAIL] --zip argument not provided to phase1 script")
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

print("\n=== STEP 1: Verify addon not installed ===")
_assert_true(
    "elastic_fit" not in bpy.context.preferences.addons,
    "elastic_fit not in addons before install",
)

print("\n=== STEP 2: Install from zip ===")
result = bpy.ops.preferences.addon_install(filepath=ZIP_PATH, overwrite=True)
_assert_equal(result, {"FINISHED"}, "addon_install returned FINISHED")

print("\n=== STEP 3: Enable addon ===")
result = bpy.ops.preferences.addon_enable(module="elastic_fit")
_assert_equal(result, {"FINISHED"}, "addon_enable returned FINISHED")

print("\n=== STEP 4: Verify registration ===")
_assert_true(
    "elastic_fit" in bpy.context.preferences.addons,
    "elastic_fit in addons after enable",
)
_assert_true(
    hasattr(bpy.context.scene, "efit_props"),
    "efit_props registered on scene",
)
p = bpy.context.scene.efit_props
_assert_equal(p.ui_tab, "FULL", "ui_tab default is FULL")
_assert_equal(p.fit_mode, "FULL", "fit_mode default is FULL")
_assert_true(
    hasattr(bpy.types, "SVRC_PT_elastic_fit"),
    "panel class registered",
)

print("\n=== STEP 5: Disable addon ===")
result = bpy.ops.preferences.addon_disable(module="elastic_fit")
_assert_equal(result, {"FINISHED"}, "addon_disable returned FINISHED")

print("\n=== STEP 6: Verify cleanup ===")
_assert_true(
    "elastic_fit" not in bpy.context.preferences.addons,
    "elastic_fit removed from addons after disable",
)
_assert_true(
    not hasattr(bpy.context.scene, "efit_props"),
    "efit_props unregistered from scene",
)

print("\n=== STEP 7: Uninstall addon ===")
removed = _uninstall_addon("elastic_fit")
_assert_true(removed, "addon directory removed from user addons path")

print("\n=== PHASE 1 COMPLETE ===")
