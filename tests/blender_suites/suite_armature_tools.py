# suite_armature_tools.py
# Run via: blender --background --python tests/blender_suites/suite_armature_tools.py -- --blend-root <repo_root>
#
# REQUIRES: elastic_fit addon installed and enabled.
#           No active preview (fresh scene or after cancel/apply).
#           A VIEW_3D area must be open in Blender.
#           Steps 4-8 use ECF_Test2.blend in legacy mode; use --programmatic to synthesize armatures.
#
# Exit codes:
#   0 — all assertions passed
#   1 — one or more [FAIL] lines were printed

import sys
import os

# ---- parse CLI args ----
_blend_root = None
_programmatic = False
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
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
    print("[ERROR] --blend-root <repo_root> is required unless --programmatic is set")
    sys.exit(1)

BLEND_PATH = os.path.join(_blend_root, "tests", "ECF_Test2.blend") if _blend_root else ""

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

def _assert_approx(actual, expected, tol, label):
    global _failed
    ok = abs(actual - expected) < tol
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  (got {actual:.4f}, expected {expected:.4f} tol={tol})"
    print(f"  [{status}] {label}{extra}")
    if not ok:
        _failed += 1
    return ok
# ---- end helpers ----

import bpy

sys.path.insert(0, os.path.dirname(__file__))
from _programmatic_geometry import clear_programmatic_objects, get_view3d_context


def _make_merge_test_armatures():
    """Build synthetic base/donor armatures plus donor child mesh for merge tests."""
    clear_programmatic_objects()

    win, area, region = get_view3d_context()

    base_data = bpy.data.armatures.new("ECF_MergeBaseData")
    base_arm = bpy.data.objects.new("Armature", base_data)
    bpy.context.scene.collection.objects.link(base_arm)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    base_arm.select_set(True)
    bpy.context.view_layer.objects.active = base_arm
    with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
        bpy.ops.object.mode_set(mode="EDIT")
    eb = base_arm.data.edit_bones.new("Hips")
    eb.head = (0, 0, 0)
    eb.tail = (0, 0, 0.1)
    eb = base_arm.data.edit_bones.new("Spine")
    eb.head = (0, 0, 1.0)
    eb.tail = (0, 0, 1.1)
    eb = base_arm.data.edit_bones.new("LeftArm")
    eb.head = (-0.3, 0, 1.0)
    eb.tail = (-0.6, 0, 1.0)
    with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
        bpy.ops.object.mode_set(mode="OBJECT")

    donor_data = bpy.data.armatures.new("ECF_MergeDonorData")
    donor_arm = bpy.data.objects.new("Armature F", donor_data)
    donor_arm.location = (0.2, 0, 0)
    bpy.context.scene.collection.objects.link(donor_arm)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    donor_arm.select_set(True)
    bpy.context.view_layer.objects.active = donor_arm
    with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
        bpy.ops.object.mode_set(mode="EDIT")
    eb = donor_arm.data.edit_bones.new("hips")
    eb.head = (0, 0, 0)
    eb.tail = (0, 0, 0.1)
    eb = donor_arm.data.edit_bones.new("spine")
    eb.head = (0, 0, 1.0)
    eb.tail = (0, 0, 1.1)
    eb = donor_arm.data.edit_bones.new("RightArm")
    eb.head = (0.3, 0, 1.0)
    eb.tail = (0.6, 0, 1.0)
    with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
        bpy.ops.object.mode_set(mode="OBJECT")

    donor_child_mesh_data = bpy.data.meshes.new("ECF_MergeDonorChildMesh")
    donor_child_mesh_data.from_pydata(
        [(-0.1, -0.1, 0.0), (0.1, -0.1, 0.0), (0.1, 0.1, 0.0), (-0.1, 0.1, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    donor_child_mesh = bpy.data.objects.new("ECF_MergeDonorChild", donor_child_mesh_data)
    donor_child_mesh.parent = donor_arm
    donor_child_mesh.parent_type = "ARMATURE"
    arm_mod = donor_child_mesh.modifiers.new("Armature", "ARMATURE")
    arm_mod.object = donor_arm
    bpy.context.scene.collection.objects.link(donor_child_mesh)

    bpy.context.view_layer.update()
    return base_arm, donor_arm, donor_child_mesh

# ============================================================
# STEP 1: Properties exist with correct defaults
# ============================================================
p = bpy.context.scene.efit_props

print("\n=== STEP 1: Armature tools properties exist with correct defaults ===")

# Section collapse toggles
_assert_true(hasattr(p, 'show_armature_display'), "show_armature_display property exists")
_assert_true(hasattr(p, 'show_merge_armatures'),  "show_merge_armatures property exists")
_assert_equal(p.show_armature_display, False, "show_armature_display default is False")
_assert_equal(p.show_merge_armatures,  False, "show_merge_armatures default is False")

# Armature display properties
_assert_true(hasattr(p, 'armature_display_type'),    "armature_display_type property exists")
_assert_true(hasattr(p, 'armature_show_in_front'),   "armature_show_in_front property exists")
_assert_equal(p.armature_display_type,         'STICK', "armature_display_type default is STICK")
_assert_equal(p.armature_show_in_front,        False,   "armature_show_in_front default is False")

# Merge armature properties
_assert_true(hasattr(p, 'merge_source_armature'), "merge_source_armature property exists")
_assert_true(hasattr(p, 'merge_target_armature'), "merge_target_armature property exists")
_assert_true(hasattr(p, 'merge_bones'),            "merge_bones property exists")
_assert_true(hasattr(p, 'merge_align_first'),      "merge_align_first property exists")
_assert_equal(p.merge_source_armature, None,  "merge_source_armature default is None")
_assert_equal(p.merge_target_armature, None,  "merge_target_armature default is None")
_assert_equal(p.merge_bones,           True,  "merge_bones default is True")
_assert_equal(p.merge_align_first,     False, "merge_align_first default is False")

print("\n=== STEP 1 COMPLETE ===")


# ============================================================
# STEP 2: TOOLS tab switching does not affect fit_mode
# ============================================================
print("\n=== STEP 2: TOOLS tab switching ===")

p.ui_tab = 'FULL'
_assert_equal(p.ui_tab,   'FULL', "ui_tab starts as FULL")
_assert_equal(p.fit_mode, 'FULL', "fit_mode synced to FULL")

p.ui_tab = 'TOOLS'
_assert_equal(p.ui_tab,   'TOOLS', "ui_tab set to TOOLS")
# TOOLS does not map to a fit_mode value, so fit_mode must stay unchanged.
_assert_equal(p.fit_mode, 'FULL', "fit_mode unchanged when switching to TOOLS")

# Verify exclusive mode toggle works after leaving TOOLS.
p.ui_tab             = 'FULL'
p.use_exclusive_mode = True
_assert_equal(p.fit_mode, 'EXCLUSIVE', "fit_mode syncs to EXCLUSIVE via use_exclusive_mode toggle")
p.use_exclusive_mode = False
_assert_equal(p.fit_mode, 'FULL', "fit_mode syncs back to FULL when toggle disabled")

print("\n=== STEP 2 COMPLETE ===")


# ============================================================
# STEP 3: Armature display operator applies to active armature
# ============================================================
print("\n=== STEP 3: efit.armature_display applies to active armature ===")

# Create a test armature directly (no ops, no VIEW_3D context needed).
data_a = bpy.data.armatures.new("ECF_Test_DispData_A")
arm_a  = bpy.data.objects.new("ECF_Test_DispArm_A", data_a)
bpy.context.scene.collection.objects.link(arm_a)

# Set target display properties.
p.armature_display_type  = 'WIRE'
p.armature_show_in_front = True

# Select and activate the armature.
for o in bpy.context.view_layer.objects:
    o.select_set(False)
arm_a.select_set(True)
bpy.context.view_layer.objects.active = arm_a

result = bpy.ops.efit.armature_display()

_assert_equal(result, {'FINISHED'}, "efit.armature_display returned FINISHED")
_assert_equal(arm_a.data.display_type, 'WIRE', "arm_a display_type set to WIRE")
_assert_equal(arm_a.show_in_front, True, "arm_a show_in_front set to True")

# A second armature should not be affected.
data_b = bpy.data.armatures.new("ECF_Test_DispData_B")
arm_b  = bpy.data.objects.new("ECF_Test_DispArm_B", data_b)
bpy.context.scene.collection.objects.link(arm_b)

p.armature_display_type  = 'OCTAHEDRAL'
p.armature_show_in_front = False

for o in bpy.context.view_layer.objects:
    o.select_set(False)
arm_b.select_set(True)
bpy.context.view_layer.objects.active = arm_b

result2 = bpy.ops.efit.armature_display()

_assert_equal(result2, {'FINISHED'}, "efit.armature_display returned FINISHED for arm_b")
_assert_equal(arm_b.data.display_type, 'OCTAHEDRAL', "arm_b display_type set to OCTAHEDRAL")
_assert_equal(arm_b.show_in_front, False, "arm_b show_in_front set to False")
# arm_a should still have its previous settings.
_assert_equal(arm_a.data.display_type, 'WIRE', "arm_a display_type unchanged (still WIRE)")
_assert_equal(arm_a.show_in_front, True, "arm_a show_in_front unchanged (still True)")

# Reset properties.
p.armature_display_type  = 'STICK'
p.armature_show_in_front = False

# Clean up.
bpy.data.objects.remove(arm_a, do_unlink=True)
bpy.data.objects.remove(arm_b, do_unlink=True)
bpy.data.armatures.remove(data_a)
bpy.data.armatures.remove(data_b)

_assert_true("ECF_Test_DispArm_A" not in bpy.data.objects, "test armature A cleaned up")
_assert_true("ECF_Test_DispArm_B" not in bpy.data.objects, "test armature B cleaned up")

print("\n=== STEP 3 COMPLETE ===")


# ============================================================
# STEP 4: Merge armatures with merge_bones=True joins both into base
#         Uses ECF_Test2.blend with real armatures.
# ============================================================
print("\n=== STEP 4: efit.merge_armatures with merge_bones=True (join) ===")

if _programmatic:
    base_arm, donor_arm, _ = _make_merge_test_armatures()
    print("[INFO] programmatic geometry: synthetic armatures")
else:
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    base_arm = bpy.data.objects["Armature"]
    donor_arm = bpy.data.objects["Armature F"]

base_name = base_arm.name
donor_name = donor_arm.name

_assert_true(base_name in bpy.data.objects, "ECF_Test2: base armature exists")
_assert_true(donor_name in bpy.data.objects, "ECF_Test2: donor armature exists")

# Record donor bones and child meshes before merge.
donor_bone_names  = [b.name for b in donor_arm.data.bones]
donor_child_names = [o.name for o in bpy.data.objects if o.parent == donor_arm and o.type == 'MESH']

_assert_true(len(donor_bone_names) > 0,  "donor has bones to transfer")

p = bpy.context.scene.efit_props
p.merge_source_armature = base_arm
p.merge_target_armature = donor_arm
p.merge_bones           = True
p.merge_align_first     = False

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.merge_armatures()

_assert_equal(result, {'FINISHED'}, "efit.merge_armatures returned FINISHED")
_assert_true(base_name in bpy.data.objects, "base armature still present after join")
_assert_true(donor_name not in bpy.data.objects, "donor armature removed after join")

# Donor bones should now be in base. Use case-insensitive check because the
# merge preserves base-armature casing when names differ only by case.
base_arm = bpy.data.objects[base_name]
base_bone_names = [b.name for b in base_arm.data.bones]
base_bone_lower = {n.lower() for n in base_bone_names}
for bname in donor_bone_names:
    _assert_true(bname.lower() in base_bone_lower, f"donor bone {bname!r} transferred to base")

# Child meshes reparented to base with armature modifiers retargeted.
for cname in donor_child_names:
    obj = bpy.data.objects.get(cname)
    if obj:
        _assert_equal(obj.parent, base_arm, f"{cname}: reparented to base armature")
        arm_mod = next((m for m in obj.modifiers if m.type == 'ARMATURE'), None)
        if arm_mod:
            _assert_equal(arm_mod.object, base_arm, f"{cname}: armature modifier retargeted to base")

p.merge_source_armature = None
p.merge_target_armature = None

print("\n=== STEP 4 COMPLETE ===")


# ============================================================
# STEP 5: Merge armatures with merge_bones=False reparents child meshes
#         Uses ECF_Test2.blend with real armatures.
# ============================================================
print("\n=== STEP 5: efit.merge_armatures with merge_bones=False (reparent children) ===")

if _programmatic:
    base_arm, donor_arm, _ = _make_merge_test_armatures()
    print("[INFO] programmatic geometry: synthetic armatures")
else:
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    base_arm = bpy.data.objects["Armature"]
    donor_arm = bpy.data.objects["Armature F"]

base_name = base_arm.name
donor_name = donor_arm.name

_assert_true(base_name in bpy.data.objects, "ECF_Test2: base armature exists")
_assert_true(donor_name in bpy.data.objects, "ECF_Test2: donor armature exists")

# Record donor child meshes before merge.
donor_child_names = [o.name for o in bpy.data.objects if o.parent == donor_arm and o.type == 'MESH']
_assert_true(len(donor_child_names) > 0, "donor has child meshes to reparent")

p = bpy.context.scene.efit_props
p.merge_source_armature = base_arm
p.merge_target_armature = donor_arm
p.merge_bones           = False
p.merge_align_first     = False

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.merge_armatures()

_assert_equal(result, {'FINISHED'}, "efit.merge_armatures returned FINISHED")

# Both armatures still exist -- no join happened.
_assert_true(base_name in bpy.data.objects, "base armature still exists (no join)")
_assert_true(donor_name in bpy.data.objects, "donor armature still exists (no join)")

# Child meshes reparented to base with armature modifiers retargeted.
base_arm = bpy.data.objects[base_name]
for cname in donor_child_names:
    obj = bpy.data.objects.get(cname)
    if obj:
        _assert_equal(obj.parent, base_arm, f"{cname}: reparented to base armature")
        arm_mod = next((m for m in obj.modifiers if m.type == 'ARMATURE'), None)
        if arm_mod:
            _assert_equal(arm_mod.object, base_arm, f"{cname}: armature modifier retargeted to base")

p.merge_source_armature = None
p.merge_target_armature = None
p.merge_bones           = True  # restore default

print("\n=== STEP 5 COMPLETE ===")


# ============================================================
# STEP 6: merge_align_first=True aligns donor to base before merge
# ============================================================
import mathutils

print("\n=== STEP 6: merge_align_first=True ===")

# ------------------------------------------------------------------
# Sub-test A: real armatures from ECF_Test2.blend with shared bones.
# After alignment, shared bone world positions should match base
# within tolerance. donor.location must not be wildly offset.
# ------------------------------------------------------------------
print("\n-- Sub-test A: alignment with real armatures from ECF_Test2.blend --")

if _programmatic:
    base_arm, donor_arm, _ = _make_merge_test_armatures()
    print("[INFO] programmatic geometry: synthetic armatures")
else:
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    base_arm = bpy.data.objects["Armature"]
    donor_arm = bpy.data.objects["Armature F"]

base_name = base_arm.name
donor_name = donor_arm.name

_assert_true(base_name in bpy.data.objects, "ECF_Test2: base armature exists")
_assert_true(donor_name in bpy.data.objects, "ECF_Test2: donor armature exists")

base_map  = {b.name.lower(): b.name for b in base_arm.data.bones}
donor_map = {b.name.lower(): b.name for b in donor_arm.data.bones}
shared_keys = [k for k in base_map if k in donor_map]

_assert_true(len(shared_keys) >= 2, f"Sub-A precondition: at least 2 shared bones (found {len(shared_keys)})")

# Record base bone world positions for shared bones.
base_bone_world = {
    k: base_arm.matrix_world @ base_arm.data.bones[base_map[k]].head_local
    for k in shared_keys
}

donor_loc_before_length = donor_arm.location.length

p = bpy.context.scene.efit_props
p.merge_source_armature = base_arm
p.merge_target_armature = donor_arm
p.merge_bones           = False
p.merge_align_first     = True

win    = bpy.context.window_manager.windows[0]
area   = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=win, area=area):
    result_a = bpy.ops.efit.merge_armatures()

_assert_equal(result_a, {'FINISHED'}, "Sub-A: merge returned FINISHED")

# Shared bone world positions should approximately match base after alignment.
for k in shared_keys[:4]:  # check up to 4 shared bones
    dw = donor_arm.matrix_world @ donor_arm.data.bones[donor_map[k]].head_local
    bw = base_bone_world[k]
    _assert_approx(dw.x, bw.x, 0.1, f"Sub-A: {donor_map[k]} world x aligned to base")
    _assert_approx(dw.y, bw.y, 0.1, f"Sub-A: {donor_map[k]} world y aligned to base")
    _assert_approx(dw.z, bw.z, 0.1, f"Sub-A: {donor_map[k]} world z aligned to base")

# donor.location must not be wildly offset (bug-fix validation).
base_loc   = base_arm.location
donor_loc  = donor_arm.location
dist_to_base = (donor_loc - base_loc).length
_assert_true(dist_to_base < 2.0, f"Sub-A: donor.location near base (dist={dist_to_base:.3f})")

p.merge_source_armature = None
p.merge_target_armature = None
p.merge_bones           = True
p.merge_align_first     = False

# ------------------------------------------------------------------
# Sub-test B: no shared bones -- alignment skipped, merge still FINISHED
# and donor location is unchanged.
# (Synthetic armatures -- this boundary condition does not need real data.)
# ------------------------------------------------------------------
print("\n-- Sub-test B: align skipped when armatures share fewer than 2 bone names --")

win    = bpy.context.window_manager.windows[0]
area   = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')

base_data = bpy.data.armatures.new("ECF_Test_SkipBaseData")
base_arm  = bpy.data.objects.new("ECF_Test_SkipBase", base_data)
base_arm.location = (0, 0, 0)
bpy.context.scene.collection.objects.link(base_arm)
for o in bpy.context.view_layer.objects: o.select_set(False)
base_arm.select_set(True)
bpy.context.view_layer.objects.active = base_arm
with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
    bpy.ops.object.mode_set(mode='EDIT')
eb = base_arm.data.edit_bones.new("BaseBone1"); eb.head=(0,0,0); eb.tail=(0,1,0)
eb = base_arm.data.edit_bones.new("BaseBone2"); eb.head=(0,0,2); eb.tail=(0,1,2)
with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
    bpy.ops.object.mode_set(mode='OBJECT')

donor_data = bpy.data.armatures.new("ECF_Test_SkipDonorData")
donor_arm  = bpy.data.objects.new("ECF_Test_SkipDonor", donor_data)
donor_arm.location = (5, 0, 0)
bpy.context.scene.collection.objects.link(donor_arm)
for o in bpy.context.view_layer.objects: o.select_set(False)
donor_arm.select_set(True)
bpy.context.view_layer.objects.active = donor_arm
with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
    bpy.ops.object.mode_set(mode='EDIT')
eb = donor_arm.data.edit_bones.new("DonorBone1"); eb.head=(0,0,0); eb.tail=(0,1,0)
with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
    bpy.ops.object.mode_set(mode='OBJECT')

donor_loc_before = tuple(donor_arm.location)

p = bpy.context.scene.efit_props
p.merge_source_armature = base_arm
p.merge_target_armature = donor_arm
p.merge_bones           = False
p.merge_align_first     = True

with bpy.context.temp_override(window=win, area=area):
    result_b = bpy.ops.efit.merge_armatures()

_assert_equal(result_b, {'FINISHED'}, "Sub-B: merge FINISHED even when alignment skipped")
_assert_equal(tuple(donor_arm.location), donor_loc_before, "Sub-B: donor location unchanged when align skipped")

bpy.data.objects.remove(base_arm,  do_unlink=True)
bpy.data.objects.remove(donor_arm, do_unlink=True)
bpy.data.armatures.remove(base_data)
bpy.data.armatures.remove(donor_data)
p.merge_source_armature = None
p.merge_target_armature = None
p.merge_bones           = True
p.merge_align_first     = False

_assert_true("ECF_Test_SkipBase"  not in bpy.data.objects, "skip test armatures cleaned up")
_assert_true("ECF_Test_SkipDonor" not in bpy.data.objects, "skip test armatures cleaned up")

print("\n=== STEP 6 COMPLETE ===")


# ============================================================
# STEP 7: Case-insensitive bone deduplication during merge
# ============================================================
print("\n=== STEP 7: case-insensitive bone deduplication ===")

# Build synthetic armatures: base has Hips/Spine (capitalised),
# donor has hips/spine (lower) plus FootL (unique).
win    = bpy.context.window_manager.windows[0]
area   = next(a for a in win.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")

base_data = bpy.data.armatures.new("ECF_Case_BaseData")
base_arm  = bpy.data.objects.new("ECF_Case_Base", base_data)
bpy.context.scene.collection.objects.link(base_arm)
for o in bpy.context.view_layer.objects: o.select_set(False)
base_arm.select_set(True)
bpy.context.view_layer.objects.active = base_arm
with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
    bpy.ops.object.mode_set(mode="EDIT")
eb = base_arm.data.edit_bones.new("Hips");  eb.head=(0,0,0); eb.tail=(0,1,0)
eb = base_arm.data.edit_bones.new("Spine"); eb.head=(0,0,1); eb.tail=(0,1,1)
with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
    bpy.ops.object.mode_set(mode="OBJECT")

donor_data = bpy.data.armatures.new("ECF_Case_DonorData")
donor_arm  = bpy.data.objects.new("ECF_Case_Donor", donor_data)
bpy.context.scene.collection.objects.link(donor_arm)
for o in bpy.context.view_layer.objects: o.select_set(False)
donor_arm.select_set(True)
bpy.context.view_layer.objects.active = donor_arm
with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
    bpy.ops.object.mode_set(mode="EDIT")
eb = donor_arm.data.edit_bones.new("hips");  eb.head=(0,0,0); eb.tail=(0,1,0)
eb = donor_arm.data.edit_bones.new("spine"); eb.head=(0,0,1); eb.tail=(0,1,1)
eb = donor_arm.data.edit_bones.new("FootL"); eb.head=(0,0,2); eb.tail=(0,1,2)
with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
    bpy.ops.object.mode_set(mode="OBJECT")

base_bone_count_before = len(base_arm.data.bones)

p = bpy.context.scene.efit_props
p.merge_source_armature = base_arm
p.merge_target_armature = donor_arm
p.merge_bones           = True
p.merge_align_first     = False

with bpy.context.temp_override(window=win, area=area):
    result = bpy.ops.efit.merge_armatures()

_assert_equal(result, {"FINISHED"}, "merge returned FINISHED")

# After join, only base armature should remain.
base_arm = bpy.data.objects.get("ECF_Case_Base")
_assert_true(base_arm is not None,               "base armature still present after join")
_assert_true("ECF_Case_Donor" not in bpy.data.objects, "donor removed after join")

base_bones = [b.name for b in base_arm.data.bones]
added = len(base_bones) - base_bone_count_before
_assert_equal(added, 1,              "exactly 1 unique donor bone added (FootL)")
_assert_true("Hips"  in base_bones, "Hips present (base casing preserved)")
_assert_true("hips" not in base_bones, "hips NOT present as duplicate")
_assert_true("Spine" in base_bones, "Spine present (base casing preserved)")
_assert_true("spine" not in base_bones, "spine NOT present as duplicate")
_assert_true("FootL" in base_bones, "FootL present (unique donor bone added)")

p.merge_source_armature = None
p.merge_target_armature = None
p.merge_bones           = True
p.merge_align_first     = False

print("\n=== STEP 7 COMPLETE ===")


# ============================================================
# STEP 8: Synthetic alignment test -- scale + translation
# ============================================================
print("\n=== STEP 8: synthetic alignment (scale + translation) ===")

win    = bpy.context.window_manager.windows[0]
area   = next(a for a in win.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")

# Base armature: at origin, unit scale, two bones.
base_data = bpy.data.armatures.new("ECF_Align8_BaseData")
base_arm  = bpy.data.objects.new("ECF_Align8_Base", base_data)
base_arm.location = (0, 0, 0)
bpy.context.scene.collection.objects.link(base_arm)
for o in bpy.context.view_layer.objects: o.select_set(False)
base_arm.select_set(True)
bpy.context.view_layer.objects.active = base_arm
with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
    bpy.ops.object.mode_set(mode="EDIT")
eb = base_arm.data.edit_bones.new("Hips");  eb.head=(0,0,0);   eb.tail=(0,0,0.1)
eb = base_arm.data.edit_bones.new("Spine"); eb.head=(0,0,1.0); eb.tail=(0,0,1.1)
with bpy.context.temp_override(window=win, area=area, region=region, active_object=base_arm):
    bpy.ops.object.mode_set(mode="OBJECT")

# Donor armature: offset 5 on X, bones at double height (scale=2 in z).
donor_data = bpy.data.armatures.new("ECF_Align8_DonorData")
donor_arm  = bpy.data.objects.new("ECF_Align8_Donor", donor_data)
donor_arm.location = (5, 0, 0)
bpy.context.scene.collection.objects.link(donor_arm)
for o in bpy.context.view_layer.objects: o.select_set(False)
donor_arm.select_set(True)
bpy.context.view_layer.objects.active = donor_arm
with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
    bpy.ops.object.mode_set(mode="EDIT")
eb = donor_arm.data.edit_bones.new("hips");  eb.head=(0,0,0);   eb.tail=(0,0,0.2)
eb = donor_arm.data.edit_bones.new("spine"); eb.head=(0,0,2.0); eb.tail=(0,0,2.2)
with bpy.context.temp_override(window=win, area=area, region=region, active_object=donor_arm):
    bpy.ops.object.mode_set(mode="OBJECT")

# Parented mesh: child of donor, should follow alignment automatically.
parented_mesh_data = bpy.data.meshes.new("ECF_Align8_MeshData")
parented_mesh_data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
parented_mesh = bpy.data.objects.new("ECF_Align8_Mesh", parented_mesh_data)
parented_mesh.location = (5, 0, 0)
parented_mesh.parent = donor_arm
bpy.context.scene.collection.objects.link(parented_mesh)

# Unparented mesh: Armature modifier pointing to donor but no parent.
unparented_mesh_data = bpy.data.meshes.new("ECF_Align8_UnparentedMeshData")
unparented_mesh_data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
unparented_mesh = bpy.data.objects.new("ECF_Align8_UnparentedMesh", unparented_mesh_data)
unparented_mesh.location = (5, 0, 0)
arm_mod = unparented_mesh.modifiers.new("Armature", 'ARMATURE')
arm_mod.object = donor_arm
bpy.context.scene.collection.objects.link(unparented_mesh)

bpy.context.view_layer.update()

# Record world positions before merge so we can verify movement delta.
parented_world_before  = mathutils.Vector(parented_mesh.matrix_world.translation)
unparented_world_before = mathutils.Vector(unparented_mesh.matrix_world.translation)
donor_world_before     = mathutils.Vector(donor_arm.matrix_world.translation)

p = bpy.context.scene.efit_props
p.merge_source_armature = base_arm
p.merge_target_armature = donor_arm
p.merge_bones           = False
p.merge_align_first     = True

with bpy.context.temp_override(window=win, area=area):
    result = bpy.ops.efit.merge_armatures()

bpy.context.view_layer.update()

_assert_true(result == {"FINISHED"}, "STEP 8: merge returned FINISHED")

# Donor should have moved significantly closer to base (was 5 units away on X).
dist_after = (donor_arm.location - base_arm.location).length
_assert_true(dist_after < 1.0, f"STEP 8: donor moved near base (dist={dist_after:.4f})")

# Root bones should be close after alignment (translation only, no scale).
bpy.context.view_layer.update()
src_roots = [b for b in donor_arm.data.bones if b.parent is None]
tgt_roots = [b for b in base_arm.data.bones if b.parent is None]
src_root_world = donor_arm.matrix_world @ src_roots[0].head_local
tgt_root_world = base_arm.matrix_world @ tgt_roots[0].head_local
root_dist = (src_root_world - tgt_root_world).length
_assert_true(root_dist < 0.01, f"STEP 8: root bones aligned (dist={root_dist:.4f})")

# Parented mesh world position should have shifted by the same delta as the donor
# (it inherits the parent transform automatically -- no extra code needed).
# donor_delta is how far the donor moved; the child should move by the same amount.
bpy.context.view_layer.update()
donor_world_after   = mathutils.Vector(donor_arm.matrix_world.translation)
donor_delta         = donor_world_after - donor_world_before
parented_world_after = mathutils.Vector(parented_mesh.matrix_world.translation)
parented_delta       = parented_world_after - parented_world_before
parented_delta_err   = (parented_delta - donor_delta).length
_assert_true(parented_delta_err < 0.1,
    f"STEP 8: parented mesh moved with donor (delta error={parented_delta_err:.4f})")

# Unparented mesh should also have moved near base.
# The operator explicitly translates unparented meshes that reference the donor via modifier.
unparented_world = mathutils.Vector(unparented_mesh.matrix_world.translation)
base_world = mathutils.Vector(base_arm.matrix_world.translation)
unparented_dist = (unparented_world - base_world).length
_assert_true(unparented_dist < 1.0, f"STEP 8: unparented mesh world pos near base (dist={unparented_dist:.4f})")

# Cleanup.
bpy.data.objects.remove(parented_mesh,   do_unlink=True)
bpy.data.objects.remove(unparented_mesh, do_unlink=True)
bpy.data.meshes.remove(parented_mesh_data)
bpy.data.meshes.remove(unparented_mesh_data)
bpy.data.objects.remove(donor_arm, do_unlink=True)
bpy.data.objects.remove(base_arm,  do_unlink=True)
bpy.data.armatures.remove(donor_data)
bpy.data.armatures.remove(base_data)

p.merge_source_armature = None
p.merge_target_armature = None
p.merge_bones           = True
p.merge_align_first     = False

_assert_true("ECF_Align8_Base"             not in bpy.data.objects, "STEP 8 base cleaned up")
_assert_true("ECF_Align8_Donor"            not in bpy.data.objects, "STEP 8 donor cleaned up")
_assert_true("ECF_Align8_Mesh"             not in bpy.data.objects, "STEP 8 parented mesh cleaned up")
_assert_true("ECF_Align8_UnparentedMesh"   not in bpy.data.objects, "STEP 8 unparented mesh cleaned up")

print("\n=== STEP 8 COMPLETE ===")
print("\n=== ALL ARMATURE TOOLS TESTS COMPLETE ===")

sys.exit(0 if _failed == 0 else 1)
