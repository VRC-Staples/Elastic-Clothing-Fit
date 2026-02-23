# properties.py
# Blender PropertyGroup definitions for Elastic Clothing Fit.
# EFitExclusiveGroup is a single vertex group entry used in the EVGF exclusive groups list.
# EFitOffsetGroup is a single vertex-group/influence pair used in a collection.
# EFitProperties holds all user-facing settings for the add-on.
# Update callbacks are imported from preview.py, which must be loaded first.

import bpy
from bpy.props import (
    PointerProperty, FloatProperty, IntProperty, BoolProperty,
    StringProperty, EnumProperty, CollectionProperty,
)
from bpy.types import PropertyGroup

from .state import _mesh_poll
from .preview import (
    _on_preview_prop_update,
    _on_smooth_mod_update,
    _on_offset_group_influence_update,
    _on_offset_group_name_update,
)

# Module-level caches keep the enum item lists alive between Blender redraws.
# Blender can GC the list returned from an items callback if nothing else holds a reference.
_preserve_group_items_cache = []
_group_name_items_cache = []


def _preserve_group_items(self, context):
    # self is an EFitProperties instance; clothing_obj is accessible directly.
    # Reverses creation order so the most recently added group appears at the top.
    global _preserve_group_items_cache
    items = [("", "None", "")]
    if self.clothing_obj and self.clothing_obj.type == 'MESH':
        for vg in reversed(self.clothing_obj.vertex_groups):
            items.append((vg.name, vg.name, ""))
    _preserve_group_items_cache = items
    return items


def _group_name_items(self, context):
    # self is an EFitOffsetGroup instance; reach the clothing obj through the scene.
    # context may be None during undo/redo; guard before accessing it.
    # Reverses creation order so the most recently added group appears at the top.
    global _group_name_items_cache
    items = [("", "None", "")]
    if context is not None:
        p = context.scene.efit_props
        if p.clothing_obj and p.clothing_obj.type == 'MESH':
            for vg in reversed(p.clothing_obj.vertex_groups):
                items.append((vg.name, vg.name, ""))
    _group_name_items_cache = items
    return items


class EFitExclusiveGroup(PropertyGroup):
    """A single vertex group entry for Exclusive Vertex Group Fit mode."""
    group_name: EnumProperty(
        name="Vertex Group",
        description="Vertex group to fit exclusively to the body",
        items=_group_name_items,
    )
    influence: IntProperty(
        name="Influence",
        description="How much this group pushes away from the body. 100 is neutral, 0 pulls flush, 200 doubles the gap.",
        default=100,
        min=0,
        max=1000,
        subtype='PERCENTAGE',
        update=_on_offset_group_influence_update,
    )


class EFitOffsetGroup(PropertyGroup):
    """One vertex group / influence pair for per-group offset fine-tuning."""
    group_name: EnumProperty(
        name="Vertex Group",
        description="Vertex group whose offset influence will be adjusted",
        items=_group_name_items,
        update=_on_offset_group_name_update,
    )
    influence: IntProperty(
        name="Influence",
        description="How much this group pushes away from the body. 100 is neutral, 0 pulls flush, 200 doubles the gap.",
        default=100,
        min=0,
        max=1000,
        subtype='PERCENTAGE',
        update=_on_offset_group_influence_update,
    )


class EFitProperties(PropertyGroup):

    body_obj: PointerProperty(
        name="Body",
        type=bpy.types.Object,
        poll=_mesh_poll,
        description="Body mesh to fit clothing onto",
    )
    clothing_obj: PointerProperty(
        name="Clothing",
        type=bpy.types.Object,
        poll=_mesh_poll,
        description="Clothing mesh to be fitted",
    )

    fit_mode: EnumProperty(
        name="Fit Mode",
        description="Which vertices to fit",
        items=[
            ('FULL',      "Full Mesh Fit",             "Fit the entire clothing mesh to the body"),
            ('EXCLUSIVE', "Exclusive Vertex Group Fit", "Fit only the selected vertex groups, leaving the rest of the mesh untouched"),
        ],
        default='FULL',
    )
    exclusive_groups: CollectionProperty(
        name="Exclusive Groups",
        type=EFitExclusiveGroup,
        description="Vertex groups to fit in Exclusive Vertex Group Fit mode",
    )

    fit_amount: FloatProperty(
        name="Fit Amount",
        description="How tightly the clothing hugs the body. Lower values keep it loose, higher values pull it flush.",
        default=0.67,
        min=0.0,
        max=1.0,
        step=1,
        update=_on_preview_prop_update,
    )

    offset: FloatProperty(
        name="Offset",
        description="Gap between the fitted clothing and the body surface",
        default=0.005,
        min=0.0,
        max=0.5,
        step=0.01,
        precision=4,
        subtype='DISTANCE',
        update=_on_preview_prop_update,
    )

    proxy_triangles: IntProperty(
        name="Proxy Resolution",
        description="Detail level of the temporary mesh used during fitting. Higher gives cleaner results but takes longer.",
        default=300000,
        min=10000,
        max=2000000,
        step=50000,
    )

    preserve_uvs: BoolProperty(
        name="Preserve UVs",
        description="Keep UVs unchanged after fitting. Recommended for most workflows.",
        default=True,
    )

    smooth_factor: FloatProperty(
        name="Elastic Strength",
        description="How much the clothing tries to keep its original shape after being pulled onto the body.",
        default=0.75,
        min=0.0,
        max=2.0,
        update=_on_smooth_mod_update,
    )
    smooth_iterations: IntProperty(
        name="Elastic Iterations",
        description="How many times shape correction is applied. Higher values preserve more of the original silhouette.",
        default=10,
        min=0,
        max=100,
        update=_on_smooth_mod_update,
    )

    # -- Post-fit options --

    post_symmetrize: BoolProperty(
        name="Symmetrize",
        description="Mirror one side of the clothing to the other after fitting",
        default=False,
    )
    symmetrize_axis: EnumProperty(
        name="Axis",
        description="Which side to mirror from and to",
        items=[
            ('POSITIVE_X', "+X to -X", "Mirror positive X side to negative X"),
            ('NEGATIVE_X', "-X to +X", "Mirror negative X side to positive X"),
            ('POSITIVE_Y', "+Y to -Y", "Mirror positive Y side to negative Y"),
            ('NEGATIVE_Y', "-Y to +Y", "Mirror negative Y side to positive Y"),
            ('POSITIVE_Z', "+Z to -Z", "Mirror positive Z side to negative Z"),
            ('NEGATIVE_Z', "-Z to +Z", "Mirror negative Z side to positive Z"),
        ],
        default='POSITIVE_X',
    )

    post_laplacian: BoolProperty(
        name="Laplacian Smooth",
        description="Apply an extra smoothing pass after fitting to clean up small surface irregularities",
        default=False,
        update=_on_smooth_mod_update,
    )
    laplacian_factor: FloatProperty(
        name="Laplacian Factor",
        description="How strong the extra smoothing pass is",
        default=0.25,
        min=0.0,
        max=10.0,
        update=_on_smooth_mod_update,
    )
    laplacian_iterations: IntProperty(
        name="Laplacian Iterations",
        description="How many extra smoothing passes to apply",
        default=1,
        min=1,
        max=50,
        update=_on_smooth_mod_update,
    )

    # -- Preserve group (optional) --

    preserve_group: EnumProperty(
        name="Preserve Group",
        description="Vertex group that will not be fitted to the body. These vertices will gently follow nearby fitted areas instead.",
        items=_preserve_group_items,
    )
    follow_strength: FloatProperty(
        name="Follow Strength",
        description="How much the preserved vertices follow the movement of surrounding fitted areas",
        default=1.0,
        min=0.0,
        max=1.0,
        update=_on_preview_prop_update,
    )

    cleanup: BoolProperty(
        name="Replace Previous",
        description="Clear any previous fit results before running a new fit",
        default=True,
    )

    # -- Advanced adjustments --

    show_advanced: BoolProperty(
        name="Advanced Settings",
        default=False,
    )

    disp_smooth_passes: IntProperty(
        name="Smooth Passes",
        description="Passes to smooth out sharp pinches in tight areas (e.g. between legs). Higher = smoother.",
        default=15,
        min=0,
        max=50,
        update=_on_preview_prop_update,
    )
    disp_smooth_threshold: FloatProperty(
        name="Gradient Threshold",
        description="Sensitivity for crease detection. Lower values smooth out even gentle pinches; higher values only fix obvious sharp creases.",
        default=2.0,
        min=0.5,
        max=10.0,
        step=1,
        update=_on_preview_prop_update,
    )
    disp_smooth_min: FloatProperty(
        name="Min Smooth Blend",
        description="Smoothing strength in flat areas. Keep low to preserve clothing surface detail.",
        default=0.05,
        min=0.0,
        max=1.0,
        step=1,
        update=_on_preview_prop_update,
    )
    disp_smooth_max: FloatProperty(
        name="Max Smooth Blend",
        description="Smoothing strength at sharp crease areas. Higher softens them more.",
        default=0.80,
        min=0.0,
        max=1.0,
        step=1,
        update=_on_preview_prop_update,
    )
    follow_neighbors: IntProperty(
        name="Follow Neighbors",
        description="How wide an area the preserved vertices look at when deciding how to move. Higher values produce a smoother follow at the boundary.",
        default=8,
        min=1,
        max=64,
        update=_on_preview_prop_update,
    )

    # -- Offset fine-tuning groups --

    offset_groups: CollectionProperty(
        name="Offset Groups",
        type=EFitOffsetGroup,
        description="Per-vertex-group offset influence overrides",
    )

    # -- Developer / update-testing overrides --

    dev_local_zip: StringProperty(
        name="Local Zip",
        description="Local zip file to install instead of the GitHub download in dev testing mode",
        default="",
    )
    dev_override_newer: BoolProperty(
        name="Force: GitHub is newer",
        description="Treat GitHub version as newer than current regardless of actual versions",
        default=False,
    )
    dev_override_uptodate: BoolProperty(
        name="Force: Already up to date",
        description="Treat current version as up to date regardless of actual versions",
        default=False,
    )
