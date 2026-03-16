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
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > .Staples. Elastic Fit",
    "description": "Elastic, UV-safe clothing fitting with live preview and per-region offset control",
    "category": "3D View",
}

import bpy
from bpy.props import PointerProperty

from .properties import EFitExclusiveGroup, EFitOffsetGroup, EFitArmatureEntry, EFitProperties


from .operators import (
    EFIT_OT_fit,
    EFIT_OT_preview_apply,
    EFIT_OT_preview_cancel,
    EFIT_OT_remove,
    EFIT_OT_reset_defaults,
    EFIT_OT_clear_blockers,
    EFIT_OT_offset_group_add,
    EFIT_OT_offset_group_remove,
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
    _collapse_all_panels()


# Registration order matters: PropertyGroups used as CollectionProperty types
# must be registered before the PropertyGroup that holds them.
_classes = (
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
    EFIT_OT_exclusive_group_add,
    EFIT_OT_exclusive_group_remove,
    EFIT_OT_check_update,
    EFIT_OT_download_update,
    EFIT_OT_install_restart,
    EFIT_OT_armature_display,
    EFIT_OT_armature_display_add,
    EFIT_OT_armature_display_remove,
    EFIT_OT_merge_armatures,
    SVRC_PT_elastic_fit,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.efit_props = PointerProperty(type=EFitProperties)
    bpy.app.handlers.load_post.append(_efit_session_cleanup_on_load)

    from .preview import (
        _on_tab_change, _on_preview_prop_update, _on_smooth_mod_update,
        _on_offset_group_influence_update, _on_offset_group_name_update,
    )
    state.register_handler('tab_change',                        _on_tab_change)
    state.register_handler('preview_prop_update',               _on_preview_prop_update)
    state.register_handler('smooth_mod_update',                 _on_smooth_mod_update)
    state.register_handler('offset_group_influence_update',     _on_offset_group_influence_update)
    state.register_handler('offset_group_name_update',          _on_offset_group_name_update)

    updater.check_for_update()


def unregister():
    for name in ('tab_change', 'preview_prop_update', 'smooth_mod_update',
                 'offset_group_influence_update', 'offset_group_name_update'):
        state.unregister_handler(name)
    if _efit_session_cleanup_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_efit_session_cleanup_on_load)
    del bpy.types.Scene.efit_props
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
