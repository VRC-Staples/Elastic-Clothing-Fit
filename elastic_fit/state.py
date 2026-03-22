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
    span = max(end - start, 0.0001)

    vi_arr   = np.array(fitted_indices, dtype=np.int32)
    dist_arr = np.fromiter(
        (distances.get(vi, 0.0) for vi in fitted_indices),
        dtype=np.float64,
        count=len(fitted_indices),
    )
    t_arr    = np.clip((dist_arr - start) / span, 0.0, 1.0)

    if curve_key == 'LINEAR':
        w_arr = 1.0 - t_arr
    elif curve_key == 'SMOOTH':
        s = 1.0 - t_arr
        w_arr = s * s * (3.0 - 2.0 * s)
    elif curve_key == 'SHARP':
        w_arr = (1.0 - t_arr) ** 2
    elif curve_key == 'ROOT':
        w_arr = np.sqrt(np.maximum(0.0, 1.0 - t_arr))
    else:
        s = 1.0 - t_arr
        w_arr = s * s * (3.0 - 2.0 * s)  # default: SMOOTH

    w_arr    = np.where(dist_arr <= start, 1.0, np.where(dist_arr >= end, 0.0, w_arr))

    return dict(zip(vi_arr.tolist(), w_arr.tolist()))


def _compute_proximity_group_weights(cloth, proximity_groups, distances, fitted_indices, vg_membership=None):
    """Return {vi: weight} for per-group proximity falloff.

    Each vertex group in proximity_groups applies its own start/end/curve settings
    to the vertices it contains.  Vertices not covered by any group receive weight 1.0
    (no falloff reduction).  When a vertex belongs to multiple groups, the last group
    in the list wins (same deterministic pattern as offset group processing).

    proximity_groups  -- EFitProperties.proximity_groups CollectionProperty
    distances         -- {vi: float} body distances from the fit cache (already computed
                         for the global proximity_mode; per-group mode is not re-run)
    fitted_indices    -- list of vertex indices being fitted
    """
    # Default: every fitted vertex gets full weight.
    result = {vi: 1.0 for vi in fitted_indices}

    if not proximity_groups:
        return result

    fitted_set = _efit_cache.get('fitted_set') or set(fitted_indices)

    for pg in proximity_groups:
        # Empty string means no group selected.
        pg_name = pg.group_name.strip() if pg.group_name else ""
        if not pg_name:
            continue
        vg = cloth.vertex_groups.get(pg_name)
        if vg is None:
            continue
        vg_idx = vg.index

        # Collect fitted vertices that belong to this group.
        if vg_membership is not None and vg_idx in vg_membership:
            group_fitted = [vi for vi in vg_membership[vg_idx] if vi in fitted_set]
        else:
            # Fallback: iterate vertices (used when no cache is available)
            group_fitted = []
            for v in cloth.data.vertices:
                if v.index not in fitted_set:
                    continue
                for g in v.groups:
                    if g.group == vg_idx and g.weight > 0.0:
                        group_fitted.append(v.index)
                        break

        if not group_fitted:
            continue

        # Compute per-group falloff weights and apply (last-wins).
        group_weights = _compute_proximity_weights(
            distances, group_fitted,
            pg.proximity_start, pg.proximity_end, pg.proximity_curve)
        result.update(group_weights)

    return result


def _apply_disp_smoothing(smoothed_arr, fitted_indices, cloth_adj,
                          ds_passes, ds_thresh_mult, ds_min, ds_max,
                          vi_to_pos=None, src_rows=None, dst_rows=None):
    """Apply adaptive multi-pass displacement smoothing on a numpy (N,3) array.

    ``smoothed_arr`` is an ``np.ndarray`` of shape ``(N, 3)`` float64 where
    row ``i`` corresponds to vertex ``fitted_indices[i]``.  The array is NOT
    modified in place — each pass works on a copy.

    Each pass computes a per-vertex displacement gradient (max Euclidean
    distance to edge neighbors).  Vertices above median*threshold are blended
    hard toward the neighbor average (ds_max); those below are blended lightly
    (ds_min).  Fixes creases in concave areas while leaving smooth regions
    untouched.

    ``vi_to_pos``, ``src_rows``, and ``dst_rows`` are topology-derived structures
    that are pure functions of ``fitted_indices`` and ``cloth_adj``.  They are
    static for the entire preview session and should be pre-built once and passed
    in from the cache.  When None (pipeline one-shot path), they are built here.

    Returns an ``np.ndarray (N, 3)`` float64 with smoothed displacements.
    """
    N = len(fitted_indices)

    # Positional index map and COO edge arrays: build only when not supplied.
    # During preview these are pre-built at fit time and cached — zero rebuild
    # cost per slider tick.  On the pipeline one-shot path they are built here.
    if vi_to_pos is None:
        vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}
    if src_rows is None or dst_rows is None:
        # Pre-build COO edge index arrays for vectorised gradient computation.
        # Each undirected edge (i, ni_pos) where ni_pos > i is stored once.
        # np.maximum.at on both src_rows and dst_rows ensures both endpoints
        # get their gradient updated without needing the edge twice.
        _src, _dst = [], []
        for i, vi in enumerate(fitted_indices):
            for ni in cloth_adj[vi]:
                ni_pos = vi_to_pos.get(ni)
                if ni_pos is not None and ni_pos > i:  # each undirected edge once
                    _src.append(i)
                    _dst.append(ni_pos)
        src_rows = np.array(_src, dtype=np.int32)
        dst_rows = np.array(_dst, dtype=np.int32)
    has_edges = len(src_rows) > 0

    # Double-buffer ping-pong: pre-allocate two (N,3) buffers once.
    # Each pass reads from buf_a and writes to buf_b; pointers swap at end of
    # pass so the next pass reads the just-written result.  Zero allocations
    # after setup — no per-pass smoothed_arr.copy().
    buf_a = smoothed_arr.copy()
    buf_b = np.empty_like(buf_a)

    for _pass in range(ds_passes):
        # --- Gradient computation (max distance to any fitted neighbor) ---
        # Vectorised: batch norm over all edges, scatter max to both endpoints.
        gradient = np.zeros(N, dtype=np.float64)
        if has_edges:
            diffs = buf_a[src_rows] - buf_a[dst_rows]
            norms = np.sqrt((diffs ** 2).sum(axis=1))
            np.maximum.at(gradient, src_rows, norms)
            np.maximum.at(gradient, dst_rows, norms)

        # --- Median threshold (np.median replaces statistics.median) ---
        median_grad = float(np.median(gradient))

        # --- Vectorised blend factor computation ---
        threshold = max(median_grad * ds_thresh_mult, 0.0001)
        t = np.clip((gradient - threshold) / max(threshold, 0.0001), 0.0, 1.0)
        blend = np.where(gradient <= threshold,
                         ds_min,
                         ds_min + (ds_max - ds_min) * t)

        # --- Neighbor averaging (inner loop; irregular adjacency prevents
        #     full vectorisation but uses direct array indexing not Vectors) ---
        # Write results into buf_b; buf_a is the read-only source this pass.
        np.copyto(buf_b, buf_a)
        for i, vi in enumerate(fitted_indices):
            neighbors = cloth_adj[vi]
            if not neighbors:
                continue
            neighbor_positions = [vi_to_pos[ni] for ni in neighbors if ni in vi_to_pos]
            if not neighbor_positions:
                continue
            avg = buf_a[neighbor_positions].mean(axis=0)
            buf_b[i] = buf_a[i] * (1.0 - blend[i]) + avg * blend[i]

        # Swap: the written result becomes the source for the next pass.
        buf_a, buf_b = buf_b, buf_a

    # After the last swap, buf_a holds the final smoothed result.
    return buf_a


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


def _smooth_displacements(displacements, fitted_indices, cloth_adj, p,
                          return_array=False):
    """Build a smoothed copy of displacements using current property slider values.

    Wraps the numpy array construction (from the {vi: Vector} input dict),
    the call to ``_apply_disp_smoothing``, and the conversion back to
    ``{vi: Vector}`` so all callers remain unchanged.

    Passes pre-built topology arrays (vi_to_pos, src_rows, dst_rows) from the
    session cache when available — these are static for the preview lifetime and
    are computed once at fit time rather than rebuilt on every slider tick.

    ``return_array=True``: return the raw ``np.ndarray (N, 3)`` float64 instead
    of a ``{vi: Vector}`` dict.  The preview path uses this to avoid N
    ``mathutils.Vector`` allocations per tick; the pipeline one-shot path uses
    the default dict form.

    Returns a new dict {vi: Vector} with smoothed displacements, or an
    ``np.ndarray (N, 3)`` float64 when return_array=True.
    """
    # Build (N, 3) float64 array — row i corresponds to fitted_indices[i].
    # np.fromiter with count= pre-allocates the buffer and streams from the
    # generator with no intermediate Python list (vs np.array([...]) which
    # builds a list first).  Flattened then reshaped to avoid a tuple-of-tuples
    # intermediate (each .to_tuple() returns a 3-float tuple).
    N = len(fitted_indices)
    smoothed_arr = np.fromiter(
        (x for vi in fitted_indices for x in displacements[vi].to_tuple()),
        dtype=np.float64,
        count=N * 3,
    ).reshape(N, 3)
    # Pull pre-built topology from cache (None on pipeline one-shot path —
    # _apply_disp_smoothing will build them locally in that case).
    vi_to_pos = _efit_cache.get('smooth_vi_to_pos')
    src_rows  = _efit_cache.get('smooth_src_rows')
    dst_rows  = _efit_cache.get('smooth_dst_rows')
    result_arr = _apply_disp_smoothing(
        smoothed_arr, fitted_indices, cloth_adj,
        p.disp_smooth_passes, p.disp_smooth_threshold,
        p.disp_smooth_min, p.disp_smooth_max,
        vi_to_pos=vi_to_pos, src_rows=src_rows, dst_rows=dst_rows,
    )
    if return_array:
        return result_arr
    # Convert back to {vi: Vector} — pipeline.py caller unchanged.
    return {vi: mathutils.Vector(result_arr[i]) for i, vi in enumerate(fitted_indices)}


def _compute_offset_group_weights(cloth, offset_groups, fitted_indices, vg_membership=None):
    """Return per-vertex weights for each offset group entry.

    Iterates v.groups to avoid try/except-as-flow-control overhead.
    Returns {group_name: {vi: weight}} for all groups with non-zero membership
    in fitted_indices.
    """
    fitted_set = _efit_cache.get('fitted_set') or set(fitted_indices)
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
