# preview.py
# Live preview engine: reapplies the cached fit result whenever a slider changes.
# Also owns the property update callbacks and modifier sync helpers that are
# referenced by EFitOffsetGroup and EFitProperties in properties.py.

import time

import numpy as np
import mathutils
from mathutils.kdtree import KDTree

import bpy

from . import state
from .properties import _resolve_vg_name


def _efit_preview_update(context):
    """Reapply the cached fit to the clothing mesh using current slider values.

    Reads cloth_displacements from the cache, adjusts for the current offset
    delta and fit_amount, re-runs adaptive displacement smoothing, applies
    offset fine-tuning, then moves preserved vertices via inverse-distance
    weighted neighbor lookup.  Skips silently if no cache is active or if
    a recursive call is detected via state._efit_updating.
    """
    if state._efit_updating:
        return
    c = state._efit_cache
    if not c:
        return

    state._efit_updating = True
    try:
        # --- Profiling: resolve developer mode via deferred import ---
        try:
            from . import panels as _panels
            _dev_mode = _panels._cached_developer_mode
        except Exception:
            _dev_mode = False

        _t_adj = _t_smooth = _t_prox = _t_cobuf = _t_offgrp = _t_preserve = _t_fset = 0.0
        if _dev_mode:
            _t_total_start = time.perf_counter()

        p = context.scene.efit_props
        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            return
        all_originals        = c['all_originals']   # np.ndarray (N_total, 3)
        cloth_displacements  = c['cloth_displacements']
        cloth_adj            = c['cloth_adj']
        fitted_indices       = c['fitted_indices']
        preserved_indices    = c['preserved_indices']
        has_preserve         = c['has_preserve']
        fit                  = p.fit_amount

        # Adjust each displacement along the cached body-surface normal by the
        # difference between the current offset and the offset baked into the
        # cache, so the preview stays live without re-running shrinkwrap.
        offset_delta       = p.offset - c.get('original_offset', p.offset)
        cloth_body_normals = c.get('cloth_body_normals', {})

        if _dev_mode:
            _t0 = time.perf_counter()
        if offset_delta != 0.0:
            adjusted = cloth_displacements + cloth_body_normals * offset_delta
        else:
            adjusted = cloth_displacements
        if _dev_mode:
            _t_adj = time.perf_counter() - _t0

        # Re-run adaptive displacement smoothing with the current slider values.
        # return_array=True: get raw (N_fitted, 3) ndarray — avoids N Vector
        # allocations in _smooth_displacements and N more in the write loop below.
        if _dev_mode:
            _t0 = time.perf_counter()
        smoothed_arr = state._smooth_displacements(
            adjusted, fitted_indices, cloth_adj, p,
            return_array=True)
        if _dev_mode:
            _t_smooth = time.perf_counter() - _t0

        # --- Fix C: proximity weights ---
        # Proximity weights are a pure function of body distances (static) and
        # the proximity slider values.  Cache a shadow of those values and skip
        # recomputation when nothing proximity-related has changed.
        if _dev_mode:
            _t0 = time.perf_counter()
        proximity_weights = None
        if p.use_proximity_falloff:
            cloth_body_distances = c.get('cloth_body_distances', {})
            if cloth_body_distances:
                # Build a key from the current proximity slider values.
                _use_pg = p.use_proximity_group_tuning and len(p.proximity_groups) > 0
                _prox_key = (
                    _use_pg,
                    p.proximity_start, p.proximity_end, p.proximity_curve,
                )
                if c.get('_prox_key') == _prox_key and c.get('proximity_weights') is not None:
                    # Inputs unchanged — reuse cached weights.
                    proximity_weights = c['proximity_weights']
                else:
                    if _use_pg:
                        proximity_weights = state._compute_proximity_group_weights(
                            cloth, p.proximity_groups, cloth_body_distances, fitted_indices,
                            vg_membership=c.get('vg_membership'))
                    else:
                        proximity_weights = state._compute_proximity_weights(
                            cloth_body_distances, fitted_indices,
                            p.proximity_start, p.proximity_end, p.proximity_curve)
                    c['proximity_weights'] = proximity_weights
                    c['_prox_key'] = _prox_key
        if _dev_mode:
            _t_prox = time.perf_counter() - _t0

        # --- Fix A + Fix B: build co_buf without reading the mesh ---
        # all_originals is an np.ndarray (N_total, 3).  We write only fitted
        # (and later preserved) vertex positions — non-fitted verts are never
        # touched, so there is no need to read the whole mesh first.
        # smoothed_arr is already an (N_fitted, 3) ndarray; index it by position.
        if _dev_mode:
            _t0 = time.perf_counter()
        n_verts   = len(cloth.data.vertices)
        co_buf    = np.empty(n_verts * 3, dtype=np.float64)
        fi_arr    = np.array(fitted_indices, dtype=np.int32)

        # Vectorised write: all_originals[fi_arr] is (N_fitted, 3); smoothed_arr
        # rows align by position with fitted_indices.
        if proximity_weights is not None:
            pw_arr = np.fromiter(
                (proximity_weights[vi] for vi in fitted_indices),
                dtype=np.float64, count=len(fitted_indices))
            fitted_pos = all_originals[fi_arr] + smoothed_arr * (fit * pw_arr[:, None])
        else:
            fitted_pos = all_originals[fi_arr] + smoothed_arr * fit

        # Scatter fitted positions into co_buf using COO-style index assignment.
        # fi_arr gives the vertex indices; multiply by 3 for the flat buffer offset.
        base_arr = fi_arr * 3
        co_buf[base_arr]     = fitted_pos[:, 0]
        co_buf[base_arr + 1] = fitted_pos[:, 1]
        co_buf[base_arr + 2] = fitted_pos[:, 2]

        # Non-fitted vertices: read their current positions from all_originals so
        # the foreach_set has valid data everywhere (they are never deformed here).
        # Build a mask and fill in one vectorised pass.
        fitted_mask = np.zeros(n_verts, dtype=bool)
        fitted_mask[fi_arr] = True
        non_fitted = np.where(~fitted_mask)[0].astype(np.int32)
        if len(non_fitted):
            nf_base = non_fitted * 3
            nf_pos  = all_originals[non_fitted]
            co_buf[nf_base]     = nf_pos[:, 0]
            co_buf[nf_base + 1] = nf_pos[:, 1]
            co_buf[nf_base + 2] = nf_pos[:, 2]
        if _dev_mode:
            _t_cobuf = time.perf_counter() - _t0

        # Snapshot pre-offset positions from fitted_pos (already in memory).
        offset_group_weights = c.get('offset_group_weights', {})
        original_offset = c.get('original_offset', 0.0)
        source_groups = p.exclusive_groups if p.fit_mode == 'EXCLUSIVE' else p.offset_groups
        has_offset_work = bool(offset_group_weights and original_offset != 0.0)
        needs_preserve  = has_preserve and preserved_indices and p.follow_strength > 0.0
        if has_offset_work or needs_preserve:
            # fitted_pos rows align with fitted_indices by position — use directly.
            pre_offset_positions = fitted_pos
        else:
            pre_offset_positions = None

        # Accumulate offset group deltas directly into co_buf.
        if _dev_mode:
            _t0 = time.perf_counter()
        if has_offset_work:
            vi_to_pos = c.get('smooth_vi_to_pos', {})
            for og in source_groups:
                og_name = _resolve_vg_name(og.group_name)
                if not og_name:
                    continue
                weights = offset_group_weights.get(og_name)
                if not weights:
                    continue
                # 0% => -1 (no offset), 100% => 0 (neutral), 200% => +1 (double)
                mult_delta = og.influence / 100.0 - 1.0
                if abs(mult_delta) < 0.0001:
                    continue
                for vi, w in weights.items():
                    pos = vi_to_pos.get(vi)
                    if pos is not None:
                        n     = cloth_body_normals[pos]
                        delta = original_offset * mult_delta * w
                        base  = vi * 3
                        co_buf[base]     += n[0] * delta
                        co_buf[base + 1] += n[1] * delta
                        co_buf[base + 2] += n[2] * delta
        if _dev_mode:
            _t_offgrp = time.perf_counter() - _t0

        # Preserve-follow: move preserved vertices to follow nearby fitted areas.
        # Guard uses needs_preserve so follow_strength=0 skips entirely.
        if _dev_mode:
            _t0 = time.perf_counter()
        if needs_preserve and fitted_indices:
            # Lazily build and cache the KDTree on first preview call.
            kd_follow = c.get('kd_follow')
            if kd_follow is None:
                kd_follow = KDTree(len(fitted_indices))
                for i, vi in enumerate(fitted_indices):
                    kd_follow.insert(all_originals[vi], i)
                kd_follow.balance()
                c['kd_follow'] = kd_follow

            strength = p.follow_strength
            K_follow = min(p.follow_neighbors, len(fitted_indices))
            current_positions = pre_offset_positions  # ndarray (N_fitted, 3)
            for vi in preserved_indices:
                rest = all_originals[vi]
                neighbors = kd_follow.find_n(mathutils.Vector(rest), K_follow)
                tx = ty = tz = 0.0
                total_weight = 0.0
                for _co, idx, dist in neighbors:
                    # idx is the positional index in fitted_indices; use directly.
                    cp = current_positions[idx]  # numpy (3,) row
                    ni = fitted_indices[idx]
                    ao = all_originals[ni]        # numpy (3,) row
                    w  = 1.0 / max(dist, 0.0001)
                    tx += (cp[0] - ao[0]) * w
                    ty += (cp[1] - ao[1]) * w
                    tz += (cp[2] - ao[2]) * w
                    total_weight += w
                if total_weight > 0.0:
                    base = vi * 3
                    co_buf[base]     = rest[0] + (tx / total_weight) * strength
                    co_buf[base + 1] = rest[1] + (ty / total_weight) * strength
                    co_buf[base + 2] = rest[2] + (tz / total_weight) * strength
        if _dev_mode:
            _t_preserve = time.perf_counter() - _t0

        if _dev_mode:
            _t0 = time.perf_counter()
        cloth.data.vertices.foreach_set("co", co_buf)
        cloth.data.update()
        if _dev_mode:
            _t_fset = time.perf_counter() - _t0

        if _dev_mode:
            _t_total = time.perf_counter() - _t_total_start
            print(
                f"[ECF] tick"
                f"  adj={_t_adj*1000:.2f}ms"
                f"  smooth={_t_smooth*1000:.2f}ms"
                f"  prox={_t_prox*1000:.2f}ms"
                f"  cobuf={_t_cobuf*1000:.2f}ms"
                f"  offgrp={_t_offgrp*1000:.2f}ms"
                f"  preserve={_t_preserve*1000:.2f}ms"
                f"  fset={_t_fset*1000:.2f}ms"
                f"  TOTAL={_t_total*1000:.2f}ms"
            )

        if context.screen:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as exc:
        import traceback
        state._efit_last_error = str(exc)
        print(f"[ECF] preview update failed: {exc}")
        traceback.print_exc()
    finally:
        state._efit_updating = False


def _on_tab_change(self, context):
    """Called when the user switches UI tabs.

    Previously this synced fit_mode to the tab, but fit_mode is now exclusively
    controlled by the use_exclusive_mode toggle (_on_exclusive_mode_toggle in
    properties.py). Switching tabs must never alter fit_mode or use_exclusive_mode.
    This handler is kept for future tab-change side-effects (e.g. cancelling an
    in-progress preview when leaving the Fit tab).
    """
    pass


def _on_preview_prop_update(self, context):
    """Property update callback: triggers a live preview refresh when any fit
    slider changes while a preview is active."""
    if state._efit_cache:
        _efit_preview_update(context)


def _sync_preview_modifiers(cloth, p, has_preserve, preserve_name):
    """Add, update, or remove the EFit_ corrective-smooth and laplacian-smooth
    modifiers on cloth to match the current property values.

    Called once when a fit starts and again whenever the smoothing sliders change.
    """
    # Corrective Smooth modifier
    m_cs = cloth.modifiers.get(f"{state.EFIT_PREFIX}Smooth")
    if p.smooth_iterations > 0:
        if m_cs is None:
            m_cs = cloth.modifiers.new(f"{state.EFIT_PREFIX}Smooth", 'CORRECTIVE_SMOOTH')
            m_cs.smooth_type = 'SIMPLE'
            m_cs.use_only_smooth = False
            if has_preserve and preserve_name:
                m_cs.vertex_group = preserve_name
                m_cs.invert_vertex_group = True
        m_cs.factor     = p.smooth_factor
        m_cs.iterations = p.smooth_iterations
    else:
        if m_cs is not None:
            cloth.modifiers.remove(m_cs)

    # Laplacian Smooth modifier
    m_lap = cloth.modifiers.get(f"{state.EFIT_PREFIX}Laplacian")
    if p.post_laplacian:
        if m_lap is None:
            m_lap = cloth.modifiers.new(f"{state.EFIT_PREFIX}Laplacian", 'LAPLACIANSMOOTH')
            m_lap.lambda_border  = 0.0
            m_lap.use_volume_preserve = True
            m_lap.use_normalized = True
            if has_preserve and preserve_name:
                m_lap.vertex_group = preserve_name
                m_lap.invert_vertex_group = True
        m_lap.lambda_factor = p.laplacian_factor
        m_lap.iterations    = p.laplacian_iterations
    else:
        if m_lap is not None:
            cloth.modifiers.remove(m_lap)


def _on_smooth_mod_update(self, context):
    """Property update callback: syncs the live preview smooth modifiers whenever
    smooth_factor, smooth_iterations, post_laplacian, or laplacian sliders change."""
    if not state._efit_cache:
        return
    cloth = bpy.data.objects.get(state._efit_cache.get('cloth_name', ''))
    if cloth is None:
        return
    p = context.scene.efit_props
    _sync_preview_modifiers(
        cloth, p,
        state._efit_cache.get('has_preserve', False),
        state._efit_cache.get('preserve_name', ''),
    )
    if context.screen:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _on_offset_group_influence_update(self, context):
    """Property update callback: refreshes the preview when an offset group
    influence slider changes."""
    if state._efit_cache:
        _efit_preview_update(context)


def _on_offset_group_name_update(self, context):
    """Property update callback: recomputes the cached per-vertex offset weights
    for all offset groups, then refreshes the preview.  Called when the user
    changes which vertex group an offset entry points to."""
    if not state._efit_cache:
        return
    cloth = bpy.data.objects.get(state._efit_cache.get('cloth_name', ''))
    if cloth is None:
        return
    fitted_indices = state._efit_cache.get('fitted_indices', [])
    p = context.scene.efit_props
    # Build VG membership inline (non-hot-path: only fires on group name change).
    # {vg_idx: {vi: weight}} — weight stored at build time for offset group fast-path.
    fitted_set = state._efit_cache.get('fitted_set') or set(fitted_indices)
    vg_membership = {}
    for v in cloth.data.vertices:
        if v.index not in fitted_set:
            continue
        for g in v.groups:
            if g.weight > 0.0:
                vg_membership.setdefault(g.group, {})[v.index] = g.weight
    state._efit_cache['vg_membership'] = vg_membership
    state._efit_cache['offset_group_weights'] = state._compute_offset_group_weights(
        cloth, p.offset_groups, fitted_indices, vg_membership=vg_membership)
    _efit_preview_update(context)


def _on_proximity_group_prop_update(self, context):
    """Property update callback: refreshes the preview when any per-group proximity
    slider (mode, start, end, curve) changes."""
    if state._efit_cache:
        # Bust the proximity weight cache so the next tick recomputes.
        state._efit_cache.pop('_prox_key', None)
        _efit_preview_update(context)


def _on_proximity_group_name_update(self, context):
    """Property update callback: refreshes the preview when a proximity group's
    vertex group selection changes.  Weight recomputation happens inside
    _efit_preview_update via the per-group path."""
    if state._efit_cache:
        # Bust the proximity weight cache so the next tick recomputes.
        state._efit_cache.pop('_prox_key', None)
        _efit_preview_update(context)
