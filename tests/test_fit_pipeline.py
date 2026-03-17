# test_fit_pipeline.py
# End-to-end fit pipeline test.
#
# REQUIRES:
#   - elastic_fit addon installed and enabled.
#   - A .blend file with a known body mesh and clothing mesh.
#     Set BLEND_PATH, BODY_NAME, CLOTHING_NAME below.
#
# Run each STEP_* block via mcp__blender__execute_blender_code in order.

BLEND_PATH    = r"C:\Users\Staples\Documents\GitHub\Elastic-Clothing-Fit\tests\ECF_Test.blend"
BODY_NAME     = "Body"
CLOTHING_NAME = "Outfit"

# ============================================================
# STEP 1-3: Load scene, pick meshes, run fit
# ============================================================
STEP_1_TO_3 = '''
import bpy
import sys

BLEND_PATH    = r"C:\\Users\\Staples\\Documents\\GitHub\\Elastic-Clothing-Fit\\tests\\ECF_Test.blend"
BODY_NAME     = "Body"
CLOTHING_NAME = "Outfit"

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
_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=_win, area=_area):
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
CLOTHING_NAME = "Outfit"
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
# STEP 5: Verify no clipping via ray cast
# ============================================================
STEP_5 = '''
import bpy
from mathutils.bvhtree import BVHTree
import mathutils
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 5: Verify no clipping (ray cast inside-test) ===")
BODY_NAME     = "Body"
CLOTHING_NAME = "Outfit"

# Maximum acceptable fraction of fitted vertices that may be inside the body.
# 10% tolerance reflects the test mesh's baseline clipping characteristics --
# the ECF_Test.blend crotch region has inward-pointing normals that produce
# genuine penetration without the hull proxy enabled. The hull test suite
# (test_proxy_hull.py) verifies that hull=True reduces this number.
MAX_CLIP_FRACTION = 0.10

p      = bpy.context.scene.efit_props
cloth  = bpy.data.objects[CLOTHING_NAME]
body   = bpy.data.objects[BODY_NAME]

body_verts = [v.co.copy() for v in body.data.vertices]
body_faces = [tuple(f.vertices) for f in body.data.polygons]
bvh        = BVHTree.FromPolygons(body_verts, body_faces)

fitted_indices = state._efit_cache.get("fitted_indices", [])
body_normals   = state._efit_cache.get("cloth_body_normals", {})

_assert_true(len(fitted_indices) > 0, "fitted_indices non-empty in cache")
_assert_true(len(body_normals) > 0,   "cloth_body_normals non-empty in cache")

# Inside-outside test via outward ray cast.
#
# A point is OUTSIDE the body if a ray cast outward (along the body surface
# normal at the nearest point) hits nothing -- there is no body surface
# between the point and infinity in that direction.
#
# A point is INSIDE the body if the outward ray hits the body surface --
# it has to pass through the body wall to get out.
#
# The body normal cached from find_nearest at fit time already points outward
# (away from the body interior) so +n_unit is the outward direction.
#
# Nudge the ray origin slightly outward to avoid a self-hit against the
# surface polygon directly beneath the vertex (dist ~0).
RAY_NUDGE = 1e-3
clipping  = 0
no_normal = 0

for vi in fitted_indices:
    n = body_normals.get(vi)
    if n is None or n.length < 1e-6:
        no_normal += 1
        continue

    co     = cloth.data.vertices[vi].co
    n_unit = n.normalized()

    # Nudge outward so the ray origin clears the body surface if the vertex
    # sits right on it (avoids self-hit at dist~0 on the surface polygon).
    origin    = co + n_unit * RAY_NUDGE
    direction = n_unit   # fire OUTWARD along body normal

    hit_loc, hit_normal, hit_idx, hit_dist = bvh.ray_cast(origin, direction)

    if hit_loc is not None:
        # Outward ray hit the body wall -- vertex is inside the body.
        clipping += 1

total       = len(fitted_indices)
pct         = (clipping / total * 100) if total else 0.0
max_allowed = int(total * MAX_CLIP_FRACTION)

print(f"  Checked {total} fitted vertices  |  inside body: {clipping} ({pct:.1f}%)  |  max allowed: {max_allowed} ({MAX_CLIP_FRACTION*100:.0f}%)")
if no_normal > 0:
    print(f"  Skipped {no_normal} vertices with no cached body normal")

_assert_true(
    clipping <= max_allowed,
    f"clipping within tolerance: {clipping}/{total} ({pct:.1f}%) <= {MAX_CLIP_FRACTION*100:.0f}% limit"
)
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

CLOTHING_NAME = "Outfit"
cloth = bpy.data.objects[CLOTHING_NAME]

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')

print("\\n=== STEP 6: Apply fit ===")
snapshot_after_fit = [v.co.copy() for v in cloth.data.vertices]
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.preview_apply()
_assert_true(result == {'FINISHED'}, "preview_apply returned FINISHED")
_assert_true(not state._efit_cache, "cache cleared after apply")

# Positions should be stable (not zeroed or wildly different).
after_apply = [v.co.copy() for v in cloth.data.vertices]
stable = all((a - b).length < 0.05 for a, b in zip(snapshot_after_fit, after_apply))
_assert_true(stable, "vertex positions stable after apply")

print("\\n=== STEP 7: Remove fit ===")
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.remove()
_assert_true(result == {'FINISHED'}, "efit.remove returned FINISHED")

# Verify originals were restored (positions should differ from post-fit).
restored = [v.co.copy() for v in cloth.data.vertices]
changed = sum(1 for a, b in zip(snapshot_after_fit, restored) if (a - b).length > 1e-6)
_assert_true(changed > 0, f"at least one vertex restored to pre-fit position ({changed} changed)")
'''
