# state.py
# Module-level constants, shared mutable globals, and pure utility functions.
# All other modules import this module and access globals as state._efit_cache
# and state._efit_updating rather than using 'from' imports, so that rebinding
# these names here is visible across the whole package.

import math
import numpy as np

from .deformation import compute_proximity_weights

# Sidebar panel tab name.
PANEL_CATEGORY = ".Staples. ECF"

# Prefix applied to all modifiers and proxy objects created by this add-on.
EFIT_PREFIX = "EFit_"

# _efit_cache holds a complete prepared fit and the clothing lookup name.
# Slider callbacks reuse that fit without repeating the shrinkwrap pipeline.
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

# Last exception string from _efit_preview_update.  Set by the except block so
# that future debugging sessions can call `state._efit_last_error` in the
# Blender Python console without needing a live error in progress.
# Follows the _efit_updating pattern: module-level, reset to '' on a clean run.
_efit_last_error = ''

# Cache for _has_blockers_cached.  Key: (obj.name, n_mods, n_shape_keys).
# Cleared on every miss so stale keys never accumulate.
_blocker_cache = {}

# Cache for body BVH trees. Key: (obj.name, n_verts, n_polys).
# Populated by S02 pipeline.py; cleared on addon unregister.
_bvh_cache = {}


def _mesh_poll(self, obj):
    """PointerProperty poll: restricts the eyedropper to mesh objects only."""
    return obj.type == 'MESH'


def _armature_poll(self, obj):
    """PointerProperty poll: restricts the eyedropper to armature objects only."""
    return obj.type == 'ARMATURE'


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


def _compute_proximity_group_weights(cloth, proximity_groups, prepared):
    """Adapt Blender membership to fitted rows. Uncovered rows stay at full weight.

    Body distances use the global proximity mode. Groups change only falloff.
    The last group in the list wins when memberships overlap.
    """
    result = np.ones(len(prepared.fitted_indices), dtype=np.float64)
    for pg in proximity_groups:
        # Empty string means no group selected.
        pg_name = pg.group_name.strip() if pg.group_name else ""
        if not pg_name:
            continue
        vg = cloth.vertex_groups.get(pg_name)
        if vg is None:
            continue
        vg_idx = vg.index

        if vg_idx in prepared.vg_membership:
            rows = [prepared.row_of_vertex[vi] for vi in prepared.vg_membership[vg_idx]
                    if vi in prepared.row_of_vertex]
        else:
            rows = []
            for v in cloth.data.vertices:
                if v.index not in prepared.row_of_vertex:
                    continue
                for g in v.groups:
                    if g.group == vg_idx and g.weight > 0.0:
                        rows.append(prepared.row_of_vertex[v.index])
                        break

        if not rows:
            continue

        rows = np.array(rows, dtype=np.int32)
        result[rows] = compute_proximity_weights(
            prepared.body_distances[rows],
            pg.proximity_start, pg.proximity_end, pg.proximity_curve)

    return result


def _get_proximity_weights(cloth, p, prepared):
    """Read Blender group membership and cache weights on this prepared fit only."""
    if (not p.use_proximity_falloff or prepared.body_distances is None
            or len(prepared.body_distances) == 0):
        return None
    use_groups = p.use_proximity_group_tuning and len(p.proximity_groups) > 0
    key = (use_groups, p.proximity_start, p.proximity_end, p.proximity_curve)
    if prepared.proximity_key != key or prepared.proximity_weights is None:
        if use_groups:
            weights = _compute_proximity_group_weights(
                cloth, p.proximity_groups, prepared)
        else:
            weights = compute_proximity_weights(
                prepared.body_distances, p.proximity_start, p.proximity_end, p.proximity_curve)
        prepared.proximity_weights = weights
        prepared.proximity_key = key
    return prepared.proximity_weights


# ---------------------------------------------------------------------------
# Callback registry -- decouples PropertyGroup update= callbacks from preview.py
# ---------------------------------------------------------------------------

_handlers = {}


def register_handler(name, fn):
    """Register a named update handler callable."""
    _handlers[name] = fn


def unregister_handler(name):
    """Remove a named handler (called on addon unregister)."""
    _handlers.pop(name, None)


def call_handler(name, self, context):
    """Invoke a registered handler by name. No-op if not yet registered."""
    fn = _handlers.get(name)
    if fn:
        fn(self, context)


def _compute_offset_group_weights(cloth, offset_groups, fitted_indices, vg_membership=None):
    """Return per-vertex weights for each offset group entry.

    Iterates v.groups to avoid try/except-as-flow-control overhead.
    Returns {group_name: {vi: weight}} for all groups with non-zero membership
    in fitted_indices.
    """
    fitted_set = set(fitted_indices)
    offset_group_weights = {}
    for og in offset_groups:
        # Empty string means no group selected.
        og_name = og.group_name.strip() if og.group_name else ""
        if not og_name:
            continue
        vg = cloth.vertex_groups.get(og_name)
        if vg is None:
            continue
        vg_idx  = vg.index
        if vg_membership is not None and vg_idx in vg_membership:
            # Fast-path: weights already stored at build time — zero RNA reads.
            # vg_membership is keyed by fitted vertices only (built in pipeline.py
            # from fitted_set_vg), so no additional fitted_set filter is needed.
            weights = dict(vg_membership[vg_idx])
        else:
            weights = {}
            for v in cloth.data.vertices:
                if v.index not in fitted_set:
                    continue
                for g in v.groups:
                    if g.group == vg_idx and g.weight > 0.0:
                        weights[v.index] = g.weight
                        break
        if weights:
            offset_group_weights[og_name] = weights
    return offset_group_weights
