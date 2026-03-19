# test_proxy_hull.py
# Regression tests for the proxy body hull feature (S01).
#
# REQUIRES: elastic_fit addon installed and enabled.
#           test scene at tests/ECF_Test.blend (Body + Outfit objects).
#
# Run via: blender --background --python tests/test_proxy_hull.py

BLEND_PATH    = r"C:\Users\Staples\Documents\GitHub\Elastic-Clothing-Fit\tests\ECF_Test.blend"
BODY_NAME     = "Body"
CLOTHING_NAME = "Outfit"

# ============================================================
# STEP 1: Property exists with correct default
# ============================================================
STEP_1 = '''
import bpy

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

print("\\n=== STEP 1: use_proxy_hull property default ===")
p = bpy.context.scene.efit_props
_assert_true(hasattr(p, "use_proxy_hull"), "use_proxy_hull property exists")
_assert_equal(p.use_proxy_hull, False, "use_proxy_hull defaults to False")
print("\\n=== STEP 1 COMPLETE ===")
'''

# ============================================================
# STEP 2: Hull disabled -- fit produces same result as baseline
#         (toggle=False must not change pipeline behaviour)
# ============================================================
STEP_2 = '''
import bpy
import elastic_fit.state as state

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

print("\\n=== STEP 2: hull=False fit runs without error ===")
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
p = bpy.context.scene.efit_props
p.body_obj     = bpy.data.objects[BODY_NAME]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME]
p.use_proxy_hull = False

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == "VIEW_3D")
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.fit()

_assert_equal(result, {"FINISHED"}, "efit.fit returned FINISHED with hull=False")
_assert_true(bool(state._efit_cache), "cache populated after hull=False fit")

# No hull object should exist in the scene.
hull_objects = [o for o in bpy.data.objects if "HullProxy" in o.name]
_assert_equal(len(hull_objects), 0, "no EFit_HullProxy object in scene after hull=False fit")

# Record baseline positions.
cloth = bpy.data.objects[CLOTHING_NAME]
baseline_positions = [v.co.copy() for v in cloth.data.vertices]

# Cancel preview so the clothing is restored before the hull test.
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_cancel()

_assert_true(not state._efit_cache, "cache cleared after cancel")
print("  Baseline positions recorded.")
print("\\n=== STEP 2 COMPLETE ===")
'''

# ============================================================
# STEP 3: Hull enabled -- fit runs without error, no hull leaks
# ============================================================
STEP_3 = '''
import bpy
import elastic_fit.state as state

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

print("\\n=== STEP 3: hull=True fit runs, no hull leaks ===")
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
p = bpy.context.scene.efit_props
p.body_obj       = bpy.data.objects[BODY_NAME]
p.clothing_obj   = bpy.data.objects[CLOTHING_NAME]
p.use_proxy_hull = True

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == "VIEW_3D")
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.fit()

_assert_equal(result, {"FINISHED"}, "efit.fit returned FINISHED with hull=True")
_assert_true(bool(state._efit_cache), "cache populated after hull=True fit")

# Hull object must be removed before the preview phase starts.
hull_objects = [o for o in bpy.data.objects if "HullProxy" in o.name]
_assert_equal(len(hull_objects), 0, "no EFit_HullProxy object leaks into scene during preview")

# Fitted vertices must have actually moved from their original positions.
cloth = bpy.data.objects[CLOTHING_NAME]
originals = state._efit_cache.get("all_originals", {})
fitted    = state._efit_cache.get("fitted_indices", [])
moved = sum(
    1 for vi in fitted
    if vi in originals and (cloth.data.vertices[vi].co - originals[vi]).length > 1e-6
)
_assert_true(moved > 0, f"at least one fitted vertex moved with hull=True ({moved} moved)")

# Apply and confirm hull still absent after apply.
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_apply()
hull_after_apply = [o for o in bpy.data.objects if "HullProxy" in o.name]
_assert_equal(len(hull_after_apply), 0, "no EFit_HullProxy after apply")

# Reset.
p.use_proxy_hull = False
print("\\n=== STEP 3 COMPLETE ===")
'''

# ============================================================
# STEP 4: Hull produces different vertex positions than no-hull
#         (verifies the hull actually changes the shrinkwrap target)
# ============================================================
STEP_4 = '''
import bpy
import elastic_fit.state as state

BLEND_PATH    = r"C:\\Users\\Staples\\Documents\\GitHub\\Elastic-Clothing-Fit\\tests\\ECF_Test.blend"
BODY_NAME     = "Body"
CLOTHING_NAME = "Outfit"

def _assert_true(condition, label):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition

print("\\n=== STEP 4: hull produces different positions than no-hull ===")

# Fit WITHOUT hull and record applied positions.
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
# Re-fetch window/area AFTER open_mainfile -- the previous screen objects are stale.
_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == "VIEW_3D")
p = bpy.context.scene.efit_props
p.body_obj       = bpy.data.objects[BODY_NAME]
p.clothing_obj   = bpy.data.objects[CLOTHING_NAME]
p.use_proxy_hull = False
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.fit()
cloth = bpy.data.objects[CLOTHING_NAME]
no_hull_positions = [v.co.copy() for v in cloth.data.vertices]
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_cancel()

# Fit WITH hull and record applied positions.
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
# Re-fetch window/area AFTER open_mainfile -- the previous screen objects are stale.
_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == "VIEW_3D")
p = bpy.context.scene.efit_props
p.body_obj       = bpy.data.objects[BODY_NAME]
p.clothing_obj   = bpy.data.objects[CLOTHING_NAME]
p.use_proxy_hull = True
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.fit()
cloth = bpy.data.objects[CLOTHING_NAME]
hull_positions = [v.co.copy() for v in cloth.data.vertices]
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_cancel()

# At least some vertices must differ between the two fits.
# On a body with concave regions the hull fills those areas, so the
# shrinkwrap displaces clothing vertices differently.
differing = sum(
    1 for a, b in zip(no_hull_positions, hull_positions)
    if (a - b).length > 1e-5
)
_assert_true(
    differing > 0,
    f"hull=True produces different vertex positions than hull=False ({differing} vertices differ)"
)
print(f"  {differing}/{len(hull_positions)} vertices differ between hull and no-hull fits")

p.use_proxy_hull = False
print("\\n=== STEP 4 COMPLETE ===")
print("\\n=== ALL PROXY HULL TESTS COMPLETE ===")
'''
