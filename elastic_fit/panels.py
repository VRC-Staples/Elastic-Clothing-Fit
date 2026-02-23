# panels.py
# Blender panel definition for Elastic Clothing Fit.
# Draws the sidebar panel including mesh selection, blocker warnings,
# action buttons, and the collapsible Advanced Settings section.

import bpy
from bpy.types import Panel

from . import state
from .state import _has_blockers, PANEL_CATEGORY


class SVRC_PT_elastic_fit(Panel):
    bl_label       = "Elastic Clothing Fit"
    bl_idname      = "SVRC_PT_elastic_fit"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = PANEL_CATEGORY
    bl_order       = 1

    def draw(self, context):
        layout     = self.layout
        p          = context.scene.efit_props
        in_preview = bool(state._efit_cache)

        # -- Mesh selection --
        box         = layout.box()
        box.enabled = not in_preview
        box.label(text="Select Meshes", icon='MESH_DATA')
        box.prop(p, "body_obj",     icon='OUTLINER_OB_MESH')
        box.prop(p, "clothing_obj", icon='MATCLOTH')

        # -- Blocker warnings --
        if p.clothing_obj and p.clothing_obj.type == 'MESH':
            has_sk, blocker_mods = _has_blockers(p.clothing_obj)
            if has_sk or blocker_mods:
                warn_box       = layout.box()
                warn_box.alert = True
                warn_box.label(text="Blockers Detected", icon='ERROR')
                if has_sk:
                    sk_count = len(p.clothing_obj.data.shape_keys.key_blocks)
                    warn_box.label(text=f"  {sk_count} shape key(s)", icon='SHAPEKEY_DATA')
                if blocker_mods:
                    warn_box.label(
                        text=f"  {len(blocker_mods)} modifier(s): {', '.join(blocker_mods[:3])}"
                             + ("..." if len(blocker_mods) > 3 else ""),
                        icon='MODIFIER',
                    )
                warn_box.operator("efit.clear_blockers", icon='TRASH')

        # -- Action buttons --
        layout.separator()

        if in_preview:
            box = layout.box()
            box.label(text="Preview Active", icon='HIDE_OFF')
            box.label(text="Adjust sliders to see changes live.")
            row          = box.row(align=True)
            row.scale_y  = 1.5
            row.operator("efit.preview_apply",  icon='CHECKMARK', text="Apply")
            row.operator("efit.preview_cancel", icon='CANCEL',    text="Cancel")
        else:
            row         = layout.row(align=True)
            row.scale_y = 1.5
            row.operator("efit.fit",    icon='CHECKMARK')
            row.operator("efit.remove", icon='X')

        # -- Advanced Settings (collapsed by default) --
        layout.separator()
        box = layout.box()
        row = box.row()
        row.prop(p, "show_advanced",
                 icon='TRIA_DOWN' if p.show_advanced else 'TRIA_RIGHT',
                 emboss=False)

        if p.show_advanced:

            if in_preview:
                note = box.row()
                note.label(text="Some options are locked during preview.", icon='INFO')

            # Fit Settings
            sub = box.box()
            sub.label(text="Fit Settings", icon='MOD_SHRINKWRAP')
            sub.prop(p, "fit_amount", slider=True)
            sub.prop(p, "offset")

            row         = sub.row()
            row.enabled = not in_preview
            row.prop(p, "proxy_triangles")

            row         = sub.row()
            row.enabled = not in_preview
            row.prop(p, "preserve_uvs")

            # Shape Preservation
            sub = box.box()
            sub.label(text="Shape Preservation", icon='MOD_SMOOTH')
            sub.prop(p, "smooth_factor")
            sub.prop(p, "smooth_iterations")

            # Post-Fit Options
            sub = box.box()
            sub.label(text="Post-Fit Options", icon='TOOL_SETTINGS')

            row         = sub.row()
            row.enabled = not in_preview
            row.prop(p, "post_symmetrize")
            if p.post_symmetrize and not in_preview:
                row.prop(p, "symmetrize_axis", text="")

            sub.prop(p, "post_laplacian")
            if p.post_laplacian:
                col = sub.column(align=True)
                col.prop(p, "laplacian_factor")
                col.prop(p, "laplacian_iterations")

            # Preserve Group
            sub = box.box()
            sub.label(text="Preserve Group (Optional)", icon='PINNED')
            if p.clothing_obj and p.clothing_obj.type == 'MESH':
                sub.prop(p, "preserve_group", text="Group")
                if p.preserve_group:
                    sub.prop(p, "follow_strength")
            else:
                sub.label(text="Select clothing first", icon='INFO')

            # Displacement Smoothing
            sub = box.box()
            col = sub.column(align=True)
            col.label(text="Displacement Smoothing:")
            col.prop(p, "disp_smooth_passes")
            col.prop(p, "disp_smooth_threshold")
            col.prop(p, "disp_smooth_min")
            col.prop(p, "disp_smooth_max")

            # Preserve Follow
            col.separator()
            col.label(text="Preserve Follow:")
            col.prop(p, "follow_neighbors")

            # Offset Fine Tuning
            col.separator()
            col.label(text="Offset Fine Tuning:")
            cloth_obj = p.clothing_obj
            if p.offset_groups:
                header          = col.row(align=True)
                header.scale_y  = 0.6
                header.label(text="Vertex Group")
                header.label(text="Influence")
            for i, og in enumerate(p.offset_groups):
                row = col.row(align=True)
                row.prop(og, "group_name", text="")
                row.prop(og, "influence", text="", slider=True)
                op       = row.operator("efit.offset_group_remove", text="", icon='REMOVE')
                op.index = i
            col.operator("efit.offset_group_add", text="Add Group", icon='ADD')

            # Misc
            box.separator()
            row = box.row()
            row.prop(p, "cleanup")
            row.operator("efit.reset_defaults", icon='LOOP_BACK')
