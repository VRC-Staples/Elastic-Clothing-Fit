# panels.py
# Blender panel definition for Elastic Clothing Fit.
# Three-tab layout: Full Mesh Fit, Exclusive Fit, Update.
# Each tab has pinned controls (always visible) and collapsible sections.

import pathlib

import bpy
from bpy.types import Panel

from . import state
from . import updater
from .state import _has_blockers_cached, PANEL_CATEGORY

_nightly_path = pathlib.Path(__file__).parent / "_nightly.txt"


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


# ---------------------------------------------------------------------------
# Shared drawing helpers
# ---------------------------------------------------------------------------

def _draw_mesh_pickers(layout, p, in_preview):
    box         = layout.box()
    box.enabled = not in_preview
    box.label(text="Select Meshes", icon='MESH_DATA')
    if not p.body_obj or not p.clothing_obj:
        box.label(text="Pick your avatar body, then the clothing item to fit.", icon='INFO')
    box.prop(p, "body_obj",     icon='OUTLINER_OB_MESH')
    box.prop(p, "clothing_obj", icon='MATCLOTH')
    if p.body_obj and p.clothing_obj and p.body_obj == p.clothing_obj:
        dup = box.box()
        dup.alert = True
        dup.label(text="Body and clothing must be different meshes.", icon='ERROR')


def _draw_blocker_warnings(layout, p):
    if not (p.clothing_obj and p.clothing_obj.type == 'MESH'):
        return
    has_sk, blocker_mods = _has_blockers_cached(p.clothing_obj)
    if not (has_sk or blocker_mods):
        return
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


def _draw_action_buttons(layout, p, in_preview):
    layout.separator()
    if in_preview:
        box = layout.box()
        box.label(text="Preview Active", icon='HIDE_OFF')
        box.label(text="Adjust sliders to see changes live.")
        row         = box.row(align=True)
        row.scale_y = 1.5
        row.operator("efit.preview_apply",  icon='CHECKMARK', text="Apply")
        row.operator("efit.preview_cancel", icon='CANCEL',    text="Cancel")
    else:
        cloth    = p.clothing_obj
        has_fit  = bool(
            cloth and (
                cloth.name in state._efit_originals
                or "_efit_originals" in cloth
            )
        )
        fit_row         = layout.row()
        fit_row.scale_y = 1.5
        fit_row.operator("efit.fit", icon='CHECKMARK')
        rm_row         = layout.row()
        rm_row.scale_y = 1.2
        rm_row.enabled = has_fit
        rm_row.operator("efit.remove", icon='X')


def _collapsible(layout, p, prop_name):
    """Draw a collapsible toggle row. Returns True if expanded."""
    row = layout.row()
    row.prop(
        p, prop_name,
        icon='TRIA_DOWN' if getattr(p, prop_name) else 'TRIA_RIGHT',
        emboss=False,
    )
    return getattr(p, prop_name)


def _section(layout, p, prop_name, draw_fn, *args):
    """Box with a collapsible header; calls draw_fn(box, *args) when expanded."""
    box      = layout.box()
    expanded = _collapsible(box, p, prop_name)
    if expanded:
        draw_fn(box, *args)


# ---------------------------------------------------------------------------
# Section content helpers
# ---------------------------------------------------------------------------

def _draw_fit_settings(layout, p, in_preview):
    col = layout.column(align=True)
    col.prop(p, "fit_amount")
    col.prop(p, "offset")
    row         = col.row()
    row.enabled = not in_preview
    row.prop(p, "proxy_triangles")
    row         = col.row()
    row.enabled = not in_preview
    row.prop(p, "preserve_uvs")
    row         = col.row()
    row.enabled = not in_preview
    row.prop(p, "use_proxy_hull")


def _draw_shape_preservation(layout, p):
    col = layout.column(align=True)
    col.prop(p, "smooth_factor")
    col.prop(p, "smooth_iterations")
    layout.prop(p, "use_proximity_falloff")
    if p.use_proximity_falloff:
        col = layout.column(align=True)
        col.prop(p, "proximity_mode")
        col.prop(p, "proximity_start")
        col.prop(p, "proximity_end")
        col.prop(p, "proximity_curve")


def _draw_preserve_group(layout, p):
    if p.clothing_obj and p.clothing_obj.type == 'MESH':
        layout.prop(p, "preserve_group", text="Group")
        if p.preserve_group:
            col = layout.column(align=True)
            col.prop(p, "follow_strength")
            col.prop(p, "follow_neighbors")
    else:
        layout.label(text="Select clothing first", icon='INFO')


def _draw_displacement_smoothing(layout, p):
    col = layout.column(align=True)
    col.prop(p, "disp_smooth_passes")
    col.prop(p, "disp_smooth_threshold")
    col.prop(p, "disp_smooth_min")
    col.prop(p, "disp_smooth_max")
    layout.prop(p, "post_laplacian")
    if p.post_laplacian:
        col = layout.column(align=True)
        col.prop(p, "laplacian_factor")
        col.prop(p, "laplacian_iterations")


def _draw_offset_fine_tuning(layout, p, in_preview):
    if p.offset_groups:
        header         = layout.row(align=True)
        header.scale_y = 0.6
        header.label(text="Vertex Group")
        header.label(text="Influence")
    for i, og in enumerate(p.offset_groups):
        row              = layout.row(align=True)
        name_col         = row.column()
        name_col.enabled = not in_preview
        name_col.prop(og, "group_name", text="")
        row.prop(og, "influence", text="")
        rm_col         = row.column()
        rm_col.enabled = not in_preview
        op             = rm_col.operator("efit.offset_group_remove", text="", icon='REMOVE')
        op.index       = i
    add_row         = layout.row()
    add_row.enabled = not in_preview
    add_row.operator("efit.offset_group_add", text="Add Group", icon='ADD')


def _draw_misc(layout, p):
    layout.prop(p, "cleanup")
    layout.operator("efit.reset_defaults", icon='LOOP_BACK')


def _draw_armature_display(layout, p):
    for i, entry in enumerate(p.armature_display_targets):
        row      = layout.row(align=True)
        row.prop(entry, "armature", text="")
        op       = row.operator("efit.armature_display_remove", text="", icon='REMOVE')
        op.index = i
    layout.operator("efit.armature_display_add", text="Add Armature", icon='ADD')
    layout.separator()
    col = layout.column(align=True)
    col.prop(p, "armature_display_type")
    col.prop(p, "armature_show_in_front")
    layout.separator()
    layout.operator("efit.armature_display", icon='ARMATURE_DATA')


def _draw_merge_armatures(layout, p):
    col = layout.column(align=True)
    col.prop(p, "merge_source_armature", icon='ARMATURE_DATA')
    col.prop(p, "merge_target_armature", icon='ARMATURE_DATA')
    layout.separator()
    col = layout.column(align=True)
    col.prop(p, "merge_bones")
    col.prop(p, "merge_align_first")
    layout.separator()
    layout.operator("efit.merge_armatures", icon='CONSTRAINT_BONE')


def _draw_mesh_split(layout, p):
    layout.prop(p, "mesh_split_mode")
    if p.mesh_split_mode == 'BY_VERTEX_GROUP':
        layout.prop(p, "mesh_split_group", text="Group", icon='GROUP_VERTEX')
    layout.separator()
    layout.operator("efit.mesh_split", icon='MESH_DATA')


def _draw_mesh_join(layout, p):
    layout.prop(p, "mesh_join_merge")
    if p.mesh_join_merge:
        layout.prop(p, "mesh_join_threshold")
    layout.separator()
    layout.operator("efit.mesh_join", icon='OBJECT_DATA')


def _tools_tab(layout, p):
    _section(layout, p, 'show_armature_display', _draw_armature_display, p)
    _section(layout, p, 'show_merge_armatures',  _draw_merge_armatures,  p)
    _section(layout, p, 'show_mesh_split',        _draw_mesh_split,       p)
    _section(layout, p, 'show_mesh_join',         _draw_mesh_join,        p)


def _draw_exclusive_groups(layout, p, in_preview):
    sub = layout.box()
    sub.label(text="Groups to Fit", icon='GROUP_VERTEX')
    if p.exclusive_groups:
        header         = sub.row(align=True)
        header.scale_y = 0.6
        header.label(text="Vertex Group")
        header.label(text="Influence")
    for i, eg in enumerate(p.exclusive_groups):
        row              = sub.row(align=True)
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


def _draw_update_tab(layout, context):
    from . import bl_info
    p = context.scene.efit_props
    s = updater.get_state()

    # --- version header ---
    version_str = f"v{'.'.join(str(x) for x in bl_info['version'])}"
    nightly_ts = _nightly_path.read_text().strip() if _nightly_path.is_file() else None
    if nightly_ts:
        parts = nightly_ts.split()
        ts_part = parts[0] if parts else nightly_ts
        commit_part = parts[1] if len(parts) > 1 else ''
        if len(ts_part) >= 8 and ts_part[:8].isdigit():
            d = ts_part[:8]
            display_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        else:
            display_date = ts_part
        suffix = f"-nightly ({display_date})"
        if commit_part:
            suffix += f" [{commit_part}]"
        version_str += suffix
    split = layout.split(factor=0.4)
    split.label(text="Addon")
    split.label(text=version_str)
    split = layout.split(factor=0.4)
    split.label(text="Blender")
    split.label(text=f"v{'.'.join(str(x) for x in bpy.app.version)}")
    layout.separator()

    # --- nightly channel toggle ---
    layout.prop(p, "use_nightly_channel")
    if updater._is_dev_mode():
        layout.prop(p, "dev_update_url")
    layout.separator()

    if s['status'] == 'checking':
        layout.label(text="Checking for updates...", icon='SORTTIME')

    elif s['status'] == 'up_to_date':
        row = layout.row()
        row.label(text="Up to date.", icon='CHECKMARK')
        row.operator("efit.check_update", text="", icon='FILE_REFRESH')

    elif s['status'] == 'available':
        layout.label(text=f"Update available: {s['tag']}", icon='ERROR')
        if s.get('blender_blocked'):
            req = s['blender_min_required']
            req_str = '.'.join(str(x) for x in req)
            layout.label(text=f"Requires Blender {req_str} or later.", icon='ERROR')
        dl_col = layout.column()
        dl_col.enabled = not s.get('blender_blocked', False)
        dl_col.operator("efit.download_update",
                        text=f"Download {s['tag']}", icon='IMPORT')
        layout.operator("efit.check_update", text="Re-check", icon='FILE_REFRESH')

    elif s['status'] == 'downloading':
        pct = int(s['progress'] * 100)
        layout.label(text=f"Downloading... {pct}%", icon='SORTTIME')

    elif s['status'] == 'ready':
        layout.label(text=f"{s['tag']} downloaded.", icon='INFO')
        has_filepath = bool(bpy.data.filepath)
        if has_filepath:
            if bpy.data.is_dirty:
                layout.prop(p, "update_save_file")
            layout.prop(p, "update_reopen_file")
        else:
            warn       = layout.box()
            warn.alert = True
            warn.label(text="Your .blend file is untitled and unsaved.", icon='ERROR')
            warn.label(text="Save before restarting or lose work.")
        layout.operator("efit.install_restart",
                        text="Restart and Install", icon='LOOP_BACK')

    elif s['status'] == 'error':
        lines = _wrap_text("Error: " + s['error'], max_chars=40, max_lines=3)
        for i, line in enumerate(lines):
            layout.label(text=line, icon='ERROR' if i == 0 else 'NONE')
        layout.operator("efit.check_update", text="Try Again", icon='FILE_REFRESH')

    else:
        row = layout.row()
        row.label(text="", icon='CHECKMARK')
        row.operator("efit.check_update", text="Check for Updates", icon='FILE_REFRESH')


# ---------------------------------------------------------------------------
# Tab content functions
# ---------------------------------------------------------------------------

def _full_tab(layout, p, in_preview):
    _draw_mesh_pickers(layout, p, in_preview)
    _draw_blocker_warnings(layout, p)
    _draw_action_buttons(layout, p, in_preview)

    layout.separator()

    if _collapsible(layout, p, 'show_advanced'):
        _section(layout, p, 'show_fit_settings',          _draw_fit_settings,          p, in_preview)
        _section(layout, p, 'show_shape_preservation',     _draw_shape_preservation,    p)
        _section(layout, p, 'show_displacement_smoothing', _draw_displacement_smoothing, p)
        _section(layout, p, 'show_preserve_group',         _draw_preserve_group,        p)
        _section(layout, p, 'show_offset_fine_tuning',    _draw_offset_fine_tuning,    p, in_preview)
        _section(layout, p, 'show_misc',                  _draw_misc,                  p)


def _exclusive_tab(layout, p, in_preview):
    _draw_mesh_pickers(layout, p, in_preview)
    _draw_blocker_warnings(layout, p)
    _draw_exclusive_groups(layout, p, in_preview)
    _draw_action_buttons(layout, p, in_preview)

    layout.separator()

    if _collapsible(layout, p, 'show_advanced'):
        _section(layout, p, 'show_fit_settings',           _draw_fit_settings,          p, in_preview)
        _section(layout, p, 'show_shape_preservation',     _draw_shape_preservation,    p)
        _section(layout, p, 'show_displacement_smoothing', _draw_displacement_smoothing, p)
        _section(layout, p, 'show_misc',                   _draw_misc,                  p)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

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

        row         = layout.row(align=True)
        row.enabled = not in_preview
        row.prop(p, "ui_tab", expand=True)

        layout.separator()

        if p.ui_tab == 'FULL':
            _full_tab(layout, p, in_preview)
        elif p.ui_tab == 'EXCLUSIVE':
            _exclusive_tab(layout, p, in_preview)
        elif p.ui_tab == 'TOOLS':
            _tools_tab(layout, p)
        elif p.ui_tab == 'UPDATE':
            _draw_update_tab(layout, context)
