# suite_fit_pipeline.py
# Run via: blender --background --python tests/blender_suites/suite_fit_pipeline.py -- --blend-root <repo_root>
#
# REQUIRES: elastic_fit addon installed and enabled.
#           tests/ECF_Test.blend with Body and Outfit objects.
#
# Exit codes:
#   0 — all assertions passed
#   1 — one or more [FAIL] lines were printed

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _programmatic_geometry import (
    clear_programmatic_objects,
    get_view3d_context,
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

BLEND_PATH = os.path.join(_blend_root, "tests", "ECF_Test.blend") if _blend_root else None
BODY_NAME = "Body"
CLOTHING_NAME = "Outfit"

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

# ---- import bpy (Blender's Python API) ----
import bpy

# ============================================================
# STEP 1-3: Load scene, pick meshes, run fit
# ============================================================
print("\n=== STEP 1: Load blend file ===")
if _programmatic:
    clear_programmatic_objects()
    body = make_icosphere("ECF_Body", radius=1.0)
    cloth = make_icosphere("ECF_Clothing", radius=1.1)
    BODY_NAME_LOCAL = body.name
    CLOTHING_NAME_LOCAL = cloth.name
    print("[INFO] programmatic geometry: ECF_Body, ECF_Clothing")
else:
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    BODY_NAME_LOCAL = BODY_NAME
    CLOTHING_NAME_LOCAL = CLOTHING_NAME

_assert_true(BODY_NAME_LOCAL in bpy.data.objects, f"{BODY_NAME_LOCAL!r} exists in scene")
_assert_true(CLOTHING_NAME_LOCAL in bpy.data.objects, f"{CLOTHING_NAME_LOCAL!r} exists in scene")

print("\n=== STEP 2: Set mesh pickers ===")
p = bpy.context.scene.efit_props
p.body_obj = bpy.data.objects[BODY_NAME_LOCAL]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME_LOCAL]
_assert_equal(p.body_obj.name, BODY_NAME_LOCAL, "body_obj set correctly")
_assert_equal(p.clothing_obj.name, CLOTHING_NAME_LOCAL, "clothing_obj set correctly")

print("\n=== STEP 3: Run fit and verify preview cache ===")
import elastic_fit.state as state
_assert_true(not state._efit_cache, "cache empty before fit")
_win, _area, _region = get_view3d_context()
with bpy.context.temp_override(window=_win, area=_area, region=_region):
    result = bpy.ops.efit.fit()
_assert_equal(result, {'FINISHED'}, "efit.fit returned FINISHED")
_assert_true(bool(state._efit_cache),          "cache populated after fit")
_assert_true('cloth_displacements' in state._efit_cache, "cloth_displacements cached")
_assert_true('fitted_indices'      in state._efit_cache, "fitted_indices cached")
_assert_true('cloth_body_distances' in state._efit_cache, "cloth_body_distances cached")
print("  Cache keys:", list(state._efit_cache.keys()))

# ============================================================
# STEP 4: Adjust fit_amount slider, verify vertices moved
# ============================================================
print("\n=== STEP 4: Adjust fit_amount, verify vertices moved ===")
p = bpy.context.scene.efit_props
cloth = bpy.data.objects[CLOTHING_NAME_LOCAL]

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

# ============================================================
# STEP 5: Verify no clipping via ray cast
# ============================================================
print("\n=== STEP 5: Verify no clipping (ray cast inside-test) ===")
from mathutils.bvhtree import BVHTree
import mathutils

import numpy as np

# Maximum acceptable fraction of fitted vertices that may be inside the body.
# 10% tolerance reflects the test mesh's baseline clipping characteristics --
# the ECF_Test.blend crotch region has inward-pointing normals that produce
# genuine penetration without the hull proxy enabled. The hull test suite
# (suite_proxy_hull.py) verifies that hull=True reduces this number.
MAX_CLIP_FRACTION = 0.50 if _programmatic else 0.10
if _programmatic:
    print("[INFO] programmatic MAX_CLIP_FRACTION override: 50%")

p = bpy.context.scene.efit_props
cloth = bpy.data.objects[CLOTHING_NAME_LOCAL]
body = bpy.data.objects[BODY_NAME_LOCAL]

body_verts = [v.co.copy() for v in body.data.vertices]
body_faces = [tuple(f.vertices) for f in body.data.polygons]
bvh        = BVHTree.FromPolygons(body_verts, body_faces)

fitted_indices = state._efit_cache.get("fitted_indices", [])
body_normals   = state._efit_cache.get("cloth_body_normals", None)

_assert_true(len(fitted_indices) > 0, "fitted_indices non-empty in cache")
_assert_true(body_normals is not None and len(body_normals) > 0,
             "cloth_body_normals non-empty in cache")

# Build positional index map for ndarray access.
vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}

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
    pos = vi_to_pos.get(vi)
    if pos is None:
        no_normal += 1
        continue
    n = body_normals[pos]
    n_len = np.linalg.norm(n)
    if n_len < 1e-6:
        no_normal += 1
        continue

    co     = cloth.data.vertices[vi].co
    n_unit = n / n_len
    n_unit_vec = mathutils.Vector(n_unit)

    # Nudge outward so the ray origin clears the body surface if the vertex
    # sits right on it (avoids self-hit at dist~0 on the surface polygon).
    origin    = co + n_unit_vec * RAY_NUDGE
    direction = n_unit_vec   # fire OUTWARD along body normal

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

# ============================================================
# STEP 6-7: Apply and verify clean state; Remove and verify restore
# ============================================================
cloth = bpy.data.objects[CLOTHING_NAME_LOCAL]

_win, _area, _region = get_view3d_context()

print("\n=== STEP 6: Apply fit ===")
snapshot_after_fit = [v.co.copy() for v in cloth.data.vertices]
with bpy.context.temp_override(window=_win, area=_area, region=_region):
    result = bpy.ops.efit.preview_apply()
_assert_true(result == {'FINISHED'}, "preview_apply returned FINISHED")
_assert_true(not state._efit_cache, "cache cleared after apply")

# Positions should be stable (not zeroed or wildly different).
after_apply = [v.co.copy() for v in cloth.data.vertices]
stable = all((a - b).length < 0.05 for a, b in zip(snapshot_after_fit, after_apply))
_assert_true(stable, "vertex positions stable after apply")

print("\n=== STEP 7: Remove fit ===")
with bpy.context.temp_override(window=_win, area=_area, region=_region):
    result = bpy.ops.efit.remove()
_assert_true(result == {'FINISHED'}, "efit.remove returned FINISHED")

# Verify originals were restored (positions should differ from post-fit).
restored = [v.co.copy() for v in cloth.data.vertices]
changed = sum(1 for a, b in zip(snapshot_after_fit, restored) if (a - b).length > 1e-6)
_assert_true(changed > 0, f"at least one vertex restored to pre-fit position ({changed} changed)")

# ============================================================
# Exit
# ============================================================
print(f"\n=== FIT PIPELINE SUITE {'PASSED' if _failed == 0 else 'FAILED'} ({_failed} failure(s)) ===")
sys.exit(0 if _failed == 0 else 1)
