# test_fit_pipeline.py
# End-to-end fit pipeline test.
#
# REQUIRES:
#   - elastic_fit addon installed and enabled.
#   - A .blend file with a known body mesh and clothing mesh.
#     Set BLEND_PATH, BODY_NAME, CLOTHING_NAME below.
#
# Run each STEP_* block via mcp__blender__execute_blender_code in order.

BLEND_PATH    = r"C:\path\to\test_scene.blend"  # Update before running.
BODY_NAME     = "Body"                           # Object name in the .blend.
CLOTHING_NAME = "Clothing"                       # Object name in the .blend.

# ============================================================
# STEP 1-3: Load scene, pick meshes, run fit
# ============================================================
STEP_1_TO_3 = '''
import bpy
import sys

BLEND_PATH    = r"C:\\path\\to\\test_scene.blend"
BODY_NAME     = "Body"
CLOTHING_NAME = "Clothing"

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

print("\\n=== STEP 1: Load blend file ===")
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
_assert_true(BODY_NAME     in bpy.data.objects, f"{BODY_NAME!r} exists in scene")
_assert_true(CLOTHING_NAME in bpy.data.objects, f"{CLOTHING_NAME!r} exists in scene")

print("\\n=== STEP 2: Set mesh pickers ===")
p = bpy.context.scene.efit_props
p.body_obj     = bpy.data.objects[BODY_NAME]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME]
_assert_equal(p.body_obj.name,     BODY_NAME,     "body_obj set correctly")
_assert_equal(p.clothing_obj.name, CLOTHING_NAME, "clothing_obj set correctly")

print("\\n=== STEP 3: Run fit and verify preview cache ===")
import elastic_fit.state as state
_assert_true(not state._efit_cache, "cache empty before fit")
result = bpy.ops.efit.fit()
_assert_equal(result, {'FINISHED'}, "efit.fit returned FINISHED")
_assert_true(bool(state._efit_cache),          "cache populated after fit")
_assert_true('cloth_displacements' in state._efit_cache, "cloth_displacements cached")
_assert_true('fitted_indices'      in state._efit_cache, "fitted_indices cached")
_assert_true('cloth_body_distances' in state._efit_cache, "cloth_body_distances cached")
print("  Cache keys:", list(state._efit_cache.keys()))
'''

# ============================================================
# STEP 4: Adjust fit_amount slider, verify vertices moved
# ============================================================
STEP_4 = '''
import bpy
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 4: Adjust fit_amount, verify vertices moved ===")
CLOTHING_NAME = "Clothing"
p     = bpy.context.scene.efit_props
cloth = bpy.data.objects[CLOTHING_NAME]

# Snapshot current positions.
before = [v.co.copy() for v in cloth.data.vertices]
old_amount = p.fit_amount

# Change fit_amount and let the update callback fire.
p.fit_amount = max(0.0, old_amount - 0.2)

after = [v.co.copy() for v in cloth.data.vertices]

moved = sum(1 for a, b in zip(before, after) if (a - b).length > 1e-6)
_assert_true(moved > 0, f"at least one vertex moved after fit_amount change ({moved} moved)")

# Restore.
p.fit_amount = old_amount
'''

# ============================================================
# STEP 5: Verify no clipping
# ============================================================
STEP_5 = '''
import bpy
from mathutils.bvhtree import BVHTree
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 5: Verify no clipping ===")
BODY_NAME     = "Body"
CLOTHING_NAME = "Clothing"
p      = bpy.context.scene.efit_props
cloth  = bpy.data.objects[CLOTHING_NAME]
body   = bpy.data.objects[BODY_NAME]
offset = p.offset
epsilon = 1e-4

body_verts = [v.co.copy() for v in body.data.vertices]
body_faces = [tuple(f.vertices) for f in body.data.polygons]
bvh        = BVHTree.FromPolygons(body_verts, body_faces)

fitted_indices = state._efit_cache.get('fitted_indices', [])
clipping = 0
for vi in fitted_indices:
    co  = cloth.data.vertices[vi].co
    loc, normal, face_idx, dist = bvh.find_nearest(co)
    if dist is not None and dist < (offset - epsilon):
        clipping += 1

_assert_true(clipping == 0, f"no fitted vertices clip through body (checked {len(fitted_indices)})")
if clipping > 0:
    print(f"    {clipping} vertices are inside the body surface")
'''

# ============================================================
# STEP 6-7: Apply and verify clean state; Remove and verify restore
# ============================================================
STEP_6_TO_7 = '''
import bpy
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

CLOTHING_NAME = "Clothing"
cloth = bpy.data.objects[CLOTHING_NAME]

print("\\n=== STEP 6: Apply fit ===")
snapshot_after_fit = [v.co.copy() for v in cloth.data.vertices]
result = bpy.ops.efit.preview_apply()
_assert_true(result == {'FINISHED'}, "preview_apply returned FINISHED")
_assert_true(not state._efit_cache, "cache cleared after apply")

# Positions should be stable (not zeroed or wildly different).
after_apply = [v.co.copy() for v in cloth.data.vertices]
stable = all((a - b).length < 0.05 for a, b in zip(snapshot_after_fit, after_apply))
_assert_true(stable, "vertex positions stable after apply")

print("\\n=== STEP 7: Remove fit ===")
result = bpy.ops.efit.remove()
_assert_true(result == {'FINISHED'}, "efit.remove returned FINISHED")

# Verify originals were restored (positions should differ from post-fit).
restored = [v.co.copy() for v in cloth.data.vertices]
changed = sum(1 for a, b in zip(snapshot_after_fit, restored) if (a - b).length > 1e-6)
_assert_true(changed > 0, f"at least one vertex restored to pre-fit position ({changed} changed)")
'''
