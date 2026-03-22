# benchmark_final_timing.py
# Run via: blender --background --python tests/blender_suites/benchmark_final_timing.py -- --blend-root <repo_root>
#
# Integrated per-section timing benchmark for elastic_fit preview hot-path on ECF_Test.blend.
# Reads preview._last_tick_timings (populated by T01/S05 infrastructure) to collect real
# per-section wall-clock data, not just total tick time.
#
# Measures with preserve OFF (follow_strength=0.0) then preserve ON (follow_strength=1.0,
# follow_neighbors=32) and emits [TIMING]-tagged machine-readable output at the end.
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

# ============================================================
# STEP 1: Load scene
# ============================================================
print("\n=== BENCHMARK: Final Integrated Timing ===")
print(f"  Blend file: {BLEND_PATH}")

bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)

if BODY_NAME not in bpy.data.objects or CLOTHING_NAME not in bpy.data.objects:
    print(f"[ERROR] Required objects not found: {BODY_NAME}, {CLOTHING_NAME}")
    sys.exit(1)

cloth = bpy.data.objects[CLOTHING_NAME]
print(f"  Clothing object: '{CLOTHING_NAME}' ({len(cloth.data.vertices)} vertices)")
print(f"  Body object:     '{BODY_NAME}'")

# ============================================================
# STEP 2: Set mesh pickers
# ============================================================
p = bpy.context.scene.efit_props
p.body_obj     = bpy.data.objects[BODY_NAME]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME]

# ============================================================
# STEP 3: Enable developer mode (required for _last_tick_timings)
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
# STEP 4: Run fit to populate cache
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
fitted_indices = c.get('fitted_indices', [])
print(f"  fitted_indices: {len(fitted_indices)}")
print(f"  Total vertices: {len(cloth.data.vertices)}")

# ============================================================
# STEP 5: Define tick measurement helper
# ============================================================
# Reads preview._last_tick_timings after each tick, which is populated inside
# the existing `if _dev_mode:` block in preview.py (T01/S05 infrastructure).
# Falls back to perf_counter total if _last_tick_timings is None (dev mode off).

def _measure_ticks(n, label):
    """
    Toggle fit_amount slightly n times and collect per-section timings
    from preview._last_tick_timings after each tick.

    Returns a list of timing dicts. Each dict has keys:
        adj, smooth, prox, cobuf, offgrp, preserve, fset, total  (seconds as floats)

    Failure visibility:
      If _preview._last_tick_timings is None after the first tick, developer mode
      was not enabled or preview.py does not have the capture point. The benchmark
      will fall back to perf_counter wall-clock and emit a warning.
    """
    results = []
    for i in range(n):
        delta = 0.05 * (1 if i % 2 == 0 else -1)
        new_val = max(0.0, min(1.0, p.fit_amount + delta))
        t0 = time.perf_counter()
        p.fit_amount = new_val
        wall_ms = (time.perf_counter() - t0) * 1000.0

        if _preview._last_tick_timings is not None:
            # Deep copy so next tick does not overwrite the dict in-place
            row = dict(_preview._last_tick_timings)
        else:
            # Fallback — only total wall time available
            row = {k: 0.0 for k in ('adj', 'smooth', 'prox', 'cobuf', 'offgrp', 'preserve', 'fset')}
            row['total'] = wall_ms / 1000.0
        results.append(row)

    avg_total_ms = sum(r['total'] for r in results) / len(results) * 1000.0
    print(f"    {label}: avg TOTAL = {avg_total_ms:.2f}ms over {n} ticks")
    return results

# ============================================================
# STEP 6: Measure with preserve OFF
# ============================================================
print("\n=== STEP 2: Measure with preserve OFF (follow_strength=0.0) ===")
p.follow_strength = 0.0
# Warm up
p.fit_amount = max(0.0, min(1.0, p.fit_amount + 0.01))

_results_no_preserve = _measure_ticks(5, "follow_strength=0.0 (preserve OFF)")

if _preview._last_tick_timings is None:
    print("[WARN] _last_tick_timings is None — developer mode capture point may not be active")
    print("[WARN] Falling back to perf_counter wall time only; per-section data unavailable")

# ============================================================
# STEP 7: Measure with preserve ON (K=32)
# ============================================================
print("\n=== STEP 3: Measure with preserve ON (follow_strength=1.0, K=32) ===")
p.follow_strength  = 1.0
p.follow_neighbors = 32
# Clear KDTree cache so it rebuilds with the correct K
state._efit_cache.pop('kd_follow', None)
# Warm up (rebuilds KDTree on first call)
p.fit_amount = max(0.0, min(1.0, p.fit_amount + 0.01))

_results_with_preserve = _measure_ticks(5, "follow_strength=1.0, K=32 (preserve ON)")

# ============================================================
# STEP 8: Compute averages
# ============================================================
SECTIONS = ('adj', 'smooth', 'prox', 'cobuf', 'offgrp', 'preserve', 'fset', 'total')

def _avg_section(results, key):
    return sum(r[key] for r in results) / len(results) * 1000.0  # → ms

avgs_no  = {k: _avg_section(_results_no_preserve, k)     for k in SECTIONS}
avgs_yes = {k: _avg_section(_results_with_preserve, k)   for k in SECTIONS}

# ============================================================
# STEP 9: Emit [TIMING]-tagged machine-readable output
# ============================================================
print("\n=== TIMING SUMMARY ===")
print(f"\n  Mesh: ECF_Test.blend  "
      f"total_verts={len(cloth.data.vertices)}  "
      f"fitted_verts={len(fitted_indices)}")

print("\n  === Preserve OFF (follow_strength=0.0) ===")
for k in SECTIONS:
    print(f"    {k:10s}: {avgs_no[k]:.3f} ms")

print("\n  === Preserve ON (follow_strength=1.0, K=32) ===")
for k in SECTIONS:
    print(f"    {k:10s}: {avgs_yes[k]:.3f} ms")

preserve_overhead = avgs_yes['preserve'] - avgs_no['preserve']
print(f"\n  preserve-follow overhead (K=32): {preserve_overhead:.2f}ms")

# [TIMING] tagged lines — machine-readable, filter with grep '\[TIMING\]'
print(f"\n[TIMING] mesh_verts={len(cloth.data.vertices)}")
print(f"[TIMING] fitted_verts={len(fitted_indices)}")
for k in SECTIONS:
    ms = avgs_no[k]
    print(f"[TIMING] no_preserve_{k}_ms={ms:.3f}")
for k in SECTIONS:
    ms = avgs_yes[k]
    print(f"[TIMING] preserve_K32_{k}_ms={ms:.3f}")
print(f"[TIMING] TOTAL_no_preserve_ms={avgs_no['total']:.3f}")
print(f"[TIMING] TOTAL_with_preserve_K32_ms={avgs_yes['total']:.3f}")
print(f"[TIMING] preserve_overhead_K32_ms={preserve_overhead:.2f}")

# Sub-16ms verdict (without preserve-follow)
sub16 = avgs_no['total'] < 16.0
print(f"[TIMING] sub16ms_no_preserve={'YES' if sub16 else 'NO'}  ({avgs_no['total']:.2f}ms)")

# ============================================================
# STEP 10: Final summary
# ============================================================
print("\n=== BENCHMARK COMPLETE ===")
print(f"  No-preserve total:   {avgs_no['total']:.2f}ms  "
      f"({'sub-16ms ✓' if sub16 else 'OVER 16ms ✗'})")
print(f"  With-preserve total: {avgs_yes['total']:.2f}ms  (K=32, known bottleneck per D044)")

sys.exit(0)
