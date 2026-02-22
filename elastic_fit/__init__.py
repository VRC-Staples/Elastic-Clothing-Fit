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
    "name": "Elastic Clothing Fit",
    "author": ".Staples.",
    "version": (1, 0, 4),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > .Staples. Elastic Fit",
    "description": "Elastic, UV-safe clothing fitting with live preview and per-region offset control",
    "category": "3D View",
}

import bpy
from bpy.props import PointerProperty

from .properties import EFitOffsetGroup, EFitProperties
from .operators import (
    EFIT_OT_fit,
    EFIT_OT_preview_apply,
    EFIT_OT_preview_cancel,
    EFIT_OT_remove,
    EFIT_OT_reset_defaults,
    EFIT_OT_clear_blockers,
    EFIT_OT_offset_group_add,
    EFIT_OT_offset_group_remove,
)
from .ui import SVRC_PT_elastic_fit

# Registration order matters: EFitOffsetGroup must be registered before
# EFitProperties because EFitProperties holds a CollectionProperty of it.
_classes = (
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
    SVRC_PT_elastic_fit,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.efit_props = PointerProperty(type=EFitProperties)


def unregister():
    del bpy.types.Scene.efit_props
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
