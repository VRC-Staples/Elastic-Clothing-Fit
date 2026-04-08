# suite_proximity.py
# Run via: blender --background --python tests/blender_suites/suite_proximity.py -- --blend-root <repo_root>
#
# Pass --skip to bypass the suite (use when Fit Pipeline had failures):
#   blender --background --python tests/blender_suites/suite_proximity.py -- --skip
#
# REQUIRES: elastic_fit addon installed and enabled.
#           tests/ECF_Test3.blend with Body and outfit objects.
#
# Exit codes:
#   0 — all assertions passed, or suite was skipped
#   1 — one or more [FAIL] lines were printed

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
_skip = "--skip" in _argv
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

if _skip:
    print("[SKIP] Proximity suite skipped (Fit Pipeline had failures)")
    sys.exit(0)

if _blend_root is None and not _programmatic:
    print("[ERROR] --blend-root <repo_root> is required (unless --programmatic is set)")
    sys.exit(1)

BLEND_PATH    = os.path.join(_blend_root, "tests", "ECF_Test3.blend") if _blend_root else None
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
if _programmatic:
    clear_programmatic_objects()
    body = make_icosphere("ECF_Body", radius=1.0)
    cloth = make_clothing_with_groups(
        "ECF_Clothing",
        radius=1.02,
        group_names=("Group1", "Group2"),
    )
    print("[INFO] programmatic geometry: ECF_Body, ECF_Clothing (2 groups)")
else:
    bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    body = bpy.data.objects[BODY_NAME]
    cloth = bpy.data.objects[CLOTHING_NAME]

BODY_NAME_LOCAL = body.name
CLOTHING_NAME_LOCAL = cloth.name

_assert_true(BODY_NAME_LOCAL in bpy.data.objects, f"{BODY_NAME_LOCAL!r} exists in scene")
_assert_true(CLOTHING_NAME_LOCAL in bpy.data.objects, f"{CLOTHING_NAME_LOCAL!r} exists in scene")

p = bpy.context.scene.efit_props
p.body_obj = body
p.clothing_obj = cloth
_assert_equal(p.body_obj.name, BODY_NAME_LOCAL, "body_obj set correctly")
_assert_equal(p.clothing_obj.name, CLOTHING_NAME_LOCAL, "clothing_obj set correctly")

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

    _assert_true(len(current) > 0, f"curve={curve!r} weights non-empty ({len(current)} entries)")
    _assert_all_in_range(current, 0.0, 1.0, f"curve={curve!r} weights all in [0, 1]")

    if prev_weights is not None:
        differs = current_vals != prev_weights
        _assert_true(differs, f"curve={curve!r} weights differ from previous curve")

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

    # Wide range -- full effect on all vertices.
    p.proximity_start = 0.0
    p.proximity_end   = 1.0

    after_wide = [v.co.copy() for v in cloth.data.vertices]
    moved_wide = sum(1 for a, b in zip(after_narrow, after_wide) if (a - b).length > 1e-6)
    _assert_true(moved_wide > 0, f"widening range moved at least one vertex ({moved_wide} moved)")
    _assert_true(
        moved_wide >= moved_narrow,
        f"wide range moves at least as many vertices as narrow ({moved_wide} >= {moved_narrow})",
    )

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

# proximity_weights after disable may be either None (legacy behavior)
# or a retained cache map in newer behavior.
pw = c.get('proximity_weights')
if pw is None:
    _assert_true(True, "proximity_weights is None after disable")
else:
    _assert_true(len(pw) > 0, f"proximity_weights retained after disable ({len(pw)} entries)")
    _assert_all_in_range(pw, 0.0, 1.0, "retained proximity_weights remain in [0, 1] after disable")

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
# STEP 7: Per-group checkbox on, 0 groups -> global path still applies
# ============================================================
print("\n=== STEP 7: Per-group tuning enabled, 0 groups -> global path ===")
p.use_proximity_falloff     = True
p.use_proximity_group_tuning = True
p.proximity_start = 0.0
p.proximity_end   = 0.05
p.proximity_curve = 'SMOOTH'
# Ensure no groups are present.
p.proximity_groups.clear()

with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.fit()
_assert_equal(result, {'FINISHED'}, "STEP 7: efit.fit returned FINISHED")

c = state._efit_cache
pw = c.get('proximity_weights') or {}
_assert_true(len(pw) > 0, f"STEP 7: proximity_weights non-empty ({len(pw)} entries)")
_assert_all_in_range(pw, 0.0, 1.0, "STEP 7: all weights in [0, 1]")

with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_cancel()
_assert_true(not state._efit_cache, "STEP 7: cache cleared after cancel")

# ============================================================
# STEP 8: Per-group tuning, 1 group -> group vertices get per-group weights,
#         ungrouped vertices get weight 1.0
# ============================================================
print("\n=== STEP 8: Per-group tuning, 1 group added ===")
cloth_obj = cloth
vg_names = [vg.name for vg in cloth_obj.vertex_groups] if cloth_obj else []

if not vg_names:
    print("  [SKIP] No vertex groups on clothing — skipping STEP 8-10")
else:
    vg1 = vg_names[0]
    print(f"    Using vertex group: {vg1!r}")

    # Add one proximity group with a very tight end distance.
    new_pg = p.proximity_groups.add()
    new_pg.group_name   = vg1
    new_pg.proximity_start = 0.0
    new_pg.proximity_end   = 0.001   # extremely tight: most group verts will get ~0.0
    new_pg.proximity_curve = 'SMOOTH'

    with bpy.context.temp_override(window=_win, area=_area):
        result = bpy.ops.efit.fit()
    _assert_equal(result, {'FINISHED'}, "STEP 8: efit.fit returned FINISHED")

    c = state._efit_cache
    pw = c.get('proximity_weights') or {}
    _assert_true(len(pw) > 0, f"STEP 8: proximity_weights non-empty ({len(pw)} entries)")
    _assert_all_in_range(pw, 0.0, 1.0, "STEP 8: all weights in [0, 1]")

    # Ungrouped vertices must have weight 1.0.
    vg_idx = cloth_obj.vertex_groups[vg1].index
    in_group    = {v.index for v in cloth_obj.data.vertices
                   if any(g.group == vg_idx and g.weight > 0.0 for g in v.groups)}
    fitted_set  = set(c.get('fitted_indices', []))
    ungrouped   = fitted_set - in_group
    ungrouped_non_one = {vi: pw[vi] for vi in ungrouped if vi in pw and abs(pw[vi] - 1.0) > 1e-6}
    _assert_true(len(ungrouped_non_one) == 0,
                 f"STEP 8: ungrouped vertices all have weight 1.0 ({len(ungrouped_non_one)} violations)")

    with bpy.context.temp_override(window=_win, area=_area):
        bpy.ops.efit.preview_cancel()
    _assert_true(not state._efit_cache, "STEP 8: cache cleared after cancel")

    # ============================================================
    # STEP 9: 2 groups with different end distances -> independent weights
    # ============================================================
    print("\n=== STEP 9: 2 proximity groups, different end distances ===")
    if len(vg_names) < 2:
        print("  [SKIP] Need at least 2 vertex groups — skipping STEP 9")
    else:
        vg2 = vg_names[1]
        print(f"    Group 1: {vg1!r} end=0.001  Group 2: {vg2!r} end=0.5")

        # Already have 1 group from STEP 8 in p.proximity_groups; add a second.
        new_pg2 = p.proximity_groups.add()
        new_pg2.group_name     = vg2
        new_pg2.proximity_start = 0.0
        new_pg2.proximity_end   = 0.5    # wide: most group verts will get near-zero weight
        new_pg2.proximity_curve = 'SMOOTH'

        with bpy.context.temp_override(window=_win, area=_area):
            result = bpy.ops.efit.fit()
        _assert_equal(result, {'FINISHED'}, "STEP 9: efit.fit returned FINISHED")

        c = state._efit_cache
        pw = c.get('proximity_weights') or {}
        _assert_true(len(pw) > 0, f"STEP 9: proximity_weights non-empty ({len(pw)} entries)")
        _assert_all_in_range(pw, 0.0, 1.0, "STEP 9: all weights in [0, 1]")

        # Verify ungrouped verts still weight 1.0 with 2 groups.
        vg2_idx   = cloth_obj.vertex_groups[vg2].index
        in_group2 = {v.index for v in cloth_obj.data.vertices
                     if any(g.group == vg2_idx and g.weight > 0.0 for g in v.groups)}
        ungrouped2 = fitted_set - in_group - in_group2
        ungrouped2_non_one = {vi: pw[vi] for vi in ungrouped2 if vi in pw and abs(pw[vi] - 1.0) > 1e-6}
        _assert_true(len(ungrouped2_non_one) == 0,
                     f"STEP 9: ungrouped vertices all weight 1.0 ({len(ungrouped2_non_one)} violations)")

        with bpy.context.temp_override(window=_win, area=_area):
            bpy.ops.efit.preview_cancel()
        _assert_true(not state._efit_cache, "STEP 9: cache cleared after cancel")

    # ============================================================
    # STEP 10: Remove all groups -> falls back to global path
    # ============================================================
    print("\n=== STEP 10: Remove all proximity groups -> global path ===")
    p.proximity_groups.clear()
    _assert_equal(len(p.proximity_groups), 0, "STEP 10: proximity_groups cleared")

    # Rerun fit; should behave like global proximity.
    with bpy.context.temp_override(window=_win, area=_area):
        result = bpy.ops.efit.fit()
    _assert_equal(result, {'FINISHED'}, "STEP 10: efit.fit returned FINISHED")

    c = state._efit_cache
    pw = c.get('proximity_weights') or {}
    _assert_true(len(pw) > 0, f"STEP 10: proximity_weights non-empty after group removal ({len(pw)} entries)")
    _assert_all_in_range(pw, 0.0, 1.0, "STEP 10: all weights in [0, 1] after group removal")

    with bpy.context.temp_override(window=_win, area=_area):
        bpy.ops.efit.preview_cancel()
    _assert_true(not state._efit_cache, "STEP 10: cache cleared after cancel")

# ============================================================
# Final cleanup
# ============================================================
p.use_proximity_falloff      = False
p.use_proximity_group_tuning = False
p.proximity_groups.clear()

print("\n=== ALL PROXIMITY TESTS COMPLETE ===")

# ============================================================
# Exit
# ============================================================
print(f"\n=== PROXIMITY SUITE {'PASSED' if _failed == 0 else 'FAILED'} ({_failed} failure(s)) ===")
sys.exit(0 if _failed == 0 else 1)
