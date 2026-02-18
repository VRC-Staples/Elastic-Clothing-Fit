# ============================================================================
#  Elastic Clothing Fit — Blender Add-on
# ============================================================================
#
#  Proxy-based clothing fitting with UV preservation and live preview.
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
    "version": (0, 2, 16),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Elastic Fit",
    "description": "Proxy-based clothing fitting with live preview and UV preservation",
    "category": "3D View",
}

import bpy
import math
import mathutils
from mathutils.kdtree import KDTree
from bpy.props import (
    PointerProperty, FloatProperty, IntProperty, BoolProperty,
    StringProperty, EnumProperty,
)
from bpy.types import PropertyGroup, Panel, Operator

# Sidebar tab name — overridden by __init__.py when used as part of a package
PANEL_CATEGORY = "Elastic Fit"

EFIT_PREFIX = "EFit_"

# Module-level cache for live preview.  Populated by the fit operator
# when entering preview mode, cleared on Apply/Cancel.
_efit_cache = {}
_efit_updating = False  # guard against recursive update callbacks


def _mesh_poll(self, obj):
    """Filter for PointerProperty eyedropper — only allow mesh objects."""
    return obj.type == 'MESH'


def _efit_preview_update(context):
    """Re-apply displacements from cached data using current slider values."""
    global _efit_updating
    if _efit_updating:
        return
    c = _efit_cache
    if not c:
        return

    _efit_updating = True
    try:
        p = context.scene.efit_props
        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            return
        all_originals = c['all_originals']
        cloth_displacements = c['cloth_displacements']
        cloth_adj = c['cloth_adj']
        fitted_indices = c['fitted_indices']
        preserved_indices = c['preserved_indices']
        has_preserve = c['has_preserve']
        fit = p.fit_amount

        # Adjust displacements for offset change
        offset_delta = p.offset - c.get('original_offset', p.offset)
        cloth_body_normals = c.get('cloth_body_normals', {})

        adjusted_displacements = {}
        for vi in fitted_indices:
            d = cloth_displacements[vi].copy()
            if offset_delta != 0.0 and vi in cloth_body_normals:
                d += cloth_body_normals[vi] * offset_delta
            adjusted_displacements[vi] = d

        # Re-run adaptive smoothing with current params
        smoothed = {vi: adjusted_displacements[vi].copy() for vi in fitted_indices}

        ds_passes = p.disp_smooth_passes
        ds_thresh_mult = p.disp_smooth_threshold
        ds_min = p.disp_smooth_min
        ds_max = p.disp_smooth_max

        for _pass in range(ds_passes):
            gradient = {}
            for vi in fitted_indices:
                neighbors = cloth_adj[vi]
                if not neighbors:
                    gradient[vi] = 0.0
                    continue
                d = smoothed[vi]
                max_diff = 0.0
                for ni in neighbors:
                    diff = (d - smoothed[ni]).length
                    if diff > max_diff:
                        max_diff = diff
                gradient[vi] = max_diff

            grad_values = sorted(gradient.values())
            median_grad = grad_values[len(grad_values) // 2] if grad_values else 0.0

            new_smoothed = {}
            for vi in fitted_indices:
                neighbors = cloth_adj[vi]
                if not neighbors:
                    new_smoothed[vi] = smoothed[vi].copy()
                    continue
                g = gradient[vi]
                threshold = max(median_grad * ds_thresh_mult, 0.0001)
                if g <= threshold:
                    blend = ds_min
                else:
                    t = min(1.0, (g - threshold) / max(threshold, 0.0001))
                    blend = ds_min + (ds_max - ds_min) * t
                avg = mathutils.Vector((0.0, 0.0, 0.0))
                for ni in neighbors:
                    avg += smoothed[ni]
                avg /= len(neighbors)
                new_smoothed[vi] = smoothed[vi] * (1.0 - blend) + avg * blend
            smoothed = new_smoothed

        for vi in fitted_indices:
            cloth.data.vertices[vi].co = all_originals[vi] + smoothed[vi] * fit

        if has_preserve and preserved_indices and fitted_indices:
            strength = p.follow_strength
            if strength > 0.0:
                current_positions = {}
                for vi in fitted_indices:
                    current_positions[vi] = cloth.data.vertices[vi].co.copy()

                kd_follow = c.get('kd_follow')
                if kd_follow is None:
                    kd_follow = KDTree(len(fitted_indices))
                    for i, vi in enumerate(fitted_indices):
                        kd_follow.insert(all_originals[vi], i)
                    kd_follow.balance()
                    c['kd_follow'] = kd_follow

                K_follow = min(p.follow_neighbors, len(fitted_indices))
                for vi in preserved_indices:
                    rest_pos = all_originals[vi]
                    neighbors = kd_follow.find_n(rest_pos, K_follow)
                    total_disp = mathutils.Vector((0.0, 0.0, 0.0))
                    total_weight = 0.0
                    for co, idx, dist in neighbors:
                        ni = fitted_indices[idx]
                        disp = current_positions[ni] - all_originals[ni]
                        w = 1.0 / max(dist, 0.0001)
                        total_disp += disp * w
                        total_weight += w
                    if total_weight > 0.0:
                        avg_disp = total_disp / total_weight
                        cloth.data.vertices[vi].co = rest_pos + avg_disp * strength

        cloth.data.update()
        if context.screen:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass
    finally:
        _efit_updating = False


def _on_preview_prop_update(self, context):
    """Property update callback — triggers preview recompute."""
    if _efit_cache:
        _efit_preview_update(context)


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

    fit_amount: FloatProperty(
        name="Fit Amount",
        description="How far clothing moves toward the body (0 = none, 0.5 = halfway, 1 = full snap)",
        default=0.65,
        min=0.0,
        max=1.0,
        update=_on_preview_prop_update,
    )

    offset: FloatProperty(
        name="Offset",
        description="Gap between fitted surface and body surface",
        default=0.001,
        min=0.0,
        max=0.5,
        step=0.01,
        precision=4,
        subtype='DISTANCE',
        update=_on_preview_prop_update,
    )

    proxy_triangles: IntProperty(
        name="Proxy Resolution",
        description="Target triangle count for the proxy mesh (higher = smoother, slower)",
        default=300000,
        min=10000,
        max=2000000,
        step=50000,
    )

    preserve_uvs: BoolProperty(
        name="Preserve UVs",
        description="Restore original UV coordinates after fitting (prevents UV distortion at edges)",
        default=True,
    )

    smooth_factor: FloatProperty(
        name="Elastic Strength",
        description="How strongly the mesh preserves its original shape after fitting",
        default=0.75,
        min=0.0,
        max=2.0,
    )
    smooth_iterations: IntProperty(
        name="Elastic Iterations",
        description="Number of corrective smooth passes",
        default=10,
        min=0,
        max=100,
    )

    # -- Post-fit options --

    post_symmetrize: BoolProperty(
        name="Symmetrize",
        description="Symmetrize the mesh after fitting (mirrors +X to -X)",
        default=False,
    )
    symmetrize_axis: EnumProperty(
        name="Axis",
        description="Symmetry axis and direction",
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
        description="Apply Laplacian smoothing after fitting to reduce noise while preserving shape",
        default=False,
    )
    laplacian_factor: FloatProperty(
        name="Laplacian Factor",
        description="Strength of Laplacian smoothing",
        default=0.25,
        min=0.0,
        max=10.0,
    )
    laplacian_iterations: IntProperty(
        name="Laplacian Iterations",
        description="Number of Laplacian smooth passes",
        default=1,
        min=1,
        max=50,
    )

    # -- Preserve group (optional) --

    preserve_group: StringProperty(
        name="Preserve Group",
        description="Vertex group excluded from fit (follows via displacement transfer)",
        default="",
    )
    follow_strength: FloatProperty(
        name="Follow Strength",
        description="How closely preserved vertices track the fitted mesh",
        default=1.0,
        min=0.0,
        max=1.0,
        update=_on_preview_prop_update,
    )

    cleanup: BoolProperty(
        name="Replace Previous",
        description="Remove existing Elastic Fit modifiers before adding new ones",
        default=True,
    )

    # -- Advanced adjustments --

    show_advanced: BoolProperty(
        name="Show Advanced Adjustments",
        default=False,
    )

    disp_smooth_passes: IntProperty(
        name="Smooth Passes",
        description="Number of adaptive displacement smoothing iterations (higher = smoother concave areas)",
        default=15,
        min=0,
        max=50,
        update=_on_preview_prop_update,
    )
    disp_smooth_threshold: FloatProperty(
        name="Gradient Threshold",
        description="Multiplier for median gradient — controls what counts as a 'sharp jump' (lower = more aggressive)",
        default=2.0,
        min=0.5,
        max=10.0,
        update=_on_preview_prop_update,
    )
    disp_smooth_min: FloatProperty(
        name="Min Smooth Blend",
        description="Smoothing blend for low-gradient (smooth) areas",
        default=0.05,
        min=0.0,
        max=1.0,
        update=_on_preview_prop_update,
    )
    disp_smooth_max: FloatProperty(
        name="Max Smooth Blend",
        description="Smoothing blend for high-gradient (creased) areas",
        default=0.80,
        min=0.0,
        max=1.0,
        update=_on_preview_prop_update,
    )
    follow_neighbors: IntProperty(
        name="Follow Neighbors",
        description="Number of nearest fitted vertices used to compute preserved vertex follow",
        default=8,
        min=1,
        max=32,
        update=_on_preview_prop_update,
    )


# -- Elastic Fit Helpers --

def _remove_efit(obj):
    """Remove all EFit_ modifiers and restore preserved vertex positions."""
    global _efit_cache
    _efit_cache.clear()

    for m in [m for m in obj.modifiers if m.name.startswith(EFIT_PREFIX)]:
        obj.modifiers.remove(m)

    flat = obj.get("_efit_originals")
    if flat is not None:
        verts = obj.data.vertices
        n = len(verts)
        for vi in range(n):
            idx = vi * 3
            if idx + 2 < len(flat):
                verts[vi].co = mathutils.Vector((flat[idx], flat[idx+1], flat[idx+2]))
        del obj["_efit_originals"]
        obj.data.update()


def _calc_subdivisions(current_tris, target_tris):
    """How many subdivision levels to reach the target triangle count.
    Each level multiplies by ~4.
    """
    if current_tris <= 0:
        return 1
    ratio = target_tris / current_tris
    if ratio <= 1:
        return 0
    levels = math.log(ratio) / math.log(4)
    return max(1, round(levels))


def _save_uvs(mesh):
    """Snapshot all UV layer data."""
    uv_data = {}
    for uv_layer in mesh.uv_layers:
        coords = []
        for loop in uv_layer.data:
            coords.append(loop.uv.copy())
        uv_data[uv_layer.name] = coords
    return uv_data


def _restore_uvs(mesh, uv_data):
    """Write saved UV coordinates back to the mesh."""
    for layer_name, coords in uv_data.items():
        uv_layer = mesh.uv_layers.get(layer_name)
        if uv_layer is None:
            continue
        for i, loop in enumerate(uv_layer.data):
            if i < len(coords):
                loop.uv = coords[i]


def _has_blockers(obj):
    """Check if the clothing mesh has shape keys or unapplied modifiers
    that would interfere with fitting.
    """
    has_sk = obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 0
    mod_names = [m.name for m in obj.modifiers
                if not m.name.startswith(EFIT_PREFIX) and m.type != 'ARMATURE']
    return has_sk, mod_names


# -- Elastic Fit Operators --

class EFIT_OT_fit(Operator):
    bl_idname = "efit.fit"
    bl_label = "Fit Clothing"
    bl_description = "Fit clothing onto body using a high-poly proxy for smooth deformation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.efit_props
        cloth = p.clothing_obj
        body = p.body_obj

        # -- Validation --
        if not cloth or cloth.type != 'MESH':
            self.report({'ERROR'}, "Select a valid clothing mesh.")
            return {'CANCELLED'}
        if not body or body.type != 'MESH':
            self.report({'ERROR'}, "Select a valid body mesh.")
            return {'CANCELLED'}
        if cloth == body:
            self.report({'ERROR'}, "Clothing and body must be different objects.")
            return {'CANCELLED'}

        # -- Pre-fit blocker check --
        has_sk, blocker_mods = _has_blockers(cloth)
        if has_sk:
            self.report({'ERROR'},
                        "Clothing has shape keys. Use 'Clear Blockers' to remove them first.")
            return {'CANCELLED'}
        if blocker_mods:
            self.report({'ERROR'},
                        f"Clothing has unapplied modifiers: {', '.join(blocker_mods)}. "
                        "Use 'Clear Blockers' to remove them first.")
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Clear any active preview before starting a new fit
        global _efit_cache
        _efit_cache.clear()

        if p.cleanup:
            _remove_efit(cloth)
            for obj in list(bpy.data.objects):
                if obj.name.startswith(f"{EFIT_PREFIX}Proxy"):
                    bpy.data.objects.remove(obj, do_unlink=True)

        # Check preserve group
        preserve_name = (p.preserve_group or "").strip()
        has_preserve = bool(preserve_name and cloth.vertex_groups.get(preserve_name))

        if preserve_name and not cloth.vertex_groups.get(preserve_name):
            self.report({'WARNING'},
                        f"Preserve group '{preserve_name}' not found — skipping.")

        # Save ALL original vertex positions (used for undo and displacement)
        all_originals = {}
        undo_flat = [0.0] * (len(cloth.data.vertices) * 3)
        for v in cloth.data.vertices:
            all_originals[v.index] = v.co.copy()
            idx = v.index * 3
            undo_flat[idx] = v.co.x
            undo_flat[idx+1] = v.co.y
            undo_flat[idx+2] = v.co.z
        cloth["_efit_originals"] = undo_flat

        # ================================================================
        #  Create and subdivide the proxy mesh
        # ================================================================
        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth
        bpy.ops.object.duplicate(linked=False)
        proxy = context.active_object
        proxy.name = f"{EFIT_PREFIX}Proxy"

        # Strip all copied modifiers from the proxy (e.g. armature)
        # so the evaluated proxy matches its rest mesh exactly.
        for m in list(proxy.modifiers):
            proxy.modifiers.remove(m)

        current_tris = sum(max(0, len(f.vertices) - 2)
                        for f in proxy.data.polygons)
        subdiv_levels = _calc_subdivisions(current_tris, p.proxy_triangles)

        if subdiv_levels > 0:
            mod_sub = proxy.modifiers.new("_temp_subdiv", 'SUBSURF')
            mod_sub.levels = subdiv_levels
            mod_sub.render_levels = subdiv_levels
            mod_sub.subdivision_type = 'SIMPLE'

            bpy.ops.object.select_all(action='DESELECT')
            proxy.select_set(True)
            context.view_layer.objects.active = proxy
            bpy.ops.object.modifier_apply(modifier=mod_sub.name)

        actual_tris = sum(max(0, len(f.vertices) - 2)
                        for f in proxy.data.polygons)

        # ================================================================
        #  Classify preserved vs fitted vertices
        # ================================================================
        preserved_indices = []
        fitted_indices = []

        if has_preserve:
            preserve_vg = cloth.vertex_groups[preserve_name]
            for vi in range(len(cloth.data.vertices)):
                try:
                    w = preserve_vg.weight(vi)
                except RuntimeError:
                    w = 0.0
                if w > 0.0:
                    preserved_indices.append(vi)
                else:
                    fitted_indices.append(vi)
        else:
            fitted_indices = list(range(len(cloth.data.vertices)))

        # ================================================================
        #  Shrinkwrap proxy onto body (no filtering)
        # ================================================================
        proxy_pre = [v.co.copy() for v in proxy.data.vertices]

        bpy.ops.object.select_all(action='DESELECT')
        proxy.select_set(True)
        context.view_layer.objects.active = proxy

        mod_sw = proxy.modifiers.new(f"{EFIT_PREFIX}Shrinkwrap", 'SHRINKWRAP')
        mod_sw.target = body
        mod_sw.wrap_method = 'NEAREST_SURFACEPOINT'
        mod_sw.wrap_mode = 'OUTSIDE_SURFACE'
        mod_sw.offset = p.offset

        bpy.ops.object.modifier_apply(modifier=mod_sw.name)

        proxy_post = [v.co.copy() for v in proxy.data.vertices]

        # Zero out displacement for proxy vertices in the preserved area
        # so deformation doesn't bleed into preserved vertices via BVH.
        if has_preserve and preserved_indices:
            kd_preserve = KDTree(len(preserved_indices))
            for i, vi in enumerate(preserved_indices):
                kd_preserve.insert(all_originals[vi], i)
            kd_preserve.balance()

            kd_fitted = KDTree(len(fitted_indices))
            for i, vi in enumerate(fitted_indices):
                kd_fitted.insert(all_originals[vi], i)
            kd_fitted.balance()

            for pi in range(len(proxy_pre)):
                pos = proxy_pre[pi]
                _, _, d_pres = kd_preserve.find(pos)
                _, _, d_fit = kd_fitted.find(pos)

                # If this proxy vert is closer to a preserved clothing vert
                # than a fitted one, suppress its displacement.
                if d_pres < d_fit:
                    proxy_post[pi] = proxy_pre[pi].copy()

        # ================================================================
        #  Transfer displacement via surface interpolation
        # ================================================================
        # Use closest_point_on_mesh + barycentric weights on the proxy's
        # pre-shrinkwrap mesh.  This respects surface topology so vertices
        # across a gap (e.g. between legs) cannot influence each other.
        fit = p.fit_amount

        # Save UVs before modifying geometry
        saved_uvs = None
        if p.preserve_uvs:
            saved_uvs = _save_uvs(cloth.data)

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        # Build a temporary BVHTree from the pre-shrinkwrap data instead.
        from mathutils.bvhtree import BVHTree

        proxy_faces = [tuple(f.vertices) for f in proxy.data.polygons]
        bvh = BVHTree.FromPolygons(proxy_pre, proxy_faces)

        proxy_polys = proxy.data.polygons

        # First pass: compute raw displacement for each fitted vertex
        cloth_displacements = {}
        for vi in fitted_indices:
            v = cloth.data.vertices[vi]
            loc, normal, face_idx, dist = bvh.find_nearest(v.co)

            if face_idx is None:
                cloth_displacements[vi] = mathutils.Vector((0.0, 0.0, 0.0))
                continue

            face = proxy_polys[face_idx]
            fv = list(face.vertices)

            weights = []
            for fi in fv:
                d = (v.co - proxy_pre[fi]).length
                weights.append(1.0 / max(d, 0.00001))
            w_sum = sum(weights)

            avg_disp = mathutils.Vector((0.0, 0.0, 0.0))
            for fi, w in zip(fv, weights):
                avg_disp += (proxy_post[fi] - proxy_pre[fi]) * (w / w_sum)

            cloth_displacements[vi] = avg_disp

        # Compute body surface normals at each fitted clothing vertex
        # (used for live offset adjustment in preview)
        body_faces = [tuple(f.vertices) for f in body.data.polygons]
        body_verts = [v.co.copy() for v in body.data.vertices]
        bvh_body = BVHTree.FromPolygons(body_verts, body_faces)

        cloth_body_normals = {}
        for vi in fitted_indices:
            v = cloth.data.vertices[vi]
            loc, normal, face_idx, dist = bvh_body.find_nearest(v.co)
            if normal is not None:
                cloth_body_normals[vi] = normal.normalized()
            else:
                cloth_body_normals[vi] = mathutils.Vector((0.0, 0.0, 0.0))

        # Build clothing mesh adjacency for fitted vertices
        fitted_set = set(fitted_indices)
        cloth_adj = {vi: [] for vi in fitted_indices}
        for edge in cloth.data.edges:
            a, b = edge.vertices
            if a in fitted_set and b in fitted_set:
                cloth_adj[a].append(b)
                cloth_adj[b].append(a)

        # Adaptive displacement smoothing: smooth aggressively where the
        # displacement field has sharp jumps (the center-line crease in
        # concave areas), and leave smooth areas untouched.
        smoothed = {vi: cloth_displacements[vi].copy() for vi in fitted_indices}

        ds_passes = p.disp_smooth_passes
        ds_thresh_mult = p.disp_smooth_threshold
        ds_min = p.disp_smooth_min
        ds_max = p.disp_smooth_max

        for _pass in range(ds_passes):
            gradient = {}
            for vi in fitted_indices:
                neighbors = cloth_adj[vi]
                if not neighbors:
                    gradient[vi] = 0.0
                    continue
                d = smoothed[vi]
                max_diff = 0.0
                for ni in neighbors:
                    diff = (d - smoothed[ni]).length
                    if diff > max_diff:
                        max_diff = diff
                gradient[vi] = max_diff

            grad_values = sorted(gradient.values())
            median_grad = grad_values[len(grad_values) // 2] if grad_values else 0.0

            new_smoothed = {}
            for vi in fitted_indices:
                neighbors = cloth_adj[vi]
                if not neighbors:
                    new_smoothed[vi] = smoothed[vi].copy()
                    continue

                g = gradient[vi]
                threshold = max(median_grad * ds_thresh_mult, 0.0001)
                if g <= threshold:
                    blend = ds_min
                else:
                    t = min(1.0, (g - threshold) / max(threshold, 0.0001))
                    blend = ds_min + (ds_max - ds_min) * t

                avg = mathutils.Vector((0.0, 0.0, 0.0))
                for ni in neighbors:
                    avg += smoothed[ni]
                avg /= len(neighbors)

                new_smoothed[vi] = smoothed[vi] * (1.0 - blend) + avg * blend
            smoothed = new_smoothed

        # Apply smoothed displacements
        for vi in fitted_indices:
            cloth.data.vertices[vi].co = all_originals[vi] + smoothed[vi] * fit

        cloth.data.update()

        if saved_uvs:
            _restore_uvs(cloth.data, saved_uvs)

        # ================================================================
        #  Delete the proxy mesh
        # ================================================================
        bpy.data.objects.remove(proxy, do_unlink=True)

        # ================================================================
        #  Handle preserved vertices (KDTree follow)
        # ================================================================
        if has_preserve and preserved_indices and fitted_indices:
            strength = p.follow_strength
            if strength > 0.0:
                current_positions = {}
                for vi in fitted_indices:
                    current_positions[vi] = cloth.data.vertices[vi].co.copy()

                kd_follow = KDTree(len(fitted_indices))
                for i, vi in enumerate(fitted_indices):
                    kd_follow.insert(all_originals[vi], i)
                kd_follow.balance()

                K_follow = min(p.follow_neighbors, len(fitted_indices))

                for vi in preserved_indices:
                    rest_pos = all_originals[vi]
                    neighbors = kd_follow.find_n(rest_pos, K_follow)

                    total_disp = mathutils.Vector((0.0, 0.0, 0.0))
                    total_weight = 0.0

                    for co, idx, dist in neighbors:
                        ni = fitted_indices[idx]
                        disp = current_positions[ni] - all_originals[ni]
                        w = 1.0 / max(dist, 0.0001)
                        total_disp += disp * w
                        total_weight += w

                    if total_weight > 0.0:
                        avg_disp = total_disp / total_weight
                        cloth.data.vertices[vi].co = rest_pos + avg_disp * strength

                cloth.data.update()

        # ================================================================
        #  Populate preview cache — slider changes will re-apply from here
        # ================================================================
        _efit_cache = {
            'cloth_name': cloth.name,
            'all_originals': all_originals,
            'cloth_displacements': cloth_displacements,
            'cloth_adj': cloth_adj,
            'fitted_indices': fitted_indices,
            'preserved_indices': preserved_indices,
            'has_preserve': has_preserve,
            'preserve_name': preserve_name,
            'saved_uvs': saved_uvs,
            'cloth_body_normals': cloth_body_normals,
            'original_offset': p.offset,
        }

        # Reselect clothing
        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        self.report({'INFO'},
                    f"Preview ready — adjust sliders, then Apply or Cancel. "
                    f"({actual_tris:,} tri proxy, {subdiv_levels} subdivisions)")
        return {'FINISHED'}


class EFIT_OT_preview_apply(Operator):
    """Accept the current preview and apply post-processing."""
    bl_idname = "efit.preview_apply"
    bl_label = "Apply Fit"
    bl_description = "Accept the previewed fit and apply post-processing (smooth, symmetrize, etc.)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_efit_cache)

    def execute(self, context):
        global _efit_cache
        c = _efit_cache
        if not c:
            self.report({'WARNING'}, "No preview to apply.")
            return {'CANCELLED'}

        p = context.scene.efit_props
        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            self.report({'ERROR'}, "Clothing object no longer exists.")
            _efit_cache.clear()
            return {'CANCELLED'}
        preserve_name = c.get('preserve_name', '')
        has_preserve = c['has_preserve']
        preserved_indices = c['preserved_indices']
        saved_uvs = c.get('saved_uvs')

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        # ================================================================
        #  Corrective Smooth (add and apply)
        # ================================================================
        if p.smooth_iterations > 0:
            m_cs = cloth.modifiers.new(f"{EFIT_PREFIX}Smooth", 'CORRECTIVE_SMOOTH')
            m_cs.factor = p.smooth_factor
            m_cs.iterations = p.smooth_iterations
            m_cs.smooth_type = 'SIMPLE'
            m_cs.use_only_smooth = False
            if has_preserve and preserve_name:
                m_cs.vertex_group = preserve_name
                m_cs.invert_vertex_group = True
            bpy.ops.object.modifier_apply(modifier=m_cs.name)

        # ================================================================
        #  Symmetrize
        # ================================================================
        if p.post_symmetrize:
            bpy.ops.object.select_all(action='DESELECT')
            cloth.select_set(True)
            context.view_layer.objects.active = cloth
            bpy.ops.object.mode_set(mode='EDIT')
            import bmesh
            bm = bmesh.from_edit_mesh(cloth.data)
            bm.verts.ensure_lookup_table()

            for v in bm.verts:
                v.select = True
            if has_preserve and preserved_indices:
                pres_set = set(preserved_indices)
                for v in bm.verts:
                    if v.index in pres_set:
                        v.select = False
            bm.select_flush(True)
            bmesh.update_edit_mesh(cloth.data)

            bpy.ops.mesh.symmetrize(direction=p.symmetrize_axis)
            bpy.ops.object.mode_set(mode='OBJECT')

        # ================================================================
        #  Laplacian Smooth (add and apply)
        # ================================================================
        if p.post_laplacian:
            m_lap = cloth.modifiers.new(f"{EFIT_PREFIX}Laplacian", 'LAPLACIANSMOOTH')
            m_lap.lambda_factor = p.laplacian_factor
            m_lap.lambda_border = 0.0
            m_lap.iterations = p.laplacian_iterations
            m_lap.use_volume_preserve = True
            m_lap.use_normalized = True
            if has_preserve and preserve_name:
                m_lap.vertex_group = preserve_name
                m_lap.invert_vertex_group = True
            bpy.ops.object.modifier_apply(modifier=m_lap.name)

        # Restore UVs if needed
        if saved_uvs:
            _restore_uvs(cloth.data, saved_uvs)

        # Clear cache
        _efit_cache.clear()

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        self.report({'INFO'}, "Fit applied.")
        return {'FINISHED'}


class EFIT_OT_preview_cancel(Operator):
    """Cancel the preview and restore original vertex positions."""
    bl_idname = "efit.preview_cancel"
    bl_label = "Cancel Fit"
    bl_description = "Discard the previewed fit and restore original mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_efit_cache)

    def execute(self, context):
        global _efit_cache
        c = _efit_cache
        if not c:
            self.report({'WARNING'}, "No preview to cancel.")
            return {'CANCELLED'}

        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            _efit_cache.clear()
            self.report({'ERROR'}, "Clothing object no longer exists.")
            return {'CANCELLED'}
        all_originals = c['all_originals']

        for vi, co in all_originals.items():
            cloth.data.vertices[vi].co = co
        cloth.data.update()

        _efit_cache.clear()
        self.report({'INFO'}, "Fit cancelled — mesh restored.")
        return {'FINISHED'}


class EFIT_OT_remove(Operator):
    """Remove all Elastic Fit modifiers and restore the mesh."""
    bl_idname = "efit.remove"
    bl_label = "Remove Fit"
    bl_description = "Remove all Elastic Fit modifiers from the clothing"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cloth = context.scene.efit_props.clothing_obj
        if not cloth:
            self.report({'ERROR'}, "No clothing mesh selected.")
            return {'CANCELLED'}
        _remove_efit(cloth)

        for obj in list(bpy.data.objects):
            if obj.name.startswith(f"{EFIT_PREFIX}Proxy"):
                bpy.data.objects.remove(obj, do_unlink=True)

        self.report({'INFO'}, "Fit removed.")
        return {'FINISHED'}


class EFIT_OT_clear_blockers(Operator):
    """Remove all shape keys and unapplied modifiers from the clothing mesh."""
    bl_idname = "efit.clear_blockers"
    bl_label = "Clear Blockers"
    bl_description = "Remove shape keys and unapplied modifiers from clothing so it can be fitted"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cloth = context.scene.efit_props.clothing_obj
        if not cloth or cloth.type != 'MESH':
            self.report({'ERROR'}, "Select a valid clothing mesh first.")
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        removed = []

        # Remove shape keys
        if cloth.data.shape_keys:
            count = len(cloth.data.shape_keys.key_blocks)
            bpy.ops.object.select_all(action='DESELECT')
            cloth.select_set(True)
            context.view_layer.objects.active = cloth
            bpy.ops.object.shape_key_remove(all=True)
            removed.append(f"{count} shape keys")

        # Remove non-EFit modifiers (keep armatures)
        non_efit = [m for m in cloth.modifiers
                    if not m.name.startswith(EFIT_PREFIX) and m.type != 'ARMATURE']
        for m in non_efit:
            cloth.modifiers.remove(m)
        if non_efit:
            removed.append(f"{len(non_efit)} modifiers")

        if removed:
            self.report({'INFO'}, f"Removed: {', '.join(removed)}")
        else:
            self.report({'INFO'}, "Nothing to remove.")
        return {'FINISHED'}


class EFIT_OT_reset_defaults(Operator):
    """Reset all Elastic Fit sliders to their default values."""
    bl_idname = "efit.reset_defaults"
    bl_label = "Reset Defaults"
    bl_description = "Reset all sliders to their default values"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.efit_props
        for prop_name in (
            'fit_amount', 'offset', 'proxy_triangles', 'preserve_uvs',
            'smooth_factor', 'smooth_iterations',
            'post_symmetrize', 'symmetrize_axis',
            'post_laplacian', 'laplacian_factor', 'laplacian_iterations',
            'follow_strength', 'cleanup',
            'disp_smooth_passes', 'disp_smooth_threshold',
            'disp_smooth_min', 'disp_smooth_max', 'follow_neighbors',
        ):
            p.property_unset(prop_name)
        if _efit_cache:
            _efit_preview_update(context)
        self.report({'INFO'}, "All sliders reset to defaults.")
        return {'FINISHED'}


# -- Panel --

class SVRC_PT_elastic_fit(Panel):
    bl_label = "Elastic Clothing Fit"
    bl_idname = "SVRC_PT_elastic_fit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        p = context.scene.efit_props

        # -- Mesh selection --
        box = layout.box()
        box.label(text="Select Meshes", icon='MESH_DATA')
        box.prop(p, "body_obj", icon='OUTLINER_OB_MESH')
        box.prop(p, "clothing_obj", icon='MATCLOTH')

        # -- Blocker warnings --
        if p.clothing_obj and p.clothing_obj.type == 'MESH':
            has_sk, blocker_mods = _has_blockers(p.clothing_obj)
            if has_sk or blocker_mods:
                warn_box = layout.box()
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

        # -- Fit controls --
        box = layout.box()
        box.label(text="Fit Settings", icon='MOD_SHRINKWRAP')
        box.prop(p, "fit_amount", slider=True)
        box.prop(p, "offset")
        box.prop(p, "proxy_triangles")
        box.prop(p, "preserve_uvs")

        # -- Elastic smoothing --
        box = layout.box()
        box.label(text="Shape Preservation", icon='MOD_SMOOTH')
        box.prop(p, "smooth_factor")
        box.prop(p, "smooth_iterations")

        # -- Post-fit options --
        box = layout.box()
        box.label(text="Post-Fit Options", icon='TOOL_SETTINGS')

        row = box.row()
        row.prop(p, "post_symmetrize")
        if p.post_symmetrize:
            row.prop(p, "symmetrize_axis", text="")

        box.prop(p, "post_laplacian")
        if p.post_laplacian:
            sub = box.column(align=True)
            sub.prop(p, "laplacian_factor")
            sub.prop(p, "laplacian_iterations")

        # -- Preserve group --
        box = layout.box()
        box.label(text="Preserve Group (Optional)", icon='PINNED')
        if p.clothing_obj and p.clothing_obj.type == 'MESH':
            box.prop_search(
                p, "preserve_group",
                p.clothing_obj, "vertex_groups",
                text="Group",
            )
            if p.preserve_group:
                box.prop(p, "follow_strength")
        else:
            box.label(text="Select clothing first", icon='INFO')

        # -- Advanced adjustments --
        box = layout.box()
        row = box.row()
        row.prop(p, "show_advanced",
                icon='TRIA_DOWN' if p.show_advanced else 'TRIA_RIGHT',
                emboss=False)
        if p.show_advanced:
            col = box.column(align=True)
            col.label(text="Displacement Smoothing:")
            col.prop(p, "disp_smooth_passes")
            col.prop(p, "disp_smooth_threshold")
            col.prop(p, "disp_smooth_min")
            col.prop(p, "disp_smooth_max")
            col.separator()
            col.label(text="Preserve Follow:")
            col.prop(p, "follow_neighbors")

        # -- Action buttons --
        layout.separator()

        if _efit_cache:
            # Preview mode — show Apply / Cancel
            box = layout.box()
            box.label(text="Preview Active", icon='HIDE_OFF')
            box.label(text="Adjust sliders above to see changes live.")
            row = box.row(align=True)
            row.scale_y = 1.5
            row.operator("efit.preview_apply", icon='CHECKMARK', text="Apply")
            row.operator("efit.preview_cancel", icon='CANCEL', text="Cancel")
        else:
            layout.prop(p, "cleanup")
            row = layout.row(align=True)
            row.scale_y = 1.5
            row.operator("efit.fit", icon='CHECKMARK')
            row.operator("efit.remove", icon='X')

        layout.operator("efit.reset_defaults", icon='LOOP_BACK')


# ============================================================================
#  REGISTRATION
# ============================================================================

_classes = (
    EFitProperties,
    EFIT_OT_fit,
    EFIT_OT_preview_apply,
    EFIT_OT_preview_cancel,
    EFIT_OT_remove,
    EFIT_OT_reset_defaults,
    EFIT_OT_clear_blockers,
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


if __name__ == "__main__":
    register()
