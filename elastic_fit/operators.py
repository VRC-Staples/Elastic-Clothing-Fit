# operators.py
# All Blender operators for Elastic Clothing Fit.
# Pipeline helpers (proxy creation, shrinkwrap, BVH displacement transfer,
# adaptive smoothing, offset fine-tuning, preserve follow) live in pipeline.py.

import numpy as np
import mathutils

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from . import state
from . import updater
from .state import (
    EFIT_PREFIX,
    _has_blockers,
    _save_uvs, _restore_uvs, _remove_efit,
)
from .properties import _resolve_vg_name
from .preview import _efit_preview_update, _sync_preview_modifiers
from .pipeline import (
    _efit_save_originals, _efit_create_proxy, _efit_classify_vertices,
    _efit_shrinkwrap_proxy, _efit_transfer_displacements, _efit_apply_smoothing,
    _efit_apply_offset_tuning, _efit_apply_preserve_follow,
    _efit_create_hull_proxy,
)


class EFIT_OT_fit(Operator):
    bl_idname = "efit.fit"
    bl_label = "Fit Clothing"
    bl_description = "Fit the clothing to the body mesh with a smooth, elastic result"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = context.scene.efit_props
        if (p.clothing_obj is None
                or p.body_obj is None
                or p.clothing_obj == p.body_obj
                or state._efit_cache):
            return False
        if p.fit_mode == 'EXCLUSIVE':
            cloth = p.clothing_obj
            has_valid = any(
                _resolve_vg_name(eg.group_name) and cloth.vertex_groups.get(_resolve_vg_name(eg.group_name))
                for eg in p.exclusive_groups
            )
            if not has_valid:
                cls.poll_message_set(
                    "Add at least one vertex group to 'Groups to Fit' "
                    "(under Advanced Settings) before fitting."
                )
                return False
        return True

    def execute(self, context):
        p     = context.scene.efit_props
        cloth = p.clothing_obj
        body  = p.body_obj

        # Expand the relevant settings panels so the user can review what was applied.
        p.show_advanced      = True
        p.show_fit_settings  = True

        # -- Validation --
        if not cloth or cloth.type != 'MESH':
            self.report({'ERROR'}, "Select a valid clothing mesh.")
            return {'CANCELLED'}
        if not body or body.type != 'MESH':
            self.report({'ERROR'}, "Select a valid body mesh.")
            return {'CANCELLED'}
        if cloth == body:
            self.report({'ERROR'}, "Clothing and body must be different objects.")
            return {'CANCELLED'}
        if cloth.name not in context.view_layer.objects:
            self.report({'ERROR'},
                        f"'{cloth.name}' is not in the active View Layer. "
                        "Check that its collection is not excluded.")
            return {'CANCELLED'}
        if body.name not in context.view_layer.objects:
            self.report({'ERROR'},
                        f"'{body.name}' is not in the active View Layer. "
                        "Check that its collection is not excluded.")
            return {'CANCELLED'}

        has_sk, blocker_mods = _has_blockers(cloth)
        if has_sk:
            self.report({'ERROR'},
                        "Clothing has shape keys. Use 'Clear Blockers' to remove them first.")
            return {'CANCELLED'}
        if blocker_mods:
            self.report({'ERROR'},
                        f"Clothing has unapplied modifiers: {', '.join(blocker_mods)}. "
                        "Use 'Clear Blockers' to remove them first.")
            return {'CANCELLED'}

        if p.fit_mode == 'EXCLUSIVE':
            valid_groups = [eg for eg in p.exclusive_groups
                            if _resolve_vg_name(eg.group_name) and cloth.vertex_groups.get(_resolve_vg_name(eg.group_name))]
            if not valid_groups:
                self.report({'ERROR'},
                            "Exclusive Vertex Group Fit requires at least one group in the "
                            "'Groups to Fit' list. Add a vertex group under Advanced Settings.")
                return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Clear any active preview before starting a new fit.
        state._efit_cache.clear()

        if p.cleanup:
            # Remove any leftover EFit_ modifiers and the stale originals without
            # restoring vertex positions. Position restore is only correct for
            # Cancel/Remove Fit; starting a new fit should always begin from
            # whatever positions the mesh is currently in.
            for m in [m for m in cloth.modifiers if m.name.startswith(EFIT_PREFIX)]:
                cloth.modifiers.remove(m)
            if "_efit_originals" in cloth:
                del cloth["_efit_originals"]
            state._efit_originals.pop(cloth.name, None)
            for obj in list(bpy.data.objects):
                if obj.name.startswith(EFIT_PREFIX) and obj.type == 'MESH':
                    bpy.data.objects.remove(obj, do_unlink=True)

        # Resolve preserve group: check that the named vertex group actually exists.
        preserve_name = _resolve_vg_name(p.preserve_group)
        has_preserve  = bool(preserve_name and cloth.vertex_groups.get(preserve_name))

        if preserve_name and not cloth.vertex_groups.get(preserve_name):
            self.report({'WARNING'},
                        f"Preserve group '{preserve_name}' not found, skipping.")

        # -- Save originals --
        all_originals, undo_flat = _efit_save_originals(cloth)
        cloth["_efit_originals"] = undo_flat
        state._efit_originals[cloth.name] = undo_flat

        saved_uvs = _save_uvs(cloth.data) if p.preserve_uvs else None

        # -- Create and subdivide the proxy mesh --
        proxy, actual_tris, subdiv_levels = _efit_create_proxy(context, cloth, p)
        if proxy is None:
            self.report({'ERROR'}, "Could not create proxy mesh.")
            return {'CANCELLED'}

        # -- Classify preserved vs fitted vertices --
        fitted_indices, preserved_indices, has_preserve, preserve_name = \
            _efit_classify_vertices(cloth, p, has_preserve, preserve_name)

        # Cache the fitted set immediately — pipeline and state helpers read it
        # back from the cache instead of rebuilding set(fitted_indices) each call.
        state._efit_cache['fitted_set'] = set(fitted_indices)

        # -- Optional: build a convex-hull proxy of the body as the shrinkwrap target.
        # The hull fills concave regions (crotch, inner thigh) so the shrinkwrap
        # cannot pull clothing vertices into cavities between legs. Disabled by
        # default -- enable via the use_proxy_hull toggle in Fit Settings.
        if p.use_proxy_hull:
            hull_body = _efit_create_hull_proxy(context, body)
            if hull_body is None:
                self.report({'WARNING'}, "Could not create hull proxy, fitting against body directly.")
                hull_body = body
        else:
            hull_body = body

        # -- Shrinkwrap proxy onto body (or hull body) --
        proxy_pre, proxy_post = _efit_shrinkwrap_proxy(
            context, proxy, hull_body, all_originals,
            fitted_indices, preserved_indices, has_preserve, p)

        # Remove hull proxy immediately after shrinkwrap -- it is not needed downstream.
        if p.use_proxy_hull and hull_body is not body:
            bpy.data.objects.remove(hull_body, do_unlink=True)
            hull_body = None

        # -- Transfer displacement via BVH surface interpolation --
        source_groups = p.exclusive_groups if p.fit_mode == 'EXCLUSIVE' else p.offset_groups
        cloth_displacements, cloth_body_normals, cloth_body_distances, offset_group_weights, cloth_adj, vg_membership, _proxy_bvh = \
            _efit_transfer_displacements(
                cloth, proxy, proxy_pre, proxy_post, body, fitted_indices, source_groups)

        bpy.data.objects.remove(proxy, do_unlink=True)

        # -- Proximity falloff weights (between steps 5 and 6) --
        proximity_weights = None
        if p.use_proximity_falloff:
            if p.use_proximity_group_tuning and len(p.proximity_groups) > 0:
                proximity_weights = state._compute_proximity_group_weights(
                    cloth, p.proximity_groups, cloth_body_distances, fitted_indices,
                    vg_membership=vg_membership)
            else:
                proximity_weights = state._compute_proximity_weights(
                    cloth_body_distances, fitted_indices,
                    p.proximity_start, p.proximity_end, p.proximity_curve)

        # -- Adaptive displacement smoothing --
        _efit_apply_smoothing(
            cloth, all_originals, cloth_displacements,
            cloth_adj, fitted_indices, p.fit_amount, p,
            proximity_weights=proximity_weights)

        if saved_uvs:
            _restore_uvs(cloth.data, saved_uvs)

        # Save each fitted vertex's position before any offset fine-tuning is applied.
        # The preserve group follow step reads from these saved positions, so offset
        # adjustments on fitted areas cannot unintentionally move nearby preserved vertices.
        # Only snapshot when needed -- skips an expensive per-vertex copy for users
        # with no preserve group and no offset groups.
        needs_pre_pos = bool(offset_group_weights) or (has_preserve and preserved_indices)
        if needs_pre_pos:
            _n    = len(cloth.data.vertices)
            _snap = np.empty(_n * 3, dtype=np.float64)
            cloth.data.vertices.foreach_get("co", _snap)
            _snap_3 = _snap.reshape(-1, 3)
            _fi_arr = np.array(fitted_indices, dtype=np.int32)
            _pos_arr = _snap_3[_fi_arr]
            pre_offset_positions = {vi: _pos_arr[i] for i, vi in enumerate(fitted_indices)}
        else:
            pre_offset_positions = {}

        # -- Offset fine-tuning --
        if offset_group_weights:
            _efit_apply_offset_tuning(
                cloth, cloth_body_normals, offset_group_weights, source_groups, p)

        # -- Move preserved vertices to follow nearby fitted areas --
        if has_preserve and preserved_indices and fitted_indices:
            _efit_apply_preserve_follow(
                cloth, all_originals, fitted_indices,
                preserved_indices, pre_offset_positions, p)

        # -- Populate preview cache (slider changes will re-apply from here) --
        # Preserve fitted_set and KDTree entries that were written earlier in this
        # execute() call — they are valid for the full preview lifetime and must
        # survive the dict-replace below.
        _kd_preserve = state._efit_cache.get('kd_preserve')
        _kd_fitted   = state._efit_cache.get('kd_fitted')
        _kd_follow   = state._efit_cache.get('kd_follow')
        _fitted_set  = state._efit_cache.get('fitted_set', set(fitted_indices))
        state._efit_cache = {
            'cloth_name':           cloth.name,
            'all_originals':        all_originals,
            'cloth_displacements':  cloth_displacements,
            'cloth_adj':            cloth_adj,
            'fitted_indices':       fitted_indices,
            'fitted_set':           _fitted_set,
            'preserved_indices':    preserved_indices,
            'has_preserve':         has_preserve,
            'preserve_name':        preserve_name,
            'saved_uvs':            saved_uvs,
            'cloth_body_normals':   cloth_body_normals,
            'cloth_body_distances': cloth_body_distances,
            'proximity_weights':    proximity_weights,
            'original_offset':      p.offset,
            'offset_group_weights': offset_group_weights,
            'vg_membership':        vg_membership,
        }
        if _kd_preserve is not None:
            state._efit_cache['kd_preserve'] = _kd_preserve
        if _kd_fitted is not None:
            state._efit_cache['kd_fitted'] = _kd_fitted
        if _kd_follow is not None:
            state._efit_cache['kd_follow'] = _kd_follow

        # Reselect clothing.
        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        # Add live preview modifiers so smoothing is visible immediately.
        _sync_preview_modifiers(cloth, p, has_preserve, preserve_name)

        self.report({'INFO'},
                    f"Preview ready. Adjust sliders, then Apply or Cancel. "
                    f"({actual_tris:,} tris, {subdiv_levels} subdivision levels)")
        return {'FINISHED'}


class EFIT_OT_preview_apply(Operator):
    """Accept the current preview and finalize the fit."""
    bl_idname      = "efit.preview_apply"
    bl_label       = "Apply Fit"
    bl_description = "Accept the current fit and apply any post-processing options"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(state._efit_cache)

    def execute(self, context):
        c = state._efit_cache
        if not c:
            self.report({'WARNING'}, "No preview to apply.")
            return {'CANCELLED'}

        p     = context.scene.efit_props
        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            self.report({'ERROR'}, "Clothing object no longer exists.")
            state._efit_cache.clear()
            return {'CANCELLED'}

        saved_uvs         = c.get('saved_uvs')

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        # Apply the corrective smooth modifier if present.
        m_cs = cloth.modifiers.get(f"{EFIT_PREFIX}Smooth")
        if m_cs is not None:
            bpy.ops.object.modifier_apply(modifier=m_cs.name)

        # Apply the laplacian smooth modifier if present.
        m_lap = cloth.modifiers.get(f"{EFIT_PREFIX}Laplacian")
        if m_lap is not None:
            bpy.ops.object.modifier_apply(modifier=m_lap.name)

        if saved_uvs:
            _restore_uvs(cloth.data, saved_uvs)

        state._efit_cache.clear()
        p.fit_mode           = 'FULL'
        p.use_exclusive_mode = False
        p.ui_tab             = 'FULL'

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        self.report({'INFO'}, "Fit applied.")
        return {'FINISHED'}


class EFIT_OT_preview_cancel(Operator):
    """Cancel the preview and restore the clothing to its original shape."""
    bl_idname      = "efit.preview_cancel"
    bl_label       = "Cancel Fit"
    bl_description = "Discard the previewed fit and restore original mesh"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(state._efit_cache)

    def execute(self, context):
        c = state._efit_cache
        if not c:
            self.report({'WARNING'}, "No preview to cancel.")
            return {'CANCELLED'}

        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            state._efit_cache.clear()
            self.report({'ERROR'}, "Clothing object no longer exists.")
            return {'CANCELLED'}

        # Remove live preview modifiers before restoring vertex positions.
        for mod_name in (f"{EFIT_PREFIX}Smooth", f"{EFIT_PREFIX}Laplacian"):
            m = cloth.modifiers.get(mod_name)
            if m is not None:
                cloth.modifiers.remove(m)

        flat = state._efit_originals.get(cloth.name)
        if flat is not None:
            cloth.data.vertices.foreach_set("co", np.asarray(flat, dtype=np.float64))
        else:
            all_originals = c['all_originals']
            for vi, co in enumerate(all_originals):
                cloth.data.vertices[vi].co = co
        cloth.data.update()

        state._efit_cache.clear()
        state._efit_originals.pop(cloth.name, None)
        if "_efit_originals" in cloth:
            del cloth["_efit_originals"]
        p = context.scene.efit_props
        p.fit_mode           = 'FULL'
        p.use_exclusive_mode = False
        p.ui_tab             = 'FULL'
        self.report({'INFO'}, "Fit cancelled. Clothing restored.")
        return {'FINISHED'}


class EFIT_OT_remove(Operator):
    """Remove all fit data from the clothing."""
    bl_idname      = "efit.remove"
    bl_label       = "Remove Fit"
    bl_description = "Remove all fit data from the clothing and restore it"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.efit_props.clothing_obj is not None

    def execute(self, context):
        cloth = context.scene.efit_props.clothing_obj
        if not cloth:
            self.report({'ERROR'}, "No clothing mesh selected.")
            return {'CANCELLED'}
        _remove_efit(cloth)

        for obj in list(bpy.data.objects):
            if obj.name.startswith(EFIT_PREFIX) and obj.type == 'MESH':
                bpy.data.objects.remove(obj, do_unlink=True)

        self.report({'INFO'}, "Fit removed.")
        return {'FINISHED'}


class EFIT_OT_clear_blockers(Operator):
    """Remove shape keys and unapplied modifiers from the clothing."""
    bl_idname      = "efit.clear_blockers"
    bl_label       = "Clear Blockers"
    bl_description = "Remove shape keys and unapplied modifiers from the clothing so it can be fitted"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = context.scene.efit_props
        return p.clothing_obj is not None and p.clothing_obj.type == 'MESH'

    def execute(self, context):
        cloth = context.scene.efit_props.clothing_obj
        if not cloth or cloth.type != 'MESH':
            self.report({'ERROR'}, "Select a valid clothing mesh first.")
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        removed = []

        # Remove all shape keys via the operator (handles Basis key correctly).
        if cloth.data.shape_keys:
            count = len(cloth.data.shape_keys.key_blocks)
            bpy.ops.object.select_all(action='DESELECT')
            cloth.select_set(True)
            context.view_layer.objects.active = cloth
            bpy.ops.object.shape_key_remove(all=True)
            removed.append(f"{count} shape keys")

        # Remove non-EFit, non-armature modifiers.
        non_efit = [m for m in cloth.modifiers
                    if not m.name.startswith(EFIT_PREFIX) and m.type != 'ARMATURE']
        for m in non_efit:
            cloth.modifiers.remove(m)
        if non_efit:
            removed.append(f"{len(non_efit)} modifiers")

        if removed:
            self.report({'INFO'}, f"Removed: {', '.join(removed)}")
        else:
            self.report({'INFO'}, "Nothing to remove.")
        return {'FINISHED'}


class EFIT_OT_reset_defaults(Operator):
    """Reset all Elastic Fit sliders to their default values."""
    bl_idname      = "efit.reset_defaults"
    bl_label       = "Reset Defaults"
    bl_description = "Reset all sliders to their default values"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.efit_props
        for prop_name in (
            'fit_mode', 'use_exclusive_mode', 'ui_tab',
            'fit_amount', 'offset', 'proxy_triangles', 'preserve_uvs', 'use_proxy_hull',
            'smooth_factor', 'smooth_iterations',
            'post_laplacian', 'laplacian_factor', 'laplacian_iterations',
            'follow_strength', 'cleanup',
            'disp_smooth_passes', 'disp_smooth_threshold',
            'disp_smooth_min', 'disp_smooth_max', 'follow_neighbors',
            'use_proximity_falloff', 'proximity_mode',
            'proximity_start', 'proximity_end', 'proximity_curve',
            'use_proximity_group_tuning',
            'show_fit_settings', 'show_shape_preservation', 'show_preserve_group',
            'show_displacement_smoothing',
            'show_offset_fine_tuning', 'show_misc',
        ):
            p.property_unset(prop_name)
        if state._efit_cache:
            _efit_preview_update(context)
        self.report({'INFO'}, "All sliders reset to defaults.")
        return {'FINISHED'}


class EFIT_OT_offset_group_add(Operator):
    """Add a new vertex group offset entry."""
    bl_idname      = "efit.offset_group_add"
    bl_label       = "Add Offset Group"
    bl_description = "Add a vertex group whose offset influence can be fine-tuned"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item           = context.scene.efit_props.offset_groups.add()
        item.influence = 100
        return {'FINISHED'}


class EFIT_OT_offset_group_remove(Operator):
    """Remove the offset group entry at the given list index."""
    bl_idname      = "efit.offset_group_remove"
    bl_label       = "Remove Offset Group"
    bl_description = "Remove this vertex group offset entry"
    bl_options     = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        groups = context.scene.efit_props.offset_groups
        if 0 <= self.index < len(groups):
            groups.remove(self.index)
            if state._efit_cache:
                _efit_preview_update(context)
        return {'FINISHED'}


class EFIT_OT_proximity_group_add(Operator):
    """Add a new per-group proximity falloff entry."""
    bl_idname      = "efit.proximity_group_add"
    bl_label       = "Add Proximity Group"
    bl_description = "Add a vertex group with its own proximity falloff settings"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.efit_props.proximity_groups.add()
        return {'FINISHED'}


class EFIT_OT_proximity_group_remove(Operator):
    """Remove the proximity group entry at the given list index."""
    bl_idname      = "efit.proximity_group_remove"
    bl_label       = "Remove Proximity Group"
    bl_description = "Remove this per-group proximity falloff entry"
    bl_options     = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        groups = context.scene.efit_props.proximity_groups
        if 0 <= self.index < len(groups):
            groups.remove(self.index)
            if state._efit_cache:
                from .preview import _efit_preview_update as _preview_update
                _preview_update(context)
        return {'FINISHED'}


class EFIT_OT_exclusive_group_add(Operator):
    """Add a vertex group to the Exclusive Vertex Group Fit list."""
    bl_idname      = "efit.exclusive_group_add"
    bl_label       = "Add Exclusive Group"
    bl_description = "Add a vertex group to fit exclusively"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Disabled during an active preview so the list cannot change mid-fit.
        return not state._efit_cache

    def execute(self, context):
        context.scene.efit_props.exclusive_groups.add()
        return {'FINISHED'}


class EFIT_OT_exclusive_group_remove(Operator):
    """Remove a vertex group entry from the Exclusive Vertex Group Fit list."""
    bl_idname      = "efit.exclusive_group_remove"
    bl_label       = "Remove Exclusive Group"
    bl_description = "Remove this vertex group from the exclusive fit list"
    bl_options     = {'REGISTER', 'UNDO'}

    index: IntProperty()

    @classmethod
    def poll(cls, context):
        return not state._efit_cache

    def execute(self, context):
        groups = context.scene.efit_props.exclusive_groups
        if 0 <= self.index < len(groups):
            groups.remove(self.index)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Update operators
# ---------------------------------------------------------------------------

class EFIT_OT_check_update(Operator):
    """Check GitHub for a newer release of Elastic Clothing Fit."""
    bl_idname      = "efit.check_update"
    bl_label       = "Check for Updates"
    bl_description = "Query the GitHub releases API to see if a newer version is available"
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        # Grey out during an active preview so a network call cannot start mid-fit.
        return not state._efit_cache

    def execute(self, context):
        updater.check_for_update()
        return {'FINISHED'}


class EFIT_OT_download_update(Operator):
    """Download the latest release zip in the background."""
    bl_idname      = "efit.download_update"
    bl_label       = "Download Update"
    bl_description = "Download the latest release zip file in the background"
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return updater.get_status() == 'available'

    def execute(self, context):
        updater.download_and_prepare()
        return {'FINISHED'}


class EFIT_OT_install_restart(Operator):
    """Write the install startup script and relaunch Blender."""
    bl_idname      = "efit.install_restart"
    bl_label       = "Restart and Install"
    bl_description = "Save if requested, write an auto-install script, and relaunch Blender"
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return updater.get_status() == 'ready'

    def execute(self, context):
        p = context.scene.efit_props
        if p.update_save_file and bpy.data.filepath and bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        reopen = bpy.data.filepath if (bpy.data.filepath and p.update_reopen_file) else ''
        updater.install_and_restart(reopen_filepath=reopen)
        return {'FINISHED'}


