# suite_vg_stability.py
# Regression suite for vertex group name stability across dynamic list mutations.
#
# Run via: blender --background --python tests/blender_suites/suite_vg_stability.py -- --blend-root <repo_root>
#
# REQUIRES: elastic_fit addon installed and enabled.
#           tests/ECF_Test3.blend with Body and outfit objects.
#
# Exit codes:
#   0 — all assertions passed
#   1 — one or more [FAIL] lines were printed
#
# What this suite protects against:
#   Previously group_name fields used dynamic EnumProperty, which stores selections
#   as integer indices. When a vertex group was added or removed from the clothing mesh
#   the stored integer remapped to a different group (index-drift). All group_name fields
#   now use StringProperty, which stores the identifier string directly.

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _programmatic_geometry import (
    clear_programmatic_objects,
    make_clothing_with_groups,
    make_icosphere,
)

# ---- parse CLI args ----
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_blend_root = None
_programmatic = False
_i = 0
while _i < len(_argv):
    if _argv[_i] == "--blend-root" and _i + 1 < len(_argv):
        _blend_root = _argv[_i + 1]
        _i += 2
    elif _argv[_i] == "--programmatic":
        _programmatic = True
        _i += 1
    else:
        _i += 1

if _blend_root is None and not _programmatic:
    print("[ERROR] --blend-root <repo_root> is required (unless --programmatic is set)")
    sys.exit(1)

BLEND_PATH = os.path.join(_blend_root, "tests", "ECF_Test3.blend") if _blend_root else None
BODY_NAME = "Body"
CLOTHING_NAME = "Outfit"

# ---- failure counter ----
_failed = 0


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


# ---- import bpy ----
import bpy

# ============================================================
# STEP 1: Load scene and set clothing/body pickers
# ============================================================
print("\n=== STEP 1: Load blend file and set mesh pickers ===")
if _programmatic:
    clear_programmatic_objects()
    body = make_icosphere("ECF_Body", radius=1.0)
    cloth_obj = make_clothing_with_groups(
        "ECF_Clothing",
        radius=1.1,
        group_names=("StableGroupA", "StableGroupB"),
    )
    print("[INFO] programmatic geometry: ECF_Body, ECF_Clothing")
else:
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    cloth_obj = bpy.data.objects[CLOTHING_NAME]
    body = bpy.data.objects[BODY_NAME]

_assert_true(body.name in bpy.data.objects, f"{body.name!r} exists in scene")
_assert_true(cloth_obj.name in bpy.data.objects, f"{cloth_obj.name!r} exists in scene")

p = bpy.context.scene.efit_props
p.body_obj = body
p.clothing_obj = cloth_obj

_assert_equal(p.body_obj.name, body.name, "body_obj set")
_assert_equal(p.clothing_obj.name, cloth_obj.name, "clothing_obj set")

# ---- discover two real vertex groups to use as anchors ----
vg_names = [vg.name for vg in cloth_obj.vertex_groups]
_assert_true(len(vg_names) >= 2,
             f"clothing mesh has at least 2 vertex groups (found {len(vg_names)}): {vg_names}")

vg_anchor = vg_names[0]   # first group — used as the stable reference throughout
vg_second = vg_names[1]   # second group

# ============================================================
# STEP 2: offset_groups — add entry, verify name survives
#         adding a new vertex group to the mesh (the drift case)
# ============================================================
print("\n=== STEP 2: offset_groups — stability across vertex group addition ===")

p.offset_groups.clear()
og = p.offset_groups.add()
og.group_name = vg_anchor
_assert_equal(og.group_name, vg_anchor, "STEP 2: offset_groups[0].group_name set to anchor")

# Add a new vertex group to the clothing mesh — this is what triggered drift before.
new_vg_name = "_efit_regression_drift_test_"
new_vg = cloth_obj.vertex_groups.new(name=new_vg_name)
_assert_true(new_vg_name in [vg.name for vg in cloth_obj.vertex_groups],
             "STEP 2: new vertex group added to mesh")

# The critical assertion — must still read the anchor name, not the shifted one.
_assert_equal(og.group_name, vg_anchor,
              f"STEP 2: offset_groups[0].group_name stable after adding '{new_vg_name}'")

# ---- also verify: removing the newly added group doesn't cause drift ----
cloth_obj.vertex_groups.remove(new_vg)
_assert_equal(og.group_name, vg_anchor,
              "STEP 2: offset_groups[0].group_name stable after removing new group")

# ---- verify a second entry also holds its name ----
og2 = p.offset_groups.add()
og2.group_name = vg_second
new_vg2 = cloth_obj.vertex_groups.new(name="_efit_regression_drift2_")
_assert_equal(og.group_name,  vg_anchor, "STEP 2: first entry stable with two entries present")
_assert_equal(og2.group_name, vg_second, "STEP 2: second entry stable with two entries present")
cloth_obj.vertex_groups.remove(cloth_obj.vertex_groups[new_vg2.name])

p.offset_groups.clear()

# ============================================================
# STEP 3: exclusive_groups — same drift scenario
# ============================================================
print("\n=== STEP 3: exclusive_groups — stability across vertex group addition ===")

p.exclusive_groups.clear()
eg = p.exclusive_groups.add()
eg.group_name = vg_anchor
_assert_equal(eg.group_name, vg_anchor, "STEP 3: exclusive_groups[0].group_name set to anchor")

new_vg3 = cloth_obj.vertex_groups.new(name="_efit_regression_excl_")
_assert_equal(eg.group_name, vg_anchor,
              "STEP 3: exclusive_groups[0].group_name stable after adding new group")
cloth_obj.vertex_groups.remove(cloth_obj.vertex_groups[new_vg3.name])
_assert_equal(eg.group_name, vg_anchor,
              "STEP 3: exclusive_groups[0].group_name stable after removing new group")

p.exclusive_groups.clear()

# ============================================================
# STEP 4: proximity_groups — same drift scenario
# ============================================================
print("\n=== STEP 4: proximity_groups — stability across vertex group addition ===")

p.proximity_groups.clear()
pg = p.proximity_groups.add()
pg.group_name = vg_anchor
_assert_equal(pg.group_name, vg_anchor, "STEP 4: proximity_groups[0].group_name set to anchor")

new_vg4 = cloth_obj.vertex_groups.new(name="_efit_regression_prox_")
_assert_equal(pg.group_name, vg_anchor,
              "STEP 4: proximity_groups[0].group_name stable after adding new group")
cloth_obj.vertex_groups.remove(cloth_obj.vertex_groups[new_vg4.name])
_assert_equal(pg.group_name, vg_anchor,
              "STEP 4: proximity_groups[0].group_name stable after removing new group")

p.proximity_groups.clear()

# ============================================================
# STEP 5: preserve_group — same drift scenario
# ============================================================
print("\n=== STEP 5: preserve_group — stability across vertex group addition ===")

p.preserve_group = vg_anchor
_assert_equal(p.preserve_group, vg_anchor, "STEP 5: preserve_group set to anchor")

new_vg5 = cloth_obj.vertex_groups.new(name="_efit_regression_pres_")
_assert_equal(p.preserve_group, vg_anchor,
              "STEP 5: preserve_group stable after adding new group")
cloth_obj.vertex_groups.remove(cloth_obj.vertex_groups[new_vg5.name])
_assert_equal(p.preserve_group, vg_anchor,
              "STEP 5: preserve_group stable after removing new group")

p.preserve_group = ""

# ============================================================
# STEP 6: empty string / unset group resolves to no group
# ============================================================
print("\n=== STEP 6: empty group_name resolves correctly ===")
from elastic_fit.properties import _resolve_vg_name

p.offset_groups.clear()
og_blank = p.offset_groups.add()
og_blank.group_name = ""
_assert_equal(_resolve_vg_name(og_blank.group_name), "",
              "STEP 6: _resolve_vg_name('') returns empty string")

p.preserve_group = ""
_assert_equal(_resolve_vg_name(p.preserve_group), "",
              "STEP 6: _resolve_vg_name on unset preserve_group returns empty string")

p.offset_groups.clear()

# ============================================================
# STEP 7: group_name set to a name that no longer exists on
#         the mesh — _resolve_vg_name still returns the string
#         (callers do their own .get() check)
# ============================================================
print("\n=== STEP 7: stale group_name (group deleted) returns string, not error ===")
p.offset_groups.clear()
og_stale = p.offset_groups.add()
og_stale.group_name = "DeletedGroup"
_assert_equal(_resolve_vg_name(og_stale.group_name), "DeletedGroup",
              "STEP 7: _resolve_vg_name returns stale name without error")
_assert_true(cloth_obj.vertex_groups.get("DeletedGroup") is None,
             "STEP 7: stale group correctly absent from vertex_groups")
p.offset_groups.clear()

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*50}")
if _failed == 0:
    print(f"[PASS] VG Stability suite: all checks passed")
else:
    print(f"[FAIL] VG Stability suite: {_failed} check(s) failed")
print(f"{'='*50}\n")

sys.exit(0 if _failed == 0 else 1)
