# properties.py
# Blender PropertyGroup definitions for Elastic Clothing Fit.
# EFitExclusiveGroup is a single vertex group entry used in the EVGF exclusive groups list.
# EFitOffsetGroup is a single vertex-group/influence pair used in a collection.
# EFitProperties holds all user-facing settings for the add-on.
# Update callbacks are routed through the state handler registry so this module
# does not import from preview.py.

import bpy
from bpy.props import (
    PointerProperty, FloatProperty, IntProperty, BoolProperty,
    EnumProperty, CollectionProperty, StringProperty,
)
from bpy.types import PropertyGroup

from . import state
from .state import _mesh_poll, _armature_poll

# Shim lambdas that delegate to registered handlers at call time.
# __init__.py registers the actual preview functions after all modules are loaded.
def _on_tab_change(self, context):
    state.call_handler('tab_change', self, context)

def _on_preview_prop_update(self, context):
    state.call_handler('preview_prop_update', self, context)

def _on_smooth_mod_update(self, context):
    state.call_handler('smooth_mod_update', self, context)

def _on_offset_group_influence_update(self, context):
    state.call_handler('offset_group_influence_update', self, context)

def _on_offset_group_name_update(self, context):
    state.call_handler('offset_group_name_update', self, context)

def _on_show_merge_armatures(self, context):
    # Auto-populate Base and To Merge pickers when section is first expanded.
    if not self.show_merge_armatures or context is None:
        return
    if self.merge_source_armature is not None or self.merge_target_armature is not None:
        return
    armatures = sorted(
        [o for o in context.scene.objects if o.type == 'ARMATURE'],
        key=lambda o: o.name,
    )
    if len(armatures) >= 1:
        self.merge_source_armature = armatures[0]
    if len(armatures) >= 2:
        self.merge_target_armature = armatures[1]

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


class EFitArmatureEntry(PropertyGroup):
    """A single armature entry for the display settings target list."""
    armature: PointerProperty(
        name="Armature",
        type=bpy.types.Object,
        poll=_armature_poll,
        description="Armature to apply display settings to",
    )


class EFitProperties(PropertyGroup):

    # -- Tab and section collapse state --

    ui_tab: EnumProperty(
        name="Tab",
        description="Switch between fitting modes and the updater",
        items=[
            ('FULL',      "Full Mesh Fit", "Fit the entire clothing mesh to the body"),
            ('EXCLUSIVE', "Exclusive Fit", "Fit only selected vertex groups"),
            ('TOOLS',     "Tools",         "Armature and mesh utilities"),
            ('UPDATE',    "Update",        "Check for and install updates"),
        ],
        default='FULL',
        update=_on_tab_change,
    )

    show_fit_settings: BoolProperty(
        name="Fit Settings",
        default=False,
    )
    show_shape_preservation: BoolProperty(
        name="Shape Preservation",
        default=False,
    )
    show_preserve_group: BoolProperty(
        name="Preserve Group",
        default=False,
    )
    show_proximity_falloff: BoolProperty(
        name="Proximity Falloff",
        default=False,
    )
    show_displacement_smoothing: BoolProperty(
        name="Displacement Smoothing",
        default=False,
    )
    show_offset_fine_tuning: BoolProperty(
        name="Offset Fine Tuning",
        default=False,
    )
    show_misc: BoolProperty(
        name="Misc",
        default=False,
    )
    show_armature_display: BoolProperty(
        name="Armature Display",
        default=False,
    )
    show_merge_armatures: BoolProperty(
        name="Merge Armatures",
        default=False,
        update=_on_show_merge_armatures,
    )
    show_mesh_split: BoolProperty(
        name="Mesh Split",
        default=False,
    )
    show_mesh_join: BoolProperty(
        name="Mesh Join",
        default=False,
    )

    armature_display_targets: CollectionProperty(
        name="Armature Display Targets",
        type=EFitArmatureEntry,
        description="Armatures to apply display settings to",
    )

    armature_display_type: EnumProperty(
        name="Display As",
        description="How the selected armature(s) are drawn in the viewport",
        items=[
            ('WIRE',       "Wire",       ""),
            ('SOLID',      "Solid",      ""),
            ('BBONE',      "B-Bone",     ""),
            ('ENVELOPE',   "Envelope",   ""),
            ('STICK',      "Stick",      ""),
            ('OCTAHEDRAL', "Octahedral", ""),
        ],
        default='STICK',
    )
    armature_show_in_front: BoolProperty(
        name="In Front",
        description="Draw the armature in front of other objects",
        default=False,
    )

    merge_source_armature: PointerProperty(
        name="Base",
        type=bpy.types.Object,
        poll=_armature_poll,
        description="Base armature that stays after the merge",
    )
    merge_target_armature: PointerProperty(
        name="To Merge",
        type=bpy.types.Object,
        poll=_armature_poll,
        description="Armature to merge into the base",
    )
    merge_bones: BoolProperty(
        name="Merge Bones",
        description="Combine all bones into a single armature",
        default=True,
    )
    merge_align_first: BoolProperty(
        name="Align Before Merge",
        description="Scale and translate source armature to match target before merging",
        default=False,
    )

    # -- Mesh split / join tool properties --

    mesh_split_mode: EnumProperty(
        name="Split By",
        description="How to separate the mesh into multiple objects",
        items=[
            ('LOOSE_PARTS',    "Loose Parts",    "One object per disconnected mesh island"),
            ('BY_MATERIAL',    "By Material",    "One object per material slot"),
            ('BY_VERTEX_GROUP',"By Vertex Group","One object for the named group, one for the rest"),
        ],
        default='LOOSE_PARTS',
    )
    mesh_split_group: StringProperty(
        name="Vertex Group",
        description="Vertex group to split out (used when Split By is set to By Vertex Group)",
        default="",
    )
    mesh_join_merge: BoolProperty(
        name="Merge by Distance",
        description="After joining, merge vertices within the distance threshold",
        default=False,
    )
    mesh_join_threshold: FloatProperty(
        name="Merge Distance",
        description="Vertices closer than this distance are merged after joining",
        default=0.001,
        min=0.0,
        max=0.1,
        precision=4,
        subtype='DISTANCE',
    )

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

    use_proxy_hull: BoolProperty(
        name="Hull Fit",
        description=(
            "Build a convex-hull proxy of the body before fitting. "
            "Fills concave regions like the crotch and inner thigh so clothing "
            "conforms to the body center instead of being pulled toward individual legs. "
            "Disable if it degrades results on your specific mesh."
        ),
        default=False,
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

    # -- Proximity falloff --

    use_proximity_falloff: BoolProperty(
        name="Proximity Falloff",
        description="Reduce fit pull for vertices farther from the body, preserving volume in loose areas like puffy sleeves or skirts",
        default=False,
        update=_on_preview_prop_update,
    )
    proximity_mode: EnumProperty(
        name="Mode",
        description="When to measure cloth-to-body distances for the falloff",
        items=[
            ('PRE_FIT',         "Pre-Fit",         "Measure distances from original clothing positions"),
            ('POST_SHRINKWRAP', "Post Shrinkwrap",  "Measure distances after the shrinkwrap proxy is applied"),
        ],
        default='PRE_FIT',
    )
    proximity_start: FloatProperty(
        name="Start Distance",
        description="Clothing vertices closer than this to the body receive full fit pull (weight 1.0)",
        default=0.0,
        min=0.0,
        max=1.0,
        step=0.1,
        precision=4,
        subtype='DISTANCE',
        update=_on_preview_prop_update,
    )
    proximity_end: FloatProperty(
        name="End Distance",
        description="Clothing vertices farther than this from the body receive no fit pull (weight 0.0)",
        default=0.05,
        min=0.001,
        max=1.0,
        step=0.1,
        precision=4,
        subtype='DISTANCE',
        update=_on_preview_prop_update,
    )
    proximity_curve: EnumProperty(
        name="Curve",
        description="Shape of the falloff curve between Start and End distances",
        items=[
            ('LINEAR', "Linear", "Straight linear falloff"),
            ('SMOOTH', "Smooth", "Smooth S-curve falloff (recommended)"),
            ('SHARP',  "Sharp",  "Quick drop-off close to the body"),
            ('ROOT',   "Root",   "Gradual drop-off, stays full longer"),
        ],
        default='SMOOTH',
        update=_on_preview_prop_update,
    )

    # -- Offset fine-tuning groups --

    offset_groups: CollectionProperty(
        name="Offset Groups",
        type=EFitOffsetGroup,
        description="Per-vertex-group offset influence overrides",
    )

    # -- Update restart options (shown inline when a download is ready) --

    update_save_file: BoolProperty(
        name="Save current file before restarting",
        default=True,
    )
    update_reopen_file: BoolProperty(
        name="Reopen file after update",
        default=True,
    )

    # -- Update channel --

    use_nightly_channel: BoolProperty(
        name="Nightly Dev Build (Possibly Unstable)",
        description=(
            "Check for and install nightly development builds instead of stable releases. "
            "Nightly builds may contain bugs and instability."
        ),
        default=False,
    )

    # -- Dev mode update server (only visible when _dev_mode marker file exists) --

    dev_update_url: StringProperty(
        name="Update Server URL",
        description="Base URL for update checks (dev mode only)",
        default="http://localhost:8198",
    )
