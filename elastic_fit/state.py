# state.py
# Module-level constants, shared mutable globals, and pure utility functions.
# All other modules import this module and access globals as state._efit_cache
# and state._efit_updating rather than using 'from' imports, so that rebinding
# these names here is visible across the whole package.

import math
import mathutils

import bpy

# Sidebar panel tab name.
PANEL_CATEGORY = ".Staples. ECF"

# Prefix applied to all modifiers and proxy objects created by this add-on.
EFIT_PREFIX = "EFit_"

# _efit_cache holds the pre-computed displacements, normals, and adjacency data
# generated during EFIT_OT_fit.execute().  Slider callbacks read from it to
# reapply the fit without re-running the full shrinkwrap pipeline.
# Empty dict == no active preview.
_efit_cache = {}

# Guard flag to prevent _efit_preview_update from re-entering itself when it
# writes vertex positions back to the mesh (which can retrigger update callbacks).
_efit_updating = False


def _mesh_poll(self, obj):
    """PointerProperty poll: restricts the eyedropper to mesh objects only."""
    return obj.type == 'MESH'


def _has_blockers(obj):
    """Return (has_shape_keys, [modifier_names]) for items that block fitting.

    Shape keys and non-armature, non-EFit modifiers must be removed before the
    fitting pipeline runs.
    """
    has_sk = obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 0
    mod_names = [m.name for m in obj.modifiers
                 if not m.name.startswith(EFIT_PREFIX) and m.type != 'ARMATURE']
    return has_sk, mod_names


def _calc_subdivisions(current_tris, target_tris):
    """Return the number of subdivision levels needed to reach target_tris.

    Each subdivision level multiplies the triangle count by roughly 4.
    Returns at least 1 if the mesh needs to grow, 0 if it is already large enough.
    """
    if current_tris <= 0:
        return 1
    ratio = target_tris / current_tris
    if ratio <= 1:
        return 0
    levels = math.log(ratio) / math.log(4)
    return max(1, round(levels))


def _save_uvs(mesh):
    """Snapshot all UV layers on mesh into a dict keyed by layer name.

    Returns {layer_name: [Vector2D, ...]} preserving loop order.
    """
    uv_data = {}
    for uv_layer in mesh.uv_layers:
        uv_data[uv_layer.name] = [loop.uv.copy() for loop in uv_layer.data]
    return uv_data


def _restore_uvs(mesh, uv_data):
    """Write UV coordinates saved by _save_uvs back onto mesh."""
    for layer_name, coords in uv_data.items():
        uv_layer = mesh.uv_layers.get(layer_name)
        if uv_layer is None:
            continue
        for i, loop in enumerate(uv_layer.data):
            if i < len(coords):
                loop.uv = coords[i]


def _remove_efit(obj):
    """Remove all EFit_ modifiers from obj and restore its original vertex positions.

    Original positions are stored in the obj["_efit_originals"] custom property
    as a flat float array [x0, y0, z0, x1, y1, z1, ...].
    """
    global _efit_cache
    _efit_cache.clear()

    for m in [m for m in obj.modifiers if m.name.startswith(EFIT_PREFIX)]:
        obj.modifiers.remove(m)

    flat = obj.get("_efit_originals")
    if flat is not None:
        verts = obj.data.vertices
        for vi in range(len(verts)):
            idx = vi * 3
            if idx + 2 < len(flat):
                verts[vi].co = mathutils.Vector((flat[idx], flat[idx + 1], flat[idx + 2]))
        del obj["_efit_originals"]
        obj.data.update()
