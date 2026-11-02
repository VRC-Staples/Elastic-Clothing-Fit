# Live preview callbacks and Blender mesh/modifier effects.
import time

import bpy

from . import deps, state

# Developer-only timings remain available to the headless benchmark scripts.
_last_tick_timings: "dict | None" = None


def _efit_preview_update(context):
    """Evaluate the prepared fit and write its coordinates to the clothing mesh."""
    global _last_tick_timings
    if state._efit_updating:
        return
    cache = state._efit_cache
    if not cache:
        return
    state._efit_updating = True
    try:
        try:
            from . import panels
            developer_mode = panels._cached_developer_mode
        except Exception:
            developer_mode = False
        if developer_mode:
            total_start = time.perf_counter()
        p = context.scene.efit_props
        cloth = bpy.data.objects.get(cache['cloth_name'])
        if cloth is None:
            return
        prepared = cache['prepared']
        if developer_mode:
            start = time.perf_counter()
        weights = state._get_proximity_weights(cloth, p, prepared)
        if developer_mode:
            proximity_time = time.perf_counter() - start
        coordinates = prepared.evaluate(
            p, proximity_weights=weights,
            batch_tree=deps.BatchKDTree if deps.PYKDTREE_AVAILABLE else None,
            profile=developer_mode)
        if developer_mode:
            start = time.perf_counter()
        cloth.data.vertices.foreach_set('co', coordinates.ravel())
        cloth.data.update()
        if developer_mode:
            _last_tick_timings = dict(prepared.last_timings,
                                     prox=proximity_time,
                                     fset=time.perf_counter() - start,
                                     total=time.perf_counter() - total_start)
            print('[ECF] tick' + ''.join(
                f'  {name}={_last_tick_timings[name] * 1000:.2f}ms'
                for name in ('adj', 'smooth', 'prox', 'cobuf', 'offgrp', 'preserve', 'fset', 'total')))
        if context.screen:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as exc:
        import traceback
        state._efit_last_error = str(exc)
        print(f'[ECF] preview update failed: {exc}')
        traceback.print_exc()
    finally:
        state._efit_updating = False


def _on_tab_change(self, context):
    """Changing tabs does not change fit mode or the active preview."""
    pass


def _on_preview_prop_update(self, context):
    """Refresh the active preview after a fit slider changes."""
    if state._efit_cache:
        _efit_preview_update(context)


def _sync_preview_modifiers(cloth, p, has_preserve, preserve_name):
    """Match the live smoothing modifiers to the current property values."""
    m_cs = cloth.modifiers.get(f'{state.EFIT_PREFIX}Smooth')
    if p.smooth_iterations > 0:
        if m_cs is None:
            m_cs = cloth.modifiers.new(f'{state.EFIT_PREFIX}Smooth', 'CORRECTIVE_SMOOTH')
            m_cs.smooth_type = 'SIMPLE'
            m_cs.use_only_smooth = False
            if has_preserve and preserve_name:
                m_cs.vertex_group = preserve_name
                m_cs.invert_vertex_group = True
        m_cs.factor = p.smooth_factor
        m_cs.iterations = p.smooth_iterations
    elif m_cs is not None:
        cloth.modifiers.remove(m_cs)
    m_lap = cloth.modifiers.get(f'{state.EFIT_PREFIX}Laplacian')
    if p.post_laplacian:
        if m_lap is None:
            m_lap = cloth.modifiers.new(f'{state.EFIT_PREFIX}Laplacian', 'LAPLACIANSMOOTH')
            m_lap.lambda_border = 0.0
            m_lap.use_volume_preserve = True
            m_lap.use_normalized = True
            if has_preserve and preserve_name:
                m_lap.vertex_group = preserve_name
                m_lap.invert_vertex_group = True
        m_lap.lambda_factor = p.laplacian_factor
        m_lap.iterations = p.laplacian_iterations
    elif m_lap is not None:
        cloth.modifiers.remove(m_lap)


def _on_smooth_mod_update(self, context):
    """Sync the live modifiers after a smoothing property changes."""
    if not state._efit_cache:
        return
    cloth = bpy.data.objects.get(state._efit_cache.get('cloth_name', ''))
    if cloth is None:
        return
    _sync_preview_modifiers(cloth, context.scene.efit_props,
                            state._efit_cache.get('has_preserve', False),
                            state._efit_cache.get('preserve_name', ''))
    if context.screen:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _on_offset_group_influence_update(self, context):
    """Refresh the preview after an offset influence changes."""
    if state._efit_cache:
        _efit_preview_update(context)


def _on_offset_group_name_update(self, context):
    """Refresh group membership and offset weights after a group name changes."""
    if not state._efit_cache:
        return
    cloth = bpy.data.objects.get(state._efit_cache.get('cloth_name', ''))
    if cloth is None:
        return
    prepared = state._efit_cache['prepared']
    membership = {}
    for vertex in cloth.data.vertices:
        if vertex.index not in prepared.fitted_set:
            continue
        for group in vertex.groups:
            if group.weight > 0.0:
                membership.setdefault(group.group, {})[vertex.index] = group.weight
    prepared.vg_membership = membership
    prepared.set_offset_weights(state._compute_offset_group_weights(
        cloth, context.scene.efit_props.offset_groups, prepared.fitted_indices,
        vg_membership=membership))
    _efit_preview_update(context)


def _on_proximity_group_prop_update(self, context):
    """Invalidate this session's weights after a proximity property changes."""
    if state._efit_cache:
        state._efit_cache['prepared'].proximity_key = None
        _efit_preview_update(context)


def _on_proximity_group_name_update(self, context):
    """Invalidate this session's weights after a proximity group name changes."""
    if state._efit_cache:
        state._efit_cache['prepared'].proximity_key = None
        _efit_preview_update(context)
