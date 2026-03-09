# state.py
# Module-level constants, shared mutable globals, and pure utility functions.
# All other modules import this module and access globals as state._efit_cache
# and state._efit_updating rather than using 'from' imports, so that rebinding
# these names here is visible across the whole package.

import math
import mathutils
import numpy as np

# Sidebar panel tab name.
PANEL_CATEGORY = ".Staples. ECF"

# Prefix applied to all modifiers and proxy objects created by this add-on.
EFIT_PREFIX = "EFit_"

# _efit_cache holds the pre-computed displacements, normals, and adjacency data
# generated during EFIT_OT_fit.execute().  Slider callbacks read from it to
# reapply the fit without re-running the full shrinkwrap pipeline.
# Empty dict == no active preview.
_efit_cache = {}

# _efit_originals maps cloth object name -> flat float array of pre-fit vertex
# positions [x0, y0, z0, x1, ...].  Stored here (in addition to the object's
# custom property) so Remove Fit works reliably after Apply even when modifier
# application replaces the mesh data block in the same session.
_efit_originals = {}

# Guard flag to prevent _efit_preview_update from re-entering itself when it
# writes vertex positions back to the mesh (which can retrigger update callbacks).
_efit_updating = False

# Cache for _has_blockers_cached.  Key: (obj.name, n_mods, n_shape_keys).
# Cleared on every miss so stale keys never accumulate.
_blocker_cache = {}


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


def _has_blockers_cached(obj):
    """Cached wrapper around _has_blockers for use in panel draw() calls.

    Blender calls draw() up to 60 times per second.  This caches the result
    keyed by (name, modifier count, shape key count) and clears on any miss
    so stale entries never accumulate.
    """
    n_mods = len(obj.modifiers)
    n_sk   = (len(obj.data.shape_keys.key_blocks)
              if obj.data.shape_keys else 0)
    key = (obj.name, n_mods, n_sk)
    if key not in _blocker_cache:
        _blocker_cache.clear()
        _blocker_cache[key] = _has_blockers(obj)
    return _blocker_cache[key]


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

    Returns {layer_name: np.ndarray} flat float32 buffer in loop order.
    Uses foreach_get for a single C-level bulk read per layer.
    """
    uv_data = {}
    for uv_layer in mesh.uv_layers:
        buf = np.empty(len(uv_layer.data) * 2, dtype=np.float32)
        uv_layer.data.foreach_get("uv", buf)
        uv_data[uv_layer.name] = buf
    return uv_data


def _restore_uvs(mesh, uv_data):
    """Write UV coordinates saved by _save_uvs back onto mesh.

    Uses foreach_set for a single C-level bulk write per layer.
    """
    for layer_name, buf in uv_data.items():
        uv_layer = mesh.uv_layers.get(layer_name)
        if uv_layer is None:
            continue
        uv_layer.data.foreach_set("uv", buf)


def _remove_efit(obj):
    """Remove all EFit_ modifiers from obj and restore its original vertex positions.

    Checks the module-level _efit_originals dict first (reliable within the
    current session), then falls back to the obj["_efit_originals"] custom
    property (covers .blend files loaded from a previous session).
    """
    global _efit_cache, _efit_originals
    _efit_cache.clear()

    for m in [m for m in obj.modifiers if m.name.startswith(EFIT_PREFIX)]:
        obj.modifiers.remove(m)

    # Prefer the in-memory store; fall back to the custom property.
    flat = _efit_originals.pop(obj.name, None)
    if flat is None:
        flat = obj.get("_efit_originals")
    if "_efit_originals" in obj:
        del obj["_efit_originals"]

    if flat is not None:
        buf = np.asarray(flat, dtype=np.float64)
        obj.data.vertices.foreach_set("co", buf)
        obj.data.update()


# ---------------------------------------------------------------------------
# Proximity falloff: pure curve functions and weight computation
# ---------------------------------------------------------------------------

def _proximity_curve_linear(t):
    return 1.0 - t


def _proximity_curve_smooth(t):
    s = 1.0 - t
    return s * s * (3.0 - 2.0 * s)


def _proximity_curve_sharp(t):
    return (1.0 - t) ** 2


def _proximity_curve_root(t):
    return math.sqrt(max(0.0, 1.0 - t))


PROXIMITY_CURVES = {
    'LINEAR': _proximity_curve_linear,
    'SMOOTH': _proximity_curve_smooth,
    'SHARP':  _proximity_curve_sharp,
    'ROOT':   _proximity_curve_root,
}


def _compute_proximity_weights(distances, fitted_indices, start, end, curve_key):
    """Return {vi: weight} falloff weights for fitted vertices based on body distance.

    Vertices closer than start receive weight 1.0 (full fit pull).
    Vertices beyond end receive weight 0.0 (no fit pull).
    Vertices between start and end are mapped through the selected curve.
    """
    curve_fn = PROXIMITY_CURVES.get(curve_key, _proximity_curve_smooth)
    span = max(end - start, 0.0001)
    weights = {}
    for vi in fitted_indices:
        dist = distances.get(vi, 0.0)
        if dist <= start:
            weights[vi] = 1.0
        elif dist >= end:
            weights[vi] = 0.0
        else:
            t = (dist - start) / span
            weights[vi] = max(0.0, min(1.0, curve_fn(t)))
    return weights
