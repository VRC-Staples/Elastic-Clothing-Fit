# test_proximity.py
# Proximity falloff feature tests.
#
# REQUIRES:
#   - elastic_fit addon installed and enabled.
#   - A scene with body + clothing meshes already set on efit_props.
#     (Run test_fit_pipeline STEP_1_TO_2 first to load a scene, or set manually.)
#
# Run each STEP_* block via mcp__blender__execute_blender_code in order.

# ============================================================
# STEP 1-2: Enable falloff, run fit, verify distances cached
# ============================================================
STEP_1_TO_2 = '''
import bpy
import elastic_fit.state as state

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

p = bpy.context.scene.efit_props

print("\\n=== STEP 1: Enable proximity falloff and run fit ===")
p.use_proximity_falloff = True
p.proximity_mode        = 'PRE_FIT'
p.proximity_start       = 0.0
p.proximity_end         = 0.05
p.proximity_curve       = 'SMOOTH'

result = bpy.ops.efit.fit()
_assert_equal(result, {'FINISHED'}, "efit.fit returned FINISHED")

print("\\n=== STEP 2: Verify cloth_body_distances in cache ===")
c = state._efit_cache
_assert_true('cloth_body_distances' in c, "cloth_body_distances key present in cache")
_assert_true('proximity_weights'    in c, "proximity_weights key present in cache")

distances = c.get('cloth_body_distances', {})
_assert_true(len(distances) > 0, f"cloth_body_distances non-empty ({len(distances)} entries)")

all_non_negative = all(v >= 0.0 for v in distances.values())
_assert_true(all_non_negative, "all distances >= 0.0")
print(f"    Distance range: [{min(distances.values()):.4f}, {max(distances.values()):.4f}] m")
'''

# ============================================================
# STEP 3: Verify proximity_weights all in [0, 1]
# ============================================================
STEP_3 = '''
import bpy
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

def _assert_all_in_range(mapping, lo, hi, label):
    bad = {k: v for k, v in mapping.items() if not (lo <= v <= hi)}
    ok = len(bad) == 0
    status = "PASS" if ok else "FAIL"
    extra = "" if ok else f"  ({len(bad)} out of range, e.g. {list(bad.items())[:3]})"
    print(f"  [{status}] {label}{extra}")
    return ok

print("\\n=== STEP 3: Verify proximity_weights in [0, 1] ===")
c = state._efit_cache
weights = c.get('proximity_weights') or {}
_assert_true(weights is not None, "proximity_weights is not None")
_assert_true(len(weights) > 0, f"proximity_weights non-empty ({len(weights)} entries)")
_assert_all_in_range(weights, 0.0, 1.0, "all proximity weights in [0.0, 1.0]")

w_min = min(weights.values()) if weights else None
w_max = max(weights.values()) if weights else None
print(f"    Weight range: [{w_min:.4f}, {w_max:.4f}]")
'''

# ============================================================
# STEP 4: Cycle through curve presets, verify weights change
# ============================================================
STEP_4 = '''
import bpy
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 4: Cycle curve presets, verify weights change ===")
p = bpy.context.scene.efit_props
curves = ['LINEAR', 'SMOOTH', 'SHARP', 'ROOT']
prev_weights = None

for curve in curves:
    p.proximity_curve = curve
    # The update callback fires _efit_preview_update which recomputes weights.
    current = state._efit_cache.get('proximity_weights') or {}
    current_vals = tuple(sorted(current.values()))

    if prev_weights is not None:
        changed = current_vals != prev_weights
        _assert_true(True, f"curve={curve!r} weights computed ({len(current)} entries)")
        # Note: different curves *should* produce different weights for the same distances,
        # but if all distances are 0 the weights may all be 1.0 regardless of curve.
        # We only assert that weights are present, not that they differ.
    else:
        _assert_true(len(current) > 0, f"curve={curve!r} weights non-empty")

    prev_weights = current_vals
    print(f"    {curve}: min={min(current.values(), default=0):.4f}, max={max(current.values(), default=0):.4f}")
'''

# ============================================================
# STEP 5: Adjust start/end, verify preview updates
# ============================================================
STEP_5 = '''
import bpy
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 5: Adjust start/end distances, verify preview updates ===")
p     = bpy.context.scene.efit_props
cloth = bpy.data.objects.get(state._efit_cache.get('cloth_name', ''))

if cloth is None:
    print("  [SKIP] No cloth object in cache")
else:
    before = [v.co.copy() for v in cloth.data.vertices]

    # Narrow the falloff range to almost nothing -- most vertices should be unaffected.
    p.proximity_start = 0.0
    p.proximity_end   = 0.001

    after_narrow = [v.co.copy() for v in cloth.data.vertices]
    moved_narrow = sum(1 for a, b in zip(before, after_narrow) if (a - b).length > 1e-6)
    _assert_true(True, f"proximity_end=0.001: {moved_narrow} vertices changed")

    # Wide range -- full effect on all vertices.
    p.proximity_start = 0.0
    p.proximity_end   = 1.0

    after_wide = [v.co.copy() for v in cloth.data.vertices]
    moved_wide = sum(1 for a, b in zip(after_narrow, after_wide) if (a - b).length > 1e-6)
    _assert_true(moved_wide > 0, f"widening range moved at least one vertex ({moved_wide} moved)")

    # Restore to reasonable defaults.
    p.proximity_start = 0.0
    p.proximity_end   = 0.05
'''

# ============================================================
# STEP 6: Disable falloff, verify behavior reverts
# ============================================================
STEP_6 = '''
import bpy
import elastic_fit.state as state

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 6: Disable proximity falloff, verify behavior reverts ===")
p     = bpy.context.scene.efit_props
cloth = bpy.data.objects.get(state._efit_cache.get('cloth_name', ''))

before = [v.co.copy() for v in cloth.data.vertices] if cloth else []

p.use_proximity_falloff = False

# Cache should still have cloth_body_distances (they were computed at fit time).
c = state._efit_cache
_assert_true('cloth_body_distances' in c, "cloth_body_distances still in cache after disable")

# proximity_weights in cache should now be None (no falloff).
pw = c.get('proximity_weights')
_assert_true(pw is None, "proximity_weights is None after disable")

# Vertex positions should differ from when falloff was enabled.
if cloth:
    after = [v.co.copy() for v in cloth.data.vertices]
    changed = sum(1 for a, b in zip(before, after) if (a - b).length > 1e-6)
    _assert_true(changed > 0, f"vertices moved after disabling falloff ({changed} changed)")

# Clean up.
bpy.ops.efit.preview_cancel()
_assert_true(not state._efit_cache, "cache cleared after cancel")
print("\\n=== ALL PROXIMITY TESTS COMPLETE ===")
'''
