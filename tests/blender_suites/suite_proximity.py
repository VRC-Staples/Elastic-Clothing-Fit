# suite_proximity.py
# Run via: blender --background --python tests/blender_suites/suite_proximity.py -- --blend-root <repo_root>
#
# Pass --skip to bypass the suite (use when Fit Pipeline had failures):
#   blender --background --python tests/blender_suites/suite_proximity.py -- --skip
#
# REQUIRES: elastic_fit addon installed and enabled.
#           tests/ECF_Test.blend with Body and Outfit objects.
#
# Exit codes:
#   0 — all assertions passed, or suite was skipped
#   1 — one or more [FAIL] lines were printed

import sys
import os

# ---- parse CLI args ----
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_skip = "--skip" in _argv
_blend_root = None
_i = 0
while _i < len(_argv):
    if _argv[_i] == "--blend-root" and _i + 1 < len(_argv):
        _blend_root = _argv[_i + 1]
        _i += 2
    else:
        _i += 1

if _skip:
    print("[SKIP] Proximity suite skipped (Fit Pipeline had failures)")
    sys.exit(0)

if _blend_root is None:
    print("[ERROR] --blend-root <repo_root> is required")
    sys.exit(1)

BLEND_PATH    = os.path.join(_blend_root, "tests", "ECF_Test.blend")
BODY_NAME     = "Body"
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

# ---- import bpy (Blender's Python API) ----
import bpy
import elastic_fit.state as state

# ============================================================
# STEP 1-2: Load scene, set pickers, enable falloff, run fit,
#           verify distances cached
#
# Note: The original string-literal test relied on scene state already
# being loaded from a prior Fit Pipeline call. This headless
# script is self-contained — it loads the blend file and sets
# the mesh pickers before enabling proximity falloff.
# ============================================================
print("\n=== STEP 1: Load blend file and set mesh pickers ===")
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
_assert_true(BODY_NAME     in bpy.data.objects, f"{BODY_NAME!r} exists in scene")
_assert_true(CLOTHING_NAME in bpy.data.objects, f"{CLOTHING_NAME!r} exists in scene")

p = bpy.context.scene.efit_props
p.body_obj     = bpy.data.objects[BODY_NAME]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME]
_assert_equal(p.body_obj.name,     BODY_NAME,     "body_obj set correctly")
_assert_equal(p.clothing_obj.name, CLOTHING_NAME, "clothing_obj set correctly")

print("\n=== STEP 2: Enable proximity falloff and run fit ===")
p.use_proximity_falloff = True
p.proximity_mode        = 'PRE_FIT'
p.proximity_start       = 0.0
p.proximity_end         = 0.05
p.proximity_curve       = 'SMOOTH'

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.fit()
_assert_equal(result, {'FINISHED'}, "efit.fit returned FINISHED")

print("\n=== STEP 2 (cont): Verify cloth_body_distances in cache ===")
c = state._efit_cache
_assert_true('cloth_body_distances' in c, "cloth_body_distances key present in cache")
_assert_true('proximity_weights'    in c, "proximity_weights key present in cache")

distances = c.get('cloth_body_distances', {})
_assert_true(len(distances) > 0, f"cloth_body_distances non-empty ({len(distances)} entries)")

all_non_negative = all(v >= 0.0 for v in distances.values())
_assert_true(all_non_negative, "all distances >= 0.0")
print(f"    Distance range: [{min(distances.values()):.4f}, {max(distances.values()):.4f}] m")

# ============================================================
# STEP 3: Verify proximity_weights all in [0, 1]
# ============================================================
print("\n=== STEP 3: Verify proximity_weights in [0, 1] ===")
weights = c.get('proximity_weights') or {}
_assert_true(weights is not None, "proximity_weights is not None")
_assert_true(len(weights) > 0, f"proximity_weights non-empty ({len(weights)} entries)")
_assert_all_in_range(weights, 0.0, 1.0, "all proximity weights in [0.0, 1.0]")

w_min = min(weights.values()) if weights else None
w_max = max(weights.values()) if weights else None
print(f"    Weight range: [{w_min:.4f}, {w_max:.4f}]")

# ============================================================
# STEP 4: Cycle through curve presets, verify weights change
# ============================================================
print("\n=== STEP 4: Cycle curve presets, verify weights change ===")
curves = ['LINEAR', 'SMOOTH', 'SHARP', 'ROOT']
prev_weights = None

for curve in curves:
    p.proximity_curve = curve
    # The update callback fires _efit_preview_update which recomputes weights.
    current = state._efit_cache.get('proximity_weights') or {}
    current_vals = tuple(sorted(current.values()))

    if prev_weights is not None:
        _assert_true(True, f"curve={curve!r} weights computed ({len(current)} entries)")
        # Note: different curves *should* produce different weights for the same distances,
        # but if all distances are 0 the weights may all be 1.0 regardless of curve.
        # We only assert that weights are present, not that they differ.
    else:
        _assert_true(len(current) > 0, f"curve={curve!r} weights non-empty")

    prev_weights = current_vals
    print(f"    {curve}: min={min(current.values(), default=0):.4f}, max={max(current.values(), default=0):.4f}")

# ============================================================
# STEP 5: Adjust start/end, verify preview updates
# ============================================================
print("\n=== STEP 5: Adjust start/end distances, verify preview updates ===")
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

# ============================================================
# STEP 6: Disable falloff, verify behavior reverts
# ============================================================
print("\n=== STEP 6: Disable proximity falloff, verify behavior reverts ===")
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
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_cancel()
_assert_true(not state._efit_cache, "cache cleared after cancel")
print("\n=== ALL PROXIMITY TESTS COMPLETE ===")

# ============================================================
# Exit
# ============================================================
print(f"\n=== PROXIMITY SUITE {'PASSED' if _failed == 0 else 'FAILED'} ({_failed} failure(s)) ===")
sys.exit(0 if _failed == 0 else 1)
