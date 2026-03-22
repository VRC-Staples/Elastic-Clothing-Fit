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
from bpy.types import AddonPreferences, PropertyGroup

from . import state
from .state import _mesh_poll, _armature_poll

# Shim lambdas that delegate to registered handlers at call time.
# __init__.py registers the actual preview functions after all modules are loaded.
def _on_tab_change(self, context):
    state.call_handler('tab_change', self, context)

def _on_exclusive_mode_toggle(self, context):
    """Sync use_exclusive_mode bool to the fit_mode enum."""
    self.fit_mode = 'EXCLUSIVE' if self.use_exclusive_mode else 'FULL'

def _on_preview_prop_update(self, context):
    state.call_handler('preview_prop_update', self, context)

def _on_smooth_mod_update(self, context):
    state.call_handler('smooth_mod_update', self, context)

def _on_offset_group_influence_update(self, context):
    state.call_handler('offset_group_influence_update', self, context)

def _on_offset_group_name_update(self, context):
    state.call_handler('offset_group_name_update', self, context)

def _on_proximity_group_update(self, context):
    state.call_handler('proximity_group_update', self, context)

def _on_proximity_group_name_update(self, context):
    state.call_handler('proximity_group_name_update', self, context)

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

# StringProperty search callbacks for vertex group pickers.
# These return autocomplete candidates for Blender's search UI.
# StringProperty stores the name directly — immune to index-drift when groups
# are added, removed, or reordered on the clothing mesh.

def _preserve_group_search(self, context, edit_text):
    # self is an EFitProperties instance.
    # Reversed so the list appears bottom-to-top relative to Blender's
    # internal vertex-group order.  StringProperty stores the name, so
    # display order has no effect on the stored value or on index drift.
    if self.clothing_obj and self.clothing_obj.type == 'MESH':
        return [vg.name for vg in reversed(self.clothing_obj.vertex_groups)
                if edit_text.lower() in vg.name.lower()]
    return []


def _group_name_search(self, context, edit_text):
    # self is an EFitOffsetGroup / EFitExclusiveGroup / EFitProximityGroup instance.
    # Reach the clothing object through the scene; guard against missing context.
    # Reversed to match _preserve_group_search display order.
    if context is None:
        return []
    p = context.scene.efit_props
    if p.clothing_obj and p.clothing_obj.type == 'MESH':
        return [vg.name for vg in reversed(p.clothing_obj.vertex_groups)
                if edit_text.lower() in vg.name.lower()]
    return []


def _resolve_vg_name(value):
    """Return the real vertex group name, or '' if empty/unset."""
    return value or ""


class EFitProximityGroup(PropertyGroup):
    """One vertex group / falloff settings pair for per-group proximity fine-tuning."""
    group_name: StringProperty(
        name="Vertex Group",
        description="Vertex group with its own proximity falloff settings",
        default="",
        search=_group_name_search,
        update=_on_proximity_group_name_update,
    )
    proximity_mode: EnumProperty(
        name="Mode",
        description="When to measure how far the clothing is from the body for this group",
        items=[
            ('PRE_FIT',         "Pre-Fit",         "Use the original clothing position before any fitting"),
            ('POST_SHRINKWRAP', "Post Shrinkwrap",  "Use the clothing position after the initial wrap to the body"),
        ],
        default='PRE_FIT',
        update=_on_proximity_group_update,
    )
    proximity_start: FloatProperty(
        name="Start Distance",
        description="Parts of this group closer than this to the body are fully fitted",
        default=0.0,
        min=0.0,
        max=1.0,
        step=0.1,
        precision=4,
        subtype='DISTANCE',
        update=_on_proximity_group_update,
    )
    proximity_end: FloatProperty(
        name="End Distance",
        description="Parts of this group farther than this from the body are not fitted at all",
        default=0.05,
        min=0.001,
        max=1.0,
        step=0.1,
        precision=4,
        subtype='DISTANCE',
        update=_on_proximity_group_update,
    )
    proximity_curve: EnumProperty(
        name="Curve",
        description="How the fit strength fades out between Start and End for this group",
        items=[
            ('LINEAR', "Linear", "Straight even fade"),
            ('SMOOTH', "Smooth", "Gentle S-curve fade (recommended)"),
            ('SHARP',  "Sharp",  "Drops off quickly near the body"),
            ('ROOT',   "Root",   "Stays strong longer, fades late"),
        ],
        default='SMOOTH',
        update=_on_proximity_group_update,
    )


class EFitExclusiveGroup(PropertyGroup):
    """A single vertex group entry for Exclusive Vertex Group Fit mode."""
    group_name: StringProperty(
        name="Vertex Group",
        description="Vertex group to fit to the body",
        default="",
        search=_group_name_search,
    )
    influence: IntProperty(
        name="Influence",
        description="Controls the gap from the body for this group. 100 is normal, lower pulls closer, higher pushes farther out",
        default=100,
        min=0,
        max=1000,
        subtype='PERCENTAGE',
        update=_on_offset_group_influence_update,
    )


class EFitOffsetGroup(PropertyGroup):
    """One vertex group / influence pair for per-group offset fine-tuning."""
    group_name: StringProperty(
        name="Vertex Group",
        description="Vertex group to adjust the offset for",
        default="",
        search=_group_name_search,
        update=_on_offset_group_name_update,
    )
    influence: IntProperty(
        name="Influence",
        description="Controls the gap from the body for this group. 100 is normal, lower pulls closer, higher pushes farther out",
        default=100,
        min=0,
        max=1000,
        subtype='PERCENTAGE',
        update=_on_offset_group_influence_update,
    )


class EFitProperties(PropertyGroup):

    # -- Tab and section collapse state --

    ui_tab: EnumProperty(
        name="Tab",
        description="Switch between fitting, tools, and updates",
        items=[
            ('FULL',   "Fit",    "Fit clothing to the body"),
            ('TOOLS',  "Tools",  "Armature and mesh utilities"),
            ('UPDATE', "Update", "Check for and install updates"),
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
        name="Reset & Cleanup",
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

    armature_display_type: EnumProperty(
        name="Display As",
        description="How the selected armature is drawn in the viewport",
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
        description="Scale and reposition the source armature to match the target before merging",
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
        description="After joining, merge nearby vertices that overlap within the threshold",
        default=False,
    )
    mesh_join_threshold: FloatProperty(
        name="Merge Distance",
        description="Vertices closer together than this are merged into one after joining",
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
        description="The avatar or body mesh to fit clothing onto",
    )
    clothing_obj: PointerProperty(
        name="Clothing",
        type=bpy.types.Object,
        poll=_mesh_poll,
        description="The clothing mesh to be fitted",
    )

    fit_mode: EnumProperty(
        name="Fit Mode",
        description="Choose whether to fit the whole clothing or only specific parts",
        items=[
            ('FULL',      "Full Mesh Fit",             "Fit the entire clothing mesh to the body"),
            ('EXCLUSIVE', "Exclusive Vertex Group Fit", "Fit only the chosen vertex groups and leave everything else untouched"),
        ],
        default='FULL',
    )
    use_exclusive_mode: BoolProperty(
        name="Exclusive Vertex Group Mode",
        description="Fit only the listed vertex groups instead of the full mesh. Parts outside those groups stay in place",
        default=False,
        update=_on_exclusive_mode_toggle,
    )
    exclusive_groups: CollectionProperty(
        name="Exclusive Groups",
        type=EFitExclusiveGroup,
        description="Vertex groups to fit when using Exclusive mode",
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
        description="Detail level of the temporary mesh used during fitting. Higher is more accurate but slower",
        default=300000,
        min=10000,
        max=2000000,
        step=50000,
    )

    preserve_uvs: BoolProperty(
        name="Preserve UVs",
        description="Keep UV maps unchanged after fitting. Leave this on unless you have a specific reason not to",
        default=True,
    )

    use_proxy_hull: BoolProperty(
        name="Hull Fit",
        description=(
            "Wrap a simplified shell around the body before fitting. "
            "Helps in areas like the crotch and inner thighs where clothing "
            "might otherwise get pulled between the legs. "
            "Turn off if it makes your specific garment look worse."
        ),
        default=False,
    )

    smooth_factor: FloatProperty(
        name="Elastic Strength",
        description="How much the clothing tries to keep its original shape after being fitted. Higher values preserve the silhouette more",
        default=0.75,
        min=0.0,
        max=2.0,
        update=_on_smooth_mod_update,
    )
    smooth_iterations: IntProperty(
        name="Elastic Iterations",
        description="How many times shape correction runs. More iterations keep the original silhouette better",
        default=10,
        min=0,
        max=100,
        update=_on_smooth_mod_update,
    )

    post_laplacian: BoolProperty(
        name="Laplacian Smooth",
        description="Run an extra smoothing pass after fitting to clean up small bumps and wrinkles",
        default=False,
        update=_on_smooth_mod_update,
    )
    laplacian_factor: FloatProperty(
        name="Laplacian Factor",
        description="Strength of the extra smoothing pass",
        default=0.25,
        min=0.0,
        max=10.0,
        update=_on_smooth_mod_update,
    )
    laplacian_iterations: IntProperty(
        name="Laplacian Iterations",
        description="Number of extra smoothing passes to run",
        default=1,
        min=1,
        max=50,
        update=_on_smooth_mod_update,
    )

    # -- Preserve group (optional) --

    preserve_group: StringProperty(
        name="Preserve Group",
        description="Vertex group to keep unfitted. These areas will gently follow the movement of nearby fitted parts instead",
        default="",
        search=_preserve_group_search,
    )
    follow_strength: FloatProperty(
        name="Follow Strength",
        description="How closely preserved areas follow the movement of nearby fitted parts",
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
        description="Number of passes to smooth out pinching in tight areas like between the legs. More passes = smoother",
        default=15,
        min=0,
        max=50,
        update=_on_preview_prop_update,
    )
    disp_smooth_threshold: FloatProperty(
        name="Gradient Threshold",
        description="How sensitive crease detection is. Lower catches gentle pinches, higher only fixes obvious sharp creases",
        default=2.0,
        min=0.5,
        max=10.0,
        step=1,
        update=_on_preview_prop_update,
    )
    disp_smooth_min: FloatProperty(
        name="Min Smooth Blend",
        description="Smoothing in flat areas. Keep this low to preserve surface detail on the clothing",
        default=0.05,
        min=0.0,
        max=1.0,
        step=1,
        update=_on_preview_prop_update,
    )
    disp_smooth_max: FloatProperty(
        name="Max Smooth Blend",
        description="Smoothing at sharp creases. Higher values soften them more",
        default=0.80,
        min=0.0,
        max=1.0,
        step=1,
        update=_on_preview_prop_update,
    )
    follow_neighbors: IntProperty(
        name="Follow Neighbors",
        description="How wide an area preserved parts look at when following. Higher values give a smoother blend at the boundary",
        default=8,
        min=1,
        max=64,
        update=_on_preview_prop_update,
    )

    # -- Proximity falloff --

    use_proximity_falloff: BoolProperty(
        name="Proximity Falloff",
        description="Reduce fit strength for parts farther from the body, keeping volume in loose areas like puffy sleeves or skirts",
        default=False,
        update=_on_preview_prop_update,
    )
    proximity_mode: EnumProperty(
        name="Mode",
        description="When to measure how far the clothing is from the body",
        items=[
            ('PRE_FIT',         "Pre-Fit",         "Use the original clothing position before any fitting"),
            ('POST_SHRINKWRAP', "Post Shrinkwrap",  "Use the clothing position after the initial wrap to the body"),
        ],
        default='PRE_FIT',
    )
    proximity_start: FloatProperty(
        name="Start Distance",
        description="Clothing closer than this to the body is fully fitted",
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
        description="Clothing farther than this from the body is not fitted at all",
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
        description="How the fit strength fades out between Start and End distances",
        items=[
            ('LINEAR', "Linear", "Straight even fade"),
            ('SMOOTH', "Smooth", "Gentle S-curve fade (recommended)"),
            ('SHARP',  "Sharp",  "Drops off quickly near the body"),
            ('ROOT',   "Root",   "Stays strong longer, fades late"),
        ],
        default='SMOOTH',
        update=_on_preview_prop_update,
    )

    # Per-group proximity falloff fine-tuning.
    # When use_proximity_group_tuning is True and proximity_groups is non-empty,
    # each group's vertices use that group's falloff settings.
    # When True but no groups added, the global controls still apply.
    # Ungrouped vertices always get weight 1.0 (no falloff reduction).
    use_proximity_group_tuning: BoolProperty(
        name="Per-Group Fine Tuning",
        description="Give individual vertex groups their own proximity falloff settings",
        default=False,
    )
    proximity_groups: CollectionProperty(
        name="Proximity Groups",
        type=EFitProximityGroup,
        description="Per-group proximity falloff overrides",
    )

    # -- Offset fine-tuning groups --

    offset_groups: CollectionProperty(
        name="Offset Groups",
        type=EFitOffsetGroup,
        description="Per-group offset influence overrides",
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


# ---------------------------------------------------------------------------
# Addon preferences
# ---------------------------------------------------------------------------

def _on_developer_mode_update(self, context):
    """Write the new developer_mode value to the panels module-level cache.

    This update= callback fires when the user toggles Developer Mode in
    preferences, keeping panels._cached_developer_mode in sync without
    requiring panels._draw_update_tab to traverse context.preferences.addons
    on every redraw.

    Import is deferred to avoid a circular dependency at module load time
    (properties.py → panels.py → properties.py).
    """
    try:
        from . import panels as _panels
        _panels._cached_developer_mode = bool(self.developer_mode)
    except Exception:
        pass


class EFitAddonPreferences(AddonPreferences):
    """Preferences registered under Edit > Preferences > Add-ons > Elastic Clothing Fit."""
    bl_idname = "elastic_fit"

    developer_mode: BoolProperty(
        name="Developer Mode",
        description=(
            "Enables developer-facing options such as the Nightly Dev Build channel "
            "and the local update server URL field."
        ),
        default=False,
        update=_on_developer_mode_update,
    )

    def draw(self, context):
        self.layout.prop(self, "developer_mode")
