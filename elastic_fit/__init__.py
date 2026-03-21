# ============================================================================
#  Elastic Clothing Fit - Blender Add-on
# ============================================================================
#
#  Elastic, UV-safe clothing fitting with live preview and per-region offset control.
#
#  Copyright (C) 2026 .Staples.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# ============================================================================

bl_info = {
    "name": ".Staples. Elastic Clothing Fit",
    "author": ".Staples.",
    "version": (1, 0, 5),
    "blender": (3, 2, 0),
    "location": "View3D > Sidebar > .Staples. Elastic Fit",
    "description": "Elastic, UV-safe clothing fitting with live preview and per-region offset control",
    "category": "3D View",
}

import bpy
from bpy.props import PointerProperty

from .properties import EFitExclusiveGroup, EFitOffsetGroup, EFitProximityGroup, EFitArmatureEntry, EFitProperties, EFitAddonPreferences


from .operators import (
    EFIT_OT_fit,
    EFIT_OT_preview_apply,
    EFIT_OT_preview_cancel,
    EFIT_OT_remove,
    EFIT_OT_reset_defaults,
    EFIT_OT_clear_blockers,
    EFIT_OT_offset_group_add,
    EFIT_OT_offset_group_remove,
    EFIT_OT_proximity_group_add,
    EFIT_OT_proximity_group_remove,
    EFIT_OT_exclusive_group_add,
    EFIT_OT_exclusive_group_remove,
    EFIT_OT_check_update,
    EFIT_OT_download_update,
    EFIT_OT_install_restart,
)
from .armature_ops import (
    EFIT_OT_armature_display,
    EFIT_OT_armature_display_add,
    EFIT_OT_armature_display_remove,
    EFIT_OT_merge_armatures,
)
from .mesh_ops import (
    EFIT_OT_mesh_split,
    EFIT_OT_mesh_join,
)
from .panels import SVRC_PT_elastic_fit
from . import state
from . import updater


_PANEL_TOGGLES = (
    'show_fit_settings',
    'show_shape_preservation',
    'show_preserve_group',
    'show_proximity_falloff',
    'show_displacement_smoothing',
    'show_offset_fine_tuning',
    'show_misc',
    'show_armature_display',
    'show_merge_armatures',
    'show_mesh_split',
    'show_mesh_join',
    'show_advanced',
)


def _collapse_all_panels():
    """Collapse every show_* panel toggle for all scenes."""
    for scene in bpy.data.scenes:
        p = scene.efit_props
        for attr in _PANEL_TOGGLES:
            setattr(p, attr, False)


@bpy.app.handlers.persistent
def _efit_session_cleanup_on_load(_):
    """Clear in-memory caches and collapse all UI panels when a .blend file loads.

    Prevents stale numpy arrays from previous sessions lingering in memory.
    Accessing cleared entries gracefully degrades (object lookups return None).
    """
    state._efit_cache.clear()
    state._efit_originals.clear()
    state._bvh_cache.clear()
    _collapse_all_panels()


# Registration order matters: PropertyGroups used as CollectionProperty types
# must be registered before the PropertyGroup that holds them.
_classes = (
    EFitAddonPreferences,
    EFitProximityGroup,
    EFitExclusiveGroup,
    EFitOffsetGroup,
    EFitArmatureEntry,
    EFitProperties,
    EFIT_OT_fit,
    EFIT_OT_preview_apply,
    EFIT_OT_preview_cancel,
    EFIT_OT_remove,
    EFIT_OT_reset_defaults,
    EFIT_OT_clear_blockers,
    EFIT_OT_offset_group_add,
    EFIT_OT_offset_group_remove,
    EFIT_OT_proximity_group_add,
    EFIT_OT_proximity_group_remove,
    EFIT_OT_exclusive_group_add,
    EFIT_OT_exclusive_group_remove,
    EFIT_OT_check_update,
    EFIT_OT_download_update,
    EFIT_OT_install_restart,
    EFIT_OT_armature_display,
    EFIT_OT_armature_display_add,
    EFIT_OT_armature_display_remove,
    EFIT_OT_merge_armatures,
    EFIT_OT_mesh_split,
    EFIT_OT_mesh_join,
    SVRC_PT_elastic_fit,
)


def _efit_start_mcp_server():
    """Deferred callback: start the blender-mcp socket server if not already running.

    Called via bpy.app.timers shortly after addon registration so the Blender
    session is fully initialised before we touch the server object. Silently
    skips if the blender-mcp addon is not installed.

    Returns None to tell the timer system not to reschedule.
    """
    try:
        # The blender-mcp addon stores its server instance on bpy.types.
        # If the attribute does not exist the addon is not installed -- skip.
        server = getattr(bpy.types, 'blendermcp_server', None)
        if server is None:
            # Addon not installed or not yet registered -- create the instance.
            # BlenderMCPServer is defined in the blender-mcp addon module.
            # Attempt to reach it via the registered operator's module.
            try:
                import addon_utils
                for mod in addon_utils.modules():
                    if getattr(mod, 'bl_info', {}).get('name', '').lower().startswith('blender mcp'):
                        BlenderMCPServer = getattr(mod, 'BlenderMCPServer', None)
                        if BlenderMCPServer:
                            bpy.types.blendermcp_server = BlenderMCPServer(port=9876)
                            server = bpy.types.blendermcp_server
                            break
            except Exception:
                pass

        if server is None:
            # blender-mcp not available -- nothing to start.
            return None

        if not server.running:
            server.start()
            # Mirror the scene flag the blender-mcp UI panel reads.
            for scene in bpy.data.scenes:
                if hasattr(scene, 'blendermcp_server_running'):
                    scene.blendermcp_server_running = True

    except Exception as e:
        # Never let this crash Blender -- it is best-effort.
        print(f"[ECF] MCP server auto-start skipped: {e}")

    return None  # do not reschedule


_MIN_BLENDER = (3, 2, 0)


def register():
    if bpy.app.version < _MIN_BLENDER:
        ver = ".".join(str(x) for x in _MIN_BLENDER)
        raise RuntimeError(
            f".Staples. Elastic Clothing Fit requires Blender {ver} or later "
            f"(running {bpy.app.version_string}). Please upgrade Blender."
        )
    # Propagate the authoritative version from bl_info into _meta so that
    # panels.py can read it without a circular import.
    from . import _meta
    _meta.ADDON_VERSION = tuple(bl_info['version'])

    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.efit_props = PointerProperty(type=EFitProperties)
    bpy.app.handlers.load_post.append(_efit_session_cleanup_on_load)

    from .preview import (
        _on_tab_change, _on_preview_prop_update, _on_smooth_mod_update,
        _on_offset_group_influence_update, _on_offset_group_name_update,
        _on_proximity_group_prop_update, _on_proximity_group_name_update,
    )
    state.register_handler('tab_change',                        _on_tab_change)
    state.register_handler('preview_prop_update',               _on_preview_prop_update)
    state.register_handler('smooth_mod_update',                 _on_smooth_mod_update)
    state.register_handler('offset_group_influence_update',     _on_offset_group_influence_update)
    state.register_handler('offset_group_name_update',          _on_offset_group_name_update)
    state.register_handler('proximity_group_update',            _on_proximity_group_prop_update)
    state.register_handler('proximity_group_name_update',       _on_proximity_group_name_update)

    updater.check_for_update()

    # Prime the nightly content cache so panels.py _draw_update_tab does not
    # open the file on every draw call.
    from . import panels as _panels
    _panels._refresh_nightly_content()

    # Start the blender-mcp socket server after a short delay so the session
    # is fully ready. 0.5 s is enough for Blender's startup sequence to finish.
    bpy.app.timers.register(_efit_start_mcp_server, first_interval=0.5)


def unregister():
    state._bvh_cache.clear()
    for name in ('tab_change', 'preview_prop_update', 'smooth_mod_update',
                 'offset_group_influence_update', 'offset_group_name_update',
                 'proximity_group_update', 'proximity_group_name_update'):
        state.unregister_handler(name)
    if _efit_session_cleanup_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_efit_session_cleanup_on_load)
    del bpy.types.Scene.efit_props
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
