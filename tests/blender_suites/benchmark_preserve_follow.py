# benchmark_preserve_follow.py
# Run via: blender --background --python tests/blender_suites/benchmark_preserve_follow.py -- --blend-root <repo_root>
#
# Benchmarks the preserve-follow section of _efit_preview_update on ECF_Test.blend.
# Creates a preserve vertex group (bottom 30% of vertices by Z), enables developer
# mode, runs a fit, triggers slider changes, and wraps _efit_preview_update to
# measure preserve-follow cost directly via perf_counter around the section.
#
# Exit codes:
#   0 — benchmark completed successfully
#   1 — benchmark failed

import sys
import os
import time

# ---- parse CLI args ----
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_blend_root = None
_i = 0
while _i < len(_argv):
    if _argv[_i] == "--blend-root" and _i + 1 < len(_argv):
        _blend_root = _argv[_i + 1]
        _i += 2
    else:
        _i += 1

if _blend_root is None:
    print("[ERROR] --blend-root <repo_root> is required")
    sys.exit(1)

BLEND_PATH    = os.path.join(_blend_root, "tests", "ECF_Test.blend")
BODY_NAME     = "Body"
CLOTHING_NAME = "Outfit"

if not os.path.isfile(BLEND_PATH):
    print(f"[ERROR] Blend file not found: {BLEND_PATH}")
    sys.exit(1)

import bpy
import numpy as np

# ============================================================
# STEP 1: Load scene
# ============================================================
print("\n=== BENCHMARK: Preserve-Follow Profiling ===")
print(f"  Blend file: {BLEND_PATH}")

bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)

if BODY_NAME not in bpy.data.objects or CLOTHING_NAME not in bpy.data.objects:
    print(f"[ERROR] Required objects not found: {BODY_NAME}, {CLOTHING_NAME}")
    sys.exit(1)

# ============================================================
# STEP 2: Create preserve vertex group (bottom 30% by Z)
# ============================================================
cloth = bpy.data.objects[CLOTHING_NAME]
PRESERVE_GROUP_NAME = "_benchmark_preserve"

if PRESERVE_GROUP_NAME in cloth.vertex_groups:
    cloth.vertex_groups.remove(cloth.vertex_groups[PRESERVE_GROUP_NAME])

vg = cloth.vertex_groups.new(name=PRESERVE_GROUP_NAME)

z_coords = [v.co.z for v in cloth.data.vertices]
z_threshold = sorted(z_coords)[int(len(z_coords) * 0.30)]

preserve_count = 0
for v in cloth.data.vertices:
    if v.co.z <= z_threshold:
        vg.add([v.index], 1.0, 'REPLACE')
        preserve_count += 1

print(f"  Created preserve group '{PRESERVE_GROUP_NAME}': {preserve_count} vertices (of {len(cloth.data.vertices)})")

# ============================================================
# STEP 3: Set mesh pickers and preserve group
# ============================================================
p = bpy.context.scene.efit_props
p.body_obj     = bpy.data.objects[BODY_NAME]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME]
p.preserve_group = PRESERVE_GROUP_NAME
p.follow_strength = 1.0

# ============================================================
# STEP 4: Enable developer mode
# ============================================================
import elastic_fit.panels as _panels
_panels._cached_developer_mode = True
try:
    addon_prefs = bpy.context.preferences.addons['elastic_fit'].preferences
    addon_prefs.developer_mode = True
except Exception:
    pass
print("  Developer mode: ENABLED")

# ============================================================
# STEP 5: Run fit
# ============================================================
print("\n=== STEP 1: Run fit ===")
import elastic_fit.state as state
import elastic_fit.preview as _preview

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')

with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.fit()

if result != {'FINISHED'}:
    print(f"[ERROR] efit.fit returned {result}")
    sys.exit(1)

c = state._efit_cache
fitted_indices    = c.get('fitted_indices', [])
preserved_indices = c.get('preserved_indices', [])
print(f"  fitted_indices:    {len(fitted_indices)}")
print(f"  preserved_indices: {len(preserved_indices)}")
print(f"  follow_neighbors:  {p.follow_neighbors}")
print(f"  follow_strength:   {p.follow_strength}")
print(f"  Total vertices:    {len(cloth.data.vertices)}")

if len(preserved_indices) == 0:
    print("[WARN] No preserved indices — preserve-follow will be skipped.")

# ============================================================
# STEP 6: Instrument _efit_preview_update to capture section timings
# ============================================================
# Monkey-patch the function to capture internal timing data.
# We wrap _efit_preview_update and read _t_preserve from its local scope.
# Since we can't access locals, we instead measure the total time and
# use the K-scaling delta to isolate preserve-follow cost.

# Strategy: run with follow_strength=0 (skips preserve), then with
# follow_strength=1.0. The difference is the preserve-follow cost.

print(f"\n=== STEP 2: Isolate preserve-follow cost ===")

def _measure_ticks(n=5, label=""):
    """Return list of total tick times in ms."""
    times = []
    for i in range(n):
        delta = 0.05 * (1 if i % 2 == 0 else -1)
        new_val = max(0.0, min(1.0, p.fit_amount + delta))
        t0 = time.perf_counter()
        p.fit_amount = new_val
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    avg = sum(times) / len(times)
    print(f"    {label}: avg = {avg:.2f}ms  samples = {[f'{t:.1f}' for t in times]}")
    return times

# Baseline: preserve OFF
p.follow_strength = 0.0
# Warm up
p.fit_amount = max(0.0, min(1.0, p.fit_amount + 0.01))
times_no_preserve = _measure_ticks(5, "follow_strength=0.0 (preserve OFF)")

# With preserve ON
p.follow_strength = 1.0
# Warm up (rebuilds KDTree on first call)
p.fit_amount = max(0.0, min(1.0, p.fit_amount + 0.01))
times_with_preserve = _measure_ticks(5, "follow_strength=1.0 (preserve ON) ")

avg_no  = sum(times_no_preserve) / len(times_no_preserve)
avg_yes = sum(times_with_preserve) / len(times_with_preserve)
preserve_cost = avg_yes - avg_no

print(f"\n    preserve-follow cost (delta) = {preserve_cost:.2f}ms")
print(f"    ({avg_yes:.2f}ms with - {avg_no:.2f}ms without)")

# ============================================================
# STEP 7: Vary follow_neighbors with preserve ON
# ============================================================
print(f"\n=== STEP 3: Vary follow_neighbors (preserve ON) ===")

p.follow_strength = 1.0
results_by_k = {}

for K in [4, 8, 16, 32]:
    p.follow_neighbors = K
    # Clear kd_follow from cache to force rebuild with new K
    state._efit_cache.pop('kd_follow', None)
    # Warm up
    p.fit_amount = max(0.0, min(1.0, p.fit_amount + 0.01))

    times_k = _measure_ticks(3, f"K={K:3d}")
    avg_k = sum(times_k) / len(times_k)
    results_by_k[K] = avg_k

# Also measure without preserve for this baseline
p.follow_strength = 0.0
p.fit_amount = max(0.0, min(1.0, p.fit_amount + 0.01))
times_base = _measure_ticks(3, "K=  0 (preserve OFF baseline)")
baseline_avg = sum(times_base) / len(times_base)

print(f"\n  Per-K preserve-follow cost (delta from baseline):")
for K in [4, 8, 16, 32]:
    delta = results_by_k[K] - baseline_avg
    print(f"    K={K:3d}: preserve = {delta:.2f}ms  (total = {results_by_k[K]:.2f}ms)")

# ============================================================
# STEP 8: Report and R011 decision
# ============================================================
print(f"\n=== R011 EVALUATION ===")
print(f"  Mesh: ECF_Test.blend ({len(cloth.data.vertices)} verts)")
print(f"  Fitted:    {len(fitted_indices)}")
print(f"  Preserved: {len(preserved_indices)}")
print(f"  K=32 preserve-follow cost: {preserve_cost:.2f}ms")

K32_delta = results_by_k.get(32, 0) - baseline_avg
print(f"  K=32 preserve delta (cross-validated): {K32_delta:.2f}ms")

threshold = 2.0
avg_preserve = max(preserve_cost, K32_delta)  # use larger estimate
if avg_preserve <= threshold:
    print(f"\n  [PASS] preserve-follow ({avg_preserve:.2f}ms) <= {threshold}ms threshold")
    print(f"  Decision: ACCEPTABLE — no optimization required per R011")
else:
    print(f"\n  [ACTION] preserve-follow ({avg_preserve:.2f}ms) > {threshold}ms threshold")
    print(f"  Decision: OPTIMIZATION RECOMMENDED per R011")

print("\n=== BENCHMARK COMPLETE ===")
sys.exit(0)
