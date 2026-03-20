"""proximity_fit_screenshot.py -- run fit with proximity falloff on ECF_Test3, then screenshot.

Usage:
    blender --background --python tools/proximity_fit_screenshot.py -- --blend-root <repo_root>

Runs efit.fit with proximity_falloff enabled, then renders 6 orthographic views
so the post-fit mesh state can be inspected visually.

Exit codes:
    0 -- success
    1 -- failure
"""

import sys
import os
from pathlib import Path
from datetime import datetime

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

BLEND_PATH    = os.path.join(_blend_root, "tests", "ECF_Test3.blend")
BODY_NAME     = "Body"
CLOTHING_NAME = "Dinzee's Trackside Hoodie Bodysuit_Flexuh"

import bpy
from mathutils import Vector

# ---- open blend ----
bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)

# ---- set engine ----
scene = bpy.context.scene
for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
    try:
        scene.render.engine = engine
        if scene.render.engine == engine:
            break
    except Exception:
        continue
print(f"[ENGINE] {scene.render.engine}")

# ---- set pickers and run fit with proximity falloff ----
p = scene.efit_props
p.body_obj     = bpy.data.objects[BODY_NAME]
p.clothing_obj = bpy.data.objects[CLOTHING_NAME]

p.use_proximity_falloff = True
p.proximity_mode  = 'PRE_FIT'
p.proximity_start = 0.0
p.proximity_end   = 0.05
p.proximity_curve = 'SMOOTH'

_win  = bpy.context.window_manager.windows[0]
_area = next(a for a in _win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=_win, area=_area):
    result = bpy.ops.efit.fit()

if result != {'FINISHED'}:
    print(f"[ERROR] efit.fit returned {result}")
    sys.exit(1)
print("[FIT] fit completed with proximity falloff")

# Apply the fit so the mesh data is baked
with bpy.context.temp_override(window=_win, area=_area):
    bpy.ops.efit.preview_apply()
print("[FIT] fit applied")

# ---- output dir ----
repo_root = Path(_blend_root).resolve()
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_dir = repo_root / "tmp" / "fit-test" / timestamp
output_dir.mkdir(parents=True, exist_ok=True)

# ---- bounds ----
mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
xs, ys, zs = [], [], []
for obj in mesh_objects:
    for corner in obj.bound_box:
        wc = obj.matrix_world @ Vector(corner)
        xs.append(wc.x); ys.append(wc.y); zs.append(wc.z)
min_v = Vector((min(xs), min(ys), min(zs)))
max_v = Vector((max(xs), max(ys), max(zs)))
center = (min_v + max_v) / 2.0
size   = max_v - min_v
for attr in ('x', 'y', 'z'):
    if getattr(size, attr) < 1e-6:
        setattr(size, attr, 1.0)
print(f"[BOUNDS] center={tuple(round(v,3) for v in center)} size={tuple(round(v,3) for v in size)}")

# ---- lights ----
max_dim = max(size.x, size.y, size.z)
dist = max_dim * 2.0
for spec in [
    ("ECF_Light_Key",  "AREA", max_dim*10,     Vector((-dist,  dist, dist))),
    ("ECF_Light_Fill", "AREA", max_dim*5,      Vector(( dist,  dist, dist*0.5))),
    ("ECF_Light_Rim",  "AREA", max_dim*3,      Vector(( 0.0,  -dist, dist*1.5))),
]:
    ld = bpy.data.lights.new(name=spec[0], type=spec[1])
    ld.energy = spec[2]; ld.size = max_dim * 0.5
    lo = bpy.data.objects.new(name=spec[0], object_data=ld)
    lo.location = center + spec[3]
    rot = (center - lo.location).to_track_quat("-Z", "Y")
    lo.rotation_euler = rot.to_euler()
    scene.collection.objects.link(lo)

# ---- cameras and render ----
# front: character faces -Y, camera on -Y side looking toward +Y
VIEW_CONFIGS = [
    ("front",  Vector(( 0.0, -1.0,  0.0)), ("x", "z")),
    ("back",   Vector(( 0.0,  1.0,  0.0)), ("x", "z")),
    ("left",   Vector((-1.0,  0.0,  0.0)), ("y", "z")),
    ("right",  Vector(( 1.0,  0.0,  0.0)), ("y", "z")),
    ("top",    Vector(( 0.0,  0.0,  1.0)), ("x", "y")),
    ("bottom", Vector(( 0.0,  0.0, -1.0)), ("x", "y")),
]

scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
if hasattr(scene.eevee, "taa_render_samples"):
    scene.eevee.taa_render_samples = 16
elif hasattr(scene.eevee, "samples"):
    scene.eevee.samples = 16

for view_name, direction, scale_axes in VIEW_CONFIGS:
    cd = bpy.data.cameras.new(name=f"ECF_Cam_{view_name}")
    cd.type = "ORTHO"
    cd.ortho_scale = max(getattr(size, scale_axes[0]), getattr(size, scale_axes[1])) * 1.1
    co = bpy.data.objects.new(name=f"ECF_Cam_{view_name}", object_data=cd)
    co.location = center + direction * (max_dim * 2.5)
    rot = (center - co.location).to_track_quat("-Z", "Y")
    co.rotation_euler = rot.to_euler()
    scene.collection.objects.link(co)
    scene.camera = co
    out_path = str(output_dir / f"{view_name}.png")
    scene.render.filepath = out_path
    print(f"[RENDER] {view_name} -> {out_path}")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(co, do_unlink=True)
    bpy.data.cameras.remove(cd)

print(f"[SCREENSHOTS] {output_dir}")
sys.exit(0)
