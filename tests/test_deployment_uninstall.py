# tests/test_deployment_uninstall.py
#
# Deployment uninstall: remove elastic_fit addon directory if present.
# Runs with --factory-startup so no user addons (including MCP servers) load.
# Only file operations are needed -- prefs are not touched.
#
# Run via:
#   blender --background --factory-startup --python tests/test_deployment_uninstall.py
#
# Prints [PASS] / [FAIL] lines to stdout.

import os
import shutil

import bpy


def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition


print("\n=== STEP 1: Remove addon directory ===")
user_addons = bpy.utils.user_resource("SCRIPTS", path="addons")
addon_dir = os.path.join(user_addons, "elastic_fit")
if os.path.isdir(addon_dir):
    shutil.rmtree(addon_dir)
    _assert_true(not os.path.isdir(addon_dir), "addon directory removed")
else:
    print("  [PASS] addon directory not present (already clean)")

print("\n=== UNINSTALL COMPLETE ===")
