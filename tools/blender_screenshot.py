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
output_dir = base_out / "fit-test" / timestamp

try:
    output_dir.mkdir(parents=True, exist_ok=True)
except Exception as exc:
    print(f"[ERROR] could not create output directory '{output_dir}': {exc}")
    sys.exit(1)

print(f"[SCREENSHOTS] {output_dir}")


# ---- placeholder for render loop (implemented in T03) ----
# T02 adds bounding box computation, camera rig, and lighting.
# T03 adds the render loop that writes PNGs and calls sys.exit based on results.

sys.exit(0)
