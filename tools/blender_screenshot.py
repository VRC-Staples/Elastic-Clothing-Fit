"""blender_screenshot.py -- headless Blender script to render 6 orthographic views of a mesh.

Usage:
    blender --background --python tools/blender_screenshot.py -- --blend-file <path> [--out-dir <path>]

Arguments (after the -- separator):
    --blend-file <path>   Path to the .blend file to open. Required.
    --out-dir <path>      Root output directory. Defaults to <repo_root>/tmp.
                          Renders are saved to <out-dir>/fit-test/<YYYYMMDD_HHMMSS>/.

Exit codes:
    0 -- success, all 6 views rendered
    1 -- failure; an [ERROR] line is printed describing what went wrong
"""

import sys
import os
from pathlib import Path
from datetime import datetime

import bpy
from mathutils import Vector


# ---- parse CLI args (same pattern as tests/blender_suites/suite_fit_pipeline.py) ----

_argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
_blend_file = None
_out_dir = None
_i = 0
while _i < len(_argv):
    if _argv[_i] == "--blend-file" and _i + 1 < len(_argv):
        _blend_file = _argv[_i + 1]
        _i += 2
    elif _argv[_i] == "--out-dir" and _i + 1 < len(_argv):
        _out_dir = _argv[_i + 1]
        _i += 2
    else:
        _i += 1

if _blend_file is None:
    print("[ERROR] --blend-file <path> is required")
    sys.exit(1)

blend_path = Path(_blend_file).resolve()
if not blend_path.exists():
    print(f"[ERROR] blend file not found: {blend_path}")
    sys.exit(1)


# ---- open blend file ----

try:
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
except Exception as exc:
    print(f"[ERROR] failed to open blend file '{blend_path}': {exc}")
    sys.exit(1)


# ---- detect and set render engine ----

scene = bpy.context.scene

ENGINES_IN_PREFERENCE_ORDER = [
    "BLENDER_EEVEE_NEXT",
    "BLENDER_EEVEE",
    "BLENDER_WORKBENCH",
]

selected_engine = None
for candidate in ENGINES_IN_PREFERENCE_ORDER:
    try:
        scene.render.engine = candidate
        # verify the assignment stuck
        if scene.render.engine == candidate:
            selected_engine = candidate
            break
    except Exception:
        continue

if selected_engine is None:
    # fall back to whatever was already set rather than crashing
    selected_engine = scene.render.engine

print(f"[ENGINE] {selected_engine}")


# ---- set up output directory ----

repo_root = Path(__file__).parent.parent
base_out = Path(_out_dir).resolve() if _out_dir else repo_root / "tmp"
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
fit_test_dir = base_out / "fit-test"
output_dir = fit_test_dir / timestamp

try:
    output_dir.mkdir(parents=True, exist_ok=True)
except Exception as exc:
    print(f"[ERROR] could not create output directory '{output_dir}': {exc}")
    sys.exit(1)

print(f"[SCREENSHOTS] {output_dir}")


# ---- prune old screenshot sets ----

_MAX_SCREENSHOT_SETS = 25


def _prune_old_screenshot_sets(fit_test_root, max_sets):
    """Remove the oldest timestamp subdirectories from fit_test_root so that at
    most *max_sets* directories remain.

    Only directories whose names match the YYYYMMDD_HHMMSS timestamp pattern
    (exactly 15 characters: 8 digits, underscore, 6 digits) are considered;
    any other entries are left untouched.

    Directories are sorted lexicographically by name, which is equivalent to
    chronological order for the YYYYMMDD_HHMMSS format.  The oldest entries
    (lowest sort values) are deleted first.

    Errors during deletion are printed as warnings and do not abort the script.
    """
    import re
    import shutil

    pattern = re.compile(r"^\d{8}_\d{6}$")

    try:
        entries = [
            d for d in fit_test_root.iterdir()
            if d.is_dir() and pattern.match(d.name)
        ]
    except Exception as exc:
        print(f"[WARNING] could not list screenshot sets in '{fit_test_root}': {exc}")
        return

    if len(entries) <= max_sets:
        return  # nothing to prune

    # Sort oldest-first (lexicographic == chronological for this timestamp format)
    entries.sort(key=lambda d: d.name)
    to_delete = entries[: len(entries) - max_sets]

    for old_dir in to_delete:
        try:
            shutil.rmtree(old_dir)
            print(f"[PRUNE] removed old screenshot set: {old_dir}")
        except Exception as exc:
            print(f"[WARNING] could not remove old screenshot set '{old_dir}': {exc}")


_prune_old_screenshot_sets(fit_test_dir, _MAX_SCREENSHOT_SETS)


# ---- bounding box ----

def _get_scene_bounds(scene):
    """Return (center: Vector, dimensions: Vector) in world space for all mesh objects.

    If no mesh objects are present the function returns a safe default so downstream
    camera and light setup does not crash.
    """
    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]

    if not mesh_objects:
        # safe default: unit cube at origin
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))

    # Accumulate world-space corners across all mesh objects.
    xs, ys, zs = [], [], []
    for obj in mesh_objects:
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ Vector(corner)
            xs.append(world_corner.x)
            ys.append(world_corner.y)
            zs.append(world_corner.z)

    min_v = Vector((min(xs), min(ys), min(zs)))
    max_v = Vector((max(xs), max(ys), max(zs)))
    center = (min_v + max_v) / 2.0
    dimensions = max_v - min_v

    # Guard against degenerate (zero-size) meshes on any axis.
    if dimensions.x < 1e-6:
        dimensions.x = 1.0
    if dimensions.y < 1e-6:
        dimensions.y = 1.0
    if dimensions.z < 1e-6:
        dimensions.z = 1.0

    return center, dimensions


# ---- lighting ----

def _setup_lights(scene, center, size):
    """Create a three-point lighting rig sized to the scene bounding box.

    Returns a list of bpy.types.Object so T03 can remove them during cleanup.

    Positions:
      key  -- upper-front-left  (45 deg, positive Y forward convention)
      fill -- upper-front-right (lower energy, opposite side from key)
      rim  -- back-top          (behind the subject, creates separation)
    """
    max_dim = max(size.x, size.y, size.z)
    base_energy = max_dim * 10.0
    dist = max_dim * 2.0

    light_specs = [
        {
            "name": "ECF_Light_Key",
            "type": "AREA",
            "energy": base_energy,
            # front-left-above: +X is right, +Y is towards viewer, +Z is up
            "offset": Vector((-dist, dist, dist)),
        },
        {
            "name": "ECF_Light_Fill",
            "type": "AREA",
            "energy": base_energy * 0.5,
            # front-right-above: opposite side from key
            "offset": Vector((dist, dist, dist * 0.5)),
        },
        {
            "name": "ECF_Light_Rim",
            "type": "AREA",
            "energy": base_energy * 0.3,
            # directly behind and above
            "offset": Vector((0.0, -dist, dist * 1.5)),
        },
    ]

    created = []
    for spec in light_specs:
        light_data = bpy.data.lights.new(name=spec["name"], type=spec["type"])
        light_data.energy = spec["energy"]
        # AREA lights use size to control spread; scale with scene
        light_data.size = max_dim * 0.5

        light_obj = bpy.data.objects.new(name=spec["name"], object_data=light_data)
        light_obj.location = center + spec["offset"]

        # point the light at the scene center
        direction = center - light_obj.location
        rot = direction.to_track_quat("-Z", "Y")
        light_obj.rotation_euler = rot.to_euler()

        scene.collection.objects.link(light_obj)
        created.append(light_obj)

    return created


# ---- camera rig ----

# Six orthographic views: name, normalized direction from center, and which two
# bounding box axes determine the ortho_scale for that view.
#
# scale_axes selects which two dimension components form the visible cross-section
# for each camera direction:
#   front/back  -> X width, Z height
#   left/right  -> Y depth, Z height
#   top/bottom  -> X width, Y depth
_VIEW_CONFIGS = [
    {
        "name": "front",
        "direction": Vector((0.0, 1.0, 0.0)),   # looking towards -Y
        "scale_axes": ("x", "z"),
    },
    {
        "name": "back",
        "direction": Vector((0.0, -1.0, 0.0)),  # looking towards +Y
        "scale_axes": ("x", "z"),
    },
    {
        "name": "left",
        "direction": Vector((-1.0, 0.0, 0.0)),  # looking towards +X
        "scale_axes": ("y", "z"),
    },
    {
        "name": "right",
        "direction": Vector((1.0, 0.0, 0.0)),   # looking towards -X
        "scale_axes": ("y", "z"),
    },
    {
        "name": "top",
        "direction": Vector((0.0, 0.0, 1.0)),   # looking towards -Z
        "scale_axes": ("x", "y"),
    },
    {
        "name": "bottom",
        "direction": Vector((0.0, 0.0, -1.0)),  # looking towards +Z
        "scale_axes": ("x", "y"),
    },
]


def _setup_cameras(scene, center, size):
    """Create one orthographic camera per view, tightly framed to the bounding box.

    Each camera is placed at center + direction * (max_dim * 2.5) and pointed back
    at center using to_track_quat so it is always axis-aligned and upright.

    ortho_scale is set to max(cross-section axes) * 1.1 (10% padding).

    Returns a list of (view_name, camera_obj) tuples for the T03 render loop.
    """
    max_dim = max(size.x, size.y, size.z)
    camera_distance = max_dim * 2.5

    cameras = []
    for cfg in _VIEW_CONFIGS:
        cam_data = bpy.data.cameras.new(name=f"ECF_Cam_{cfg['name']}")
        cam_data.type = "ORTHO"

        # ortho_scale = largest visible cross-section extent + 10% padding
        a0 = getattr(size, cfg["scale_axes"][0])
        a1 = getattr(size, cfg["scale_axes"][1])
        cam_data.ortho_scale = max(a0, a1) * 1.1

        cam_obj = bpy.data.objects.new(name=f"ECF_Cam_{cfg['name']}", object_data=cam_data)
        cam_obj.location = center + cfg["direction"] * camera_distance

        # point camera back at the scene center
        direction_to_center = center - cam_obj.location
        rot = direction_to_center.to_track_quat("-Z", "Y")
        cam_obj.rotation_euler = rot.to_euler()

        scene.collection.objects.link(cam_obj)
        cameras.append((cfg["name"], cam_obj))

    return cameras


# ---- compute bounds and build rig ----

scene_center, scene_size = _get_scene_bounds(scene)
lights = _setup_lights(scene, scene_center, scene_size)
cameras = _setup_cameras(scene, scene_center, scene_size)

print(f"[BOUNDS] center={tuple(round(v, 3) for v in scene_center)} "
      f"size={tuple(round(v, 3) for v in scene_size)}")
print(f"[CAMERAS] {len(cameras)} cameras created: {[name for name, _ in cameras]}")
print(f"[LIGHTS] {len(lights)} lights created: {[obj.name for obj in lights]}")


# ---- configure render settings ----

scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
# EEVEE render samples: 16 is sufficient for material preview quality
if hasattr(scene.eevee, "taa_render_samples"):
    scene.eevee.taa_render_samples = 16
elif hasattr(scene.eevee, "samples"):
    scene.eevee.samples = 16


# ---- cleanup helper ----

def _cleanup(cameras, lights):
    """Remove all temporary camera and light objects created by this script.

    Iterates the tracked object lists from the rig setup and removes both the
    object and its underlying data block so nothing leaks into the scene.
    """
    for _name, cam_obj in cameras:
        try:
            cam_data = cam_obj.data
            bpy.data.objects.remove(cam_obj, do_unlink=True)
            bpy.data.cameras.remove(cam_data)
        except Exception as exc:
            print(f"[WARNING] could not remove camera '{cam_obj.name}': {exc}")

    for light_obj in lights:
        try:
            light_data = light_obj.data
            bpy.data.objects.remove(light_obj, do_unlink=True)
            bpy.data.lights.remove(light_data)
        except Exception as exc:
            print(f"[WARNING] could not remove light '{light_obj.name}': {exc}")


# ---- render loop ----

render_failed = False

for view_name, cam_obj in cameras:
    scene.camera = cam_obj
    out_filepath = str(output_dir / f"{view_name}.png")
    scene.render.filepath = out_filepath

    print(f"[RENDER] {view_name} -> {out_filepath}")

    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        print(f"[ERROR] render failed for {view_name}: {exc}", file=sys.stderr)
        print(f"[ERROR] render failed for {view_name}: {exc}")
        render_failed = True


# ---- cleanup ----

_cleanup(cameras, lights)


# ---- final result ----

if render_failed:
    print("[ERROR] one or more renders failed; see above for details", file=sys.stderr)
    print("[ERROR] one or more renders failed; see above for details")
    sys.exit(1)

print(f"[SCREENSHOTS] {output_dir}")
sys.exit(0)
