# tests/test_deployment_uninstall.py
#
# Deployment uninstall: disable elastic_fit in preferences and remove its
# addon directory. Runs WITHOUT --factory-startup so user preferences are
# loaded and can be properly cleared before the directory is deleted.
#
# Run via:
#   blender --background --python tests/test_deployment_uninstall.py
#
# Prints [PASS] / [FAIL] lines to stdout.

import os
import shutil

import bpy


def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition


print("\n=== STEP 1: Disable addon in preferences ===")
if "elastic_fit" in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_disable(module="elastic_fit")
    bpy.ops.wm.save_userpref()
    _assert_true(
        "elastic_fit" not in bpy.context.preferences.addons,
        "elastic_fit disabled in preferences",
    )
else:
    print("  [PASS] elastic_fit not enabled in preferences (already clean)")

print("\n=== STEP 2: Remove addon directory ===")
user_addons = bpy.utils.user_resource("SCRIPTS", path="addons")
addon_dir = os.path.join(user_addons, "elastic_fit")
if os.path.isdir(addon_dir):
    shutil.rmtree(addon_dir)
    _assert_true(not os.path.isdir(addon_dir), "addon directory removed")
else:
    print("  [PASS] addon directory not present (already clean)")

print("\n=== UNINSTALL COMPLETE ===")
