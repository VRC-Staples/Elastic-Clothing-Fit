# preview.py
# Live preview engine: reapplies the cached fit result whenever a slider changes.
# Also owns the property update callbacks and modifier sync helpers that are
# referenced by EFitOffsetGroup and EFitProperties in properties.py.

import numpy as np
import mathutils
from mathutils.kdtree import KDTree

import bpy

from . import state


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
        p = context.scene.efit_props
        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            return
        all_originals        = c['all_originals']
        cloth_displacements  = c['cloth_displacements']
        cloth_adj            = c['cloth_adj']
        fitted_indices       = c['fitted_indices']
        preserved_indices    = c['preserved_indices']
        has_preserve         = c['has_preserve']
        fit                  = p.fit_amount

        # Adjust each displacement along the cached body-surface normal by the
        # difference between the current offset and the offset baked into the
        # cache, so the preview stays live without re-running shrinkwrap.
        offset_delta      = p.offset - c.get('original_offset', p.offset)
        cloth_body_normals = c.get('cloth_body_normals', {})

        adjusted_displacements = {}
        for vi in fitted_indices:
            d = cloth_displacements[vi].copy()
            if offset_delta != 0.0 and vi in cloth_body_normals:
                d += cloth_body_normals[vi] * offset_delta
            adjusted_displacements[vi] = d

        # Re-run adaptive displacement smoothing with the current slider values.
        smoothed = {vi: adjusted_displacements[vi].copy() for vi in fitted_indices}

        ds_passes      = p.disp_smooth_passes
        ds_thresh_mult = p.disp_smooth_threshold
        ds_min         = p.disp_smooth_min
        ds_max         = p.disp_smooth_max

        smoothed = state._apply_disp_smoothing(
            smoothed, fitted_indices, cloth_adj,
            ds_passes, ds_thresh_mult, ds_min, ds_max)

        # Recompute proximity weights from cached distances so slider changes update live.
        proximity_weights = None
        if p.use_proximity_falloff:
            cloth_body_distances = c.get('cloth_body_distances', {})
            if cloth_body_distances:
                proximity_weights = state._compute_proximity_weights(
                    cloth_body_distances, fitted_indices,
                    p.proximity_start, p.proximity_end, p.proximity_curve)
        c['proximity_weights'] = proximity_weights

        # Build co_buf with smoothed positions; deferred foreach_set covers smoothing,
        # offset tuning, and preserve-follow in a single write at the end.
        n_verts = len(cloth.data.vertices)
        co_buf  = np.empty(n_verts * 3, dtype=np.float64)
        cloth.data.vertices.foreach_get("co", co_buf)
        for vi in fitted_indices:
            pw     = proximity_weights[vi] if proximity_weights else 1.0
            result = all_originals[vi] + smoothed[vi] * fit * pw
            base   = vi * 3
            co_buf[base]     = result.x
            co_buf[base + 1] = result.y
            co_buf[base + 2] = result.z

        # Snapshot pre-offset positions from the buffer -- co_buf already holds the
        # smoothed result so no additional mesh read is needed.
        offset_group_weights = c.get('offset_group_weights', {})
        original_offset = c.get('original_offset', 0.0)
        source_groups = p.exclusive_groups if p.fit_mode == 'EXCLUSIVE' else p.offset_groups
        has_offset_work = bool(offset_group_weights and original_offset != 0.0)
        needs_preserve  = has_preserve and preserved_indices and p.follow_strength > 0.0
        if has_offset_work or needs_preserve:
            pre_offset_positions = {
                vi: mathutils.Vector(co_buf[vi*3:vi*3+3]) for vi in fitted_indices
            }
        else:
            pre_offset_positions = {}

        # Accumulate offset group deltas directly into co_buf (P3).
        if has_offset_work:
            for og in source_groups:
                if not og.group_name:
                    continue
                weights = offset_group_weights.get(og.group_name)
                if not weights:
                    continue
                # 0% => -1 (no offset), 100% => 0 (neutral), 200% => +1 (double)
                mult_delta = og.influence / 100.0 - 1.0
                if abs(mult_delta) < 0.0001:
                    continue
                for vi, w in weights.items():
                    if vi in cloth_body_normals:
                        n     = cloth_body_normals[vi]
                        delta = original_offset * mult_delta * w
                        base  = vi * 3
                        co_buf[base]     += n.x * delta
                        co_buf[base + 1] += n.y * delta
                        co_buf[base + 2] += n.z * delta

        # Accumulate preserve-follow writes into co_buf (P1).
        if has_preserve and preserved_indices and fitted_indices:
            strength = p.follow_strength
            if strength > 0.0:
                current_positions = pre_offset_positions

                # Lazily build and cache the KDTree on first preview call.
                # Rest-pose positions are used so neighbor selection stays stable
                # as the mesh deforms across slider changes.
                kd_follow = c.get('kd_follow')
                if kd_follow is None:
                    kd_follow = KDTree(len(fitted_indices))
                    for i, vi in enumerate(fitted_indices):
                        kd_follow.insert(all_originals[vi], i)
                    kd_follow.balance()
                    c['kd_follow'] = kd_follow

                K_follow = min(p.follow_neighbors, len(fitted_indices))
                for vi in preserved_indices:
                    rest_pos  = all_originals[vi]
                    neighbors = kd_follow.find_n(rest_pos, K_follow)
                    total_disp   = mathutils.Vector((0.0, 0.0, 0.0))
                    total_weight = 0.0
                    for _co, idx, dist in neighbors:
                        ni    = fitted_indices[idx]
                        disp  = current_positions[ni] - all_originals[ni]
                        w     = 1.0 / max(dist, 0.0001)
                        total_disp   += disp * w
                        total_weight += w
                    if total_weight > 0.0:
                        avg_disp = total_disp / total_weight
                        res  = rest_pos + avg_disp * strength
                        base = vi * 3
                        co_buf[base]     = res.x
                        co_buf[base + 1] = res.y
                        co_buf[base + 2] = res.z

        cloth.data.vertices.foreach_set("co", co_buf)
        cloth.data.update()
        if context.screen:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        state._efit_updating = False


def _on_tab_change(self, context):
    """Sync fit_mode when the user switches UI tabs."""
    if state._efit_updating:
        return
    state._efit_updating = True
    try:
        if self.ui_tab == 'FULL':
            self.fit_mode = 'FULL'
        elif self.ui_tab == 'EXCLUSIVE':
            self.fit_mode = 'EXCLUSIVE'
    finally:
        state._efit_updating = False


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
    state._efit_cache['offset_group_weights'] = state._compute_offset_group_weights(
        cloth, p.offset_groups, fitted_indices)
    _efit_preview_update(context)
