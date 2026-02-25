# panels.py
# Blender panel definition for Elastic Clothing Fit.
# Draws the sidebar panel including mesh selection, blocker warnings,
# action buttons, and the collapsible Advanced Settings section.

import bpy
from bpy.types import Panel

from . import state
from . import updater
from .state import _has_blockers, PANEL_CATEGORY


def _wrap_text(text, max_chars=40, max_lines=3):
    """Split text into word-wrapped lines, capped at max_lines."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            if len(lines) == max_lines:
                return lines
            current = word
        else:
            current = (current + " " + word).strip()
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


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

        # -- Fit Mode toggle --
        # Disabled during preview so mode cannot change while a fit is active.
        mode_row         = layout.row(align=True)
        mode_row.enabled = not in_preview
        mode_row.prop(p, "fit_mode", expand=True)
        if p.fit_mode == 'EXCLUSIVE':
            warn       = layout.box()
            warn.alert = True
            warn.label(text="Exclusive mode: only selected vertex groups will be fitted.", icon='ERROR')
            warn.label(text="Fit mode resets to Full Mesh Fit after Apply or Cancel.")

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

            # Exclusive Groups (shown at top of Advanced Settings in EVGF mode)
            if p.fit_mode == 'EXCLUSIVE':
                sub = box.box()
                sub.label(text="Groups to Fit", icon='GROUP_VERTEX')
                if p.exclusive_groups:
                    header          = sub.row(align=True)
                    header.scale_y  = 0.6
                    header.label(text="Vertex Group")
                    header.label(text="Influence")
                for i, eg in enumerate(p.exclusive_groups):
                    row = sub.row(align=True)
                    # Group name and remove button locked during preview; influence stays live.
                    name_col         = row.column()
                    name_col.enabled = not in_preview
                    name_col.prop(eg, "group_name", text="")
                    row.prop(eg, "influence", text="")
                    rm_col         = row.column()
                    rm_col.enabled = not in_preview
                    op             = rm_col.operator("efit.exclusive_group_remove", text="", icon='REMOVE')
                    op.index       = i
                add_row         = sub.row()
                add_row.enabled = not in_preview
                add_row.operator("efit.exclusive_group_add", text="Add Group", icon='ADD')

            # Fit Settings
            sub = box.box()
            sub.label(text="Fit Settings", icon='MOD_SHRINKWRAP')
            sub.prop(p, "fit_amount")
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

            # Preserve Group (hidden in EVGF mode; exclusive groups take its place)
            if p.fit_mode == 'FULL':
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

            # Offset Fine Tuning (hidden in EVGF mode; exclusive groups carry their own influence)
            if p.fit_mode == 'FULL':
                col.separator()
                col.label(text="Offset Fine Tuning:")
                if p.offset_groups:
                    header          = col.row(align=True)
                    header.scale_y  = 0.6
                    header.label(text="Vertex Group")
                    header.label(text="Influence")
                for i, og in enumerate(p.offset_groups):
                    row = col.row(align=True)
                    row.prop(og, "group_name", text="")
                    row.prop(og, "influence", text="")
                    op       = row.operator("efit.offset_group_remove", text="", icon='REMOVE')
                    op.index = i
                col.operator("efit.offset_group_add", text="Add Group", icon='ADD')

            # Misc
            box.separator()
            row = box.row()
            row.prop(p, "cleanup")
            row.operator("efit.reset_defaults", icon='LOOP_BACK')

        # -- Updates --
        layout.separator()
        upd = layout.box()
        s   = updater.get_state()

        if s['status'] == 'checking':
            upd.label(text="Checking for updates...", icon='SORTTIME')

        elif s['status'] == 'up_to_date':
            row = upd.row()
            row.label(text="Up to date.", icon='CHECKMARK')
            row.operator("efit.check_update", text="", icon='FILE_REFRESH')

        elif s['status'] == 'available':
            upd.label(text=f"Update available: {s['tag']}", icon='ERROR')
            upd.operator("efit.download_update",
                         text=f"Download {s['tag']}", icon='IMPORT')
            upd.operator("efit.check_update", text="Re-check", icon='FILE_REFRESH')

        elif s['status'] == 'downloading':
            pct = int(s['progress'] * 100)
            upd.label(text=f"Downloading... {pct}%", icon='SORTTIME')

        elif s['status'] == 'ready':
            upd.label(text=f"{s['tag']} downloaded.", icon='INFO')
            has_filepath = bool(bpy.data.filepath)
            if has_filepath:
                if bpy.data.is_dirty:
                    upd.prop(p, "update_save_file")
                upd.prop(p, "update_reopen_file")
            else:
                warn = upd.box()
                warn.alert = True
                warn.label(text="File not saved - save manually", icon='ERROR')
                warn.label(text="before restarting to keep your work.")
            upd.operator("efit.install_restart",
                         text="Restart and Install", icon='LOOP_BACK')

        elif s['status'] == 'error':
            lines = _wrap_text("Error: " + s['error'], max_chars=40, max_lines=3)
            for i, line in enumerate(lines):
                upd.label(text=line, icon='ERROR' if i == 0 else 'NONE')
            upd.operator("efit.check_update", text="Try Again", icon='FILE_REFRESH')

        # Dev sub-box: visible only when the preference is enabled
        addon_prefs = context.preferences.addons.get(__package__)
        dev_mode    = addon_prefs.preferences.dev_update_testing if addon_prefs else False

        if dev_mode:
            dev_box       = upd.box()
            dev_box.alert = True
            dev_box.label(text="Dev mode: install uses local file only", icon='ERROR')

            zip_row = dev_box.row(align=True)
            zip_row.prop(p, "dev_local_zip", text="Local Zip")
            zip_row.operator("efit.browse_local_zip", text="", icon='FILE_FOLDER')

            dev_box.prop(p, "dev_override_newer")
            dev_box.prop(p, "dev_override_uptodate")
