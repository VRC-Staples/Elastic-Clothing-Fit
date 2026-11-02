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

import numpy as np

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
prepared = state._efit_cache['prepared']
_assert_true(np.isfinite(prepared.originals).all(), "original coordinates are finite")
_assert_true(np.isfinite(prepared.displacements).all(), "fitted displacements are finite")
_assert_true(prepared.body_distances.shape == (len(prepared.fitted_indices),)
             and np.isfinite(prepared.body_distances).all(),
             "body distances have one finite value per fitted row")
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

fitted_indices = state._efit_cache['prepared'].fitted_indices
body_normals   = state._efit_cache['prepared'].body_normals

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

print("\n=== STEP 8: Exclusive fitting keeps unselected vertices fixed ===")
p.fit_mode = 'EXCLUSIVE'
p.exclusive_groups.clear()
exclusive_group = cloth.vertex_groups.new(name='ECF_ExclusiveRegression')
selected = [vertex.index for vertex in cloth.data.vertices if vertex.index % 2 == 0]
frozen = [vertex.index for vertex in cloth.data.vertices if vertex.index % 2 != 0]
exclusive_group.add(selected, 1., 'REPLACE')
entry = p.exclusive_groups.add()
entry.group_name = exclusive_group.name
p.fit_amount = 0.67
p.follow_strength = 1.
p.follow_neighbors = 2
p.use_proximity_falloff = False
original = np.array([vertex.co[:] for vertex in cloth.data.vertices])
with bpy.context.temp_override(window=_win, area=_area, region=_region):
    result = bpy.ops.efit.fit()
_assert_equal(result, {'FINISHED'}, "exclusive fit returned FINISHED")
initial = np.array([vertex.co[:] for vertex in cloth.data.vertices])
_assert_true(np.array_equal(initial[frozen], original[frozen]),
             "exclusive initial fit keeps frozen coordinates exact with follow enabled")
_assert_true(np.any(initial[selected] != original[selected]), "exclusive fit moves selected vertices")
p.fit_amount = 0.72
preview_coordinates = np.array([vertex.co[:] for vertex in cloth.data.vertices])
_assert_true(np.array_equal(preview_coordinates[frozen], original[frozen]),
             "exclusive preview keeps frozen coordinates exact with follow enabled")
p.fit_amount = 0.67
roundtrip = np.array([vertex.co[:] for vertex in cloth.data.vertices])
_assert_true(np.array_equal(roundtrip[frozen], original[frozen]),
             "exclusive slider round trip keeps frozen coordinates exact")
with bpy.context.temp_override(window=_win, area=_area, region=_region):
    result = bpy.ops.efit.preview_cancel()
_assert_equal(result, {'FINISHED'}, "exclusive cancel returned FINISHED")
_assert_true(not state._efit_cache, "exclusive cancel clears the session")
restored = np.array([vertex.co[:] for vertex in cloth.data.vertices])
_assert_true(np.array_equal(restored, original), "exclusive cancel restores all original coordinates exactly")

from types import SimpleNamespace
from elastic_fit import deps, preview
from elastic_fit.deformation import PreparedFit


def _check_native_preserve_follow(backend_name, batch_tree):
    original = np.array([[2., 0., 0.], [10., 20., 30.], [1., 0., 0.],
                         [0., 0., 0.], [30., 40., 50.]])
    prepared = PreparedFit(
        original, np.array([[0., 0., 2.], [0., 0., 4.]]), [3, 0],
        np.empty((0, 2), dtype=np.int32), np.array([[0., 1., 0.], [0., 1., 0.]]),
        preserved_indices=[2], original_offset=0.25,
        offset_group_weights={'A': {3: 1., 0: 1.}})
    settings = SimpleNamespace(
        fit_amount=1., offset=0.25, disp_smooth_passes=0,
        follow_neighbors=2, follow_strength=0.5, fit_mode='FULL',
        offset_groups=[SimpleNamespace(group_name='A', influence=200.)])
    coordinates = prepared.evaluate(settings, batch_tree=batch_tree)
    _assert_true(np.array_equal(coordinates[[3, 0]], [[0., 0.25, 2.], [2., 0.25, 4.]]),
                 f"{backend_name}: fitted vertices receive displacement and group offset")
    _assert_true(np.array_equal(coordinates[2], [1., 0., 1.5]),
                 f"{backend_name}: preserved follows sparse neighbors but not group offsets (got {coordinates[2].tolist()})")
    _assert_true(np.array_equal(coordinates[[1, 4]], original[[1, 4]]),
                 f"{backend_name}: unrelated vertices stay exact")

    # Below half the float32 spacing at x=32, initial rounding erases each delta.
    epsilon = 3 * 2. ** -21
    original = np.array([[32., 1., 0.], [32., -1., 0.], [0., 0., 0.]])
    previous_cache = state._efit_cache
    previous_error = state._efit_last_error
    previous_backend_available = deps.PYKDTREE_AVAILABLE
    mesh = bpy.data.meshes.new('ECF_FollowPrecision')
    mesh.from_pydata(original.tolist(), [], [])
    precision_cloth = bpy.data.objects.new('ECF_FollowPrecision', mesh)
    bpy.context.collection.objects.link(precision_cloth)
    try:
        deps.PYKDTREE_AVAILABLE = batch_tree is not None
        for group_offsets in (False, True):
            groups = [SimpleNamespace(group_name='A', influence=200.)] if group_offsets else []
            settings = SimpleNamespace(
                fit_amount=1., offset=epsilon, disp_smooth_passes=0,
                follow_neighbors=2, follow_strength=1., fit_mode='FULL',
                offset_groups=groups, use_proximity_falloff=False)
            prepared = PreparedFit(
                original, np.array([[epsilon, 0., 0.], [epsilon, 0., 0.]]), [0, 1],
                np.empty((0, 2), dtype=np.int32), np.array([[1., 0., 0.], [1., 0., 0.]]),
                preserved_indices=[2], original_offset=epsilon,
                offset_group_weights={'A': {0: 1., 1: 1.}} if group_offsets else {})
            initial = prepared.evaluate(settings, batch_tree=batch_tree, initial_fit=True)
            mesh.vertices.foreach_set('co', initial.ravel())
            mesh.update()
            observed = np.array([vertex.co[:] for vertex in mesh.vertices])
            label = f"{backend_name}, group offsets={group_offsets}"
            _assert_true(np.array_equal(observed, original),
                         f"{label}: initial follow keeps rounded-away movement zero (preserved {observed[2].tolist()})")
            state._efit_cache = {'cloth_name': precision_cloth.name, 'prepared': prepared}
            state._efit_last_error = ''
            preview._efit_preview_update(SimpleNamespace(
                scene=SimpleNamespace(efit_props=settings), screen=None))
            _assert_true(not state._efit_last_error,
                         f"{label}: preview completes without error ({state._efit_last_error})")
            observed = np.array([vertex.co[:] for vertex in mesh.vertices])
            _assert_true(np.allclose(observed[2], [epsilon, 0., 0.], rtol=2e-7, atol=0.),
                         f"{label}: preview follow retains its small displacement (preserved {observed[2].tolist()})")
            expected_x = 32. + 2. ** -18 if group_offsets else 32.
            _assert_true(np.array_equal(observed[:2, 0], [expected_x, expected_x]),
                         f"{label}: fitted preview coordinates retain the group-offset mesh boundary")
    finally:
        state._efit_cache = previous_cache
        state._efit_last_error = previous_error
        deps.PYKDTREE_AVAILABLE = previous_backend_available
        bpy.data.objects.remove(precision_cloth, do_unlink=True)
        bpy.data.meshes.remove(mesh)


print("\n=== Native preserve-follow contracts ===")
_check_native_preserve_follow('mathutils', None)
if deps.PYKDTREE_AVAILABLE:
    _check_native_preserve_follow('pykdtree', deps.BatchKDTree)
else:
    print('[SKIP] Native preserve-follow batch checks: pykdtree is unavailable')

# ============================================================
# Exit
# ============================================================
print(f"\n=== FIT PIPELINE SUITE {'PASSED' if _failed == 0 else 'FAILED'} ({_failed} failure(s)) ===")
sys.exit(0 if _failed == 0 else 1)
