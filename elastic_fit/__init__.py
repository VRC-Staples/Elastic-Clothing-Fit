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

from .properties import EFitExclusiveGroup, EFitOffsetGroup, EFitProperties


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
from .panels import SVRC_PT_elastic_fit
from . import state
from . import updater


@bpy.app.handlers.persistent
def _efit_session_cleanup_on_load(_):
    """Clear in-memory caches when a new .blend file is loaded.

    Prevents stale numpy arrays from previous sessions lingering in memory.
    Accessing cleared entries gracefully degrades (object lookups return None).
    """
    state._efit_cache.clear()
    state._efit_originals.clear()


# Registration order matters: PropertyGroups used as CollectionProperty types
# must be registered before the PropertyGroup that holds them.
_classes = (
    EFitExclusiveGroup,
    EFitOffsetGroup,
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
    SVRC_PT_elastic_fit,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.efit_props = PointerProperty(type=EFitProperties)
    bpy.app.handlers.load_post.append(_efit_session_cleanup_on_load)
    updater.check_for_update()


def unregister():
    if _efit_session_cleanup_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_efit_session_cleanup_on_load)
    del bpy.types.Scene.efit_props
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
