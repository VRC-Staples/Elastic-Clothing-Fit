# operators.py
# All Blender operators for Elastic Clothing Fit.
# EFIT_OT_fit contains the full fitting pipeline (proxy creation, shrinkwrap,
# BVH displacement transfer, adaptive smoothing, offset fine-tuning, preserve follow).
# The remaining operators handle preview apply/cancel, remove, clear blockers,
# reset defaults, and offset group list management.

import numpy as np
import mathutils
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from . import state
from . import updater
from .state import (
    EFIT_PREFIX,
    _has_blockers, _calc_subdivisions,
    _save_uvs, _restore_uvs, _remove_efit,
)
from .preview import _efit_preview_update, _sync_preview_modifiers


# ---------------------------------------------------------------------------
# Fitting pipeline helpers (called exclusively by EFIT_OT_fit.execute)
# ---------------------------------------------------------------------------

def _efit_save_originals(cloth):
    """Snapshot all vertex positions for undo and displacement math.

    Returns (all_originals, undo_flat) where all_originals maps vertex index to
    Vector and undo_flat is a flat float list suitable for custom property storage.
    Uses foreach_get for a single C-level bulk read instead of per-vertex access.
    """
    n   = len(cloth.data.vertices)
    buf = np.empty(n * 3, dtype=np.float64)
    cloth.data.vertices.foreach_get("co", buf)
    all_originals = {
        i: mathutils.Vector((buf[i * 3], buf[i * 3 + 1], buf[i * 3 + 2]))
        for i in range(n)
    }
    return all_originals, buf.tolist()


def _efit_create_proxy(context, cloth, p):
    """Duplicate the clothing mesh, strip modifiers, and subdivide to the target triangle count.

    Returns (proxy, actual_tris, subdiv_levels) on success, or (None, 0, 0) on failure.
    """
    bpy.ops.object.select_all(action='DESELECT')
    cloth.select_set(True)
    context.view_layer.objects.active = cloth
    if 'FINISHED' not in bpy.ops.object.duplicate(linked=False):
        return None, 0, 0
    proxy = context.active_object
    if proxy is cloth:
        return None, 0, 0
    proxy.name = f"{EFIT_PREFIX}Proxy"

    # Strip all copied modifiers from the proxy (e.g. armature rigs)
    # so its evaluated geometry matches its rest-pose mesh exactly.
    for m in list(proxy.modifiers):
        proxy.modifiers.remove(m)

    current_tris  = sum(max(0, len(f.vertices) - 2) for f in proxy.data.polygons)
    subdiv_levels = _calc_subdivisions(current_tris, p.proxy_triangles)

    if subdiv_levels > 0:
        mod_sub = proxy.modifiers.new("_temp_subdiv", 'SUBSURF')
        mod_sub.levels             = subdiv_levels
        mod_sub.render_levels      = subdiv_levels
        mod_sub.subdivision_type   = 'SIMPLE'

        bpy.ops.object.select_all(action='DESELECT')
        proxy.select_set(True)
        context.view_layer.objects.active = proxy
        bpy.ops.object.modifier_apply(modifier=mod_sub.name)

    actual_tris = sum(max(0, len(f.vertices) - 2) for f in proxy.data.polygons)
    return proxy, actual_tris, subdiv_levels


def _efit_classify_vertices(cloth, p, has_preserve, preserve_name):
    """Classify each clothing vertex as fitted or preserved.

    Returns (fitted_indices, preserved_indices, has_preserve, preserve_name).
    In EXCLUSIVE mode, has_preserve and preserve_name are forced to False/""
    because the frozen vertices do not participate in the preserve-follow step.
    """
    preserved_indices = []
    fitted_indices    = []

    if p.fit_mode == 'EXCLUSIVE':
        # In EVGF mode only the union of the listed exclusive groups is fitted.
        # Everything else is frozen in place; no follow step is needed.
        # Iterate v.groups to avoid try/except-as-flow-control overhead.
        target_vg_indices = {
            cloth.vertex_groups[eg.group_name].index
            for eg in p.exclusive_groups
            if eg.group_name and cloth.vertex_groups.get(eg.group_name)
        }
        fitted_set = set()
        for v in cloth.data.vertices:
            for g in v.groups:
                if g.group in target_vg_indices and g.weight > 0.0:
                    fitted_set.add(v.index)
                    break
        fitted_indices    = list(fitted_set)
        preserved_indices = [v.index for v in cloth.data.vertices
                             if v.index not in fitted_set]
        has_preserve  = False
        preserve_name = ""
    elif has_preserve:
        preserve_vg_idx = cloth.vertex_groups[preserve_name].index
        for v in cloth.data.vertices:
            in_group = any(
                g.group == preserve_vg_idx and g.weight > 0.0
                for g in v.groups
            )
            if in_group:
                preserved_indices.append(v.index)
            else:
                fitted_indices.append(v.index)
    else:
        fitted_indices = list(range(len(cloth.data.vertices)))

    return fitted_indices, preserved_indices, has_preserve, preserve_name


def _efit_shrinkwrap_proxy(context, proxy, body, all_originals, fitted_indices,
                           preserved_indices, has_preserve, p):
    """Apply shrinkwrap to proxy and zero displacement near the preserve boundary.

    The boundary zeroing step prevents deformation from bleeding into preserved regions
    via BVH interpolation by nullifying proxy displacement for vertices topologically
    closer to a preserved clothing vertex than to a fitted one.

    Returns (proxy_pre, proxy_post).
    """
    _n_proxy = len(proxy.data.vertices)
    _buf_pre = np.empty(_n_proxy * 3, dtype=np.float64)
    proxy.data.vertices.foreach_get("co", _buf_pre)
    proxy_pre = [mathutils.Vector(_buf_pre[i*3:i*3+3]) for i in range(_n_proxy)]

    bpy.ops.object.select_all(action='DESELECT')
    proxy.select_set(True)
    context.view_layer.objects.active = proxy

    mod_sw              = proxy.modifiers.new(f"{EFIT_PREFIX}Shrinkwrap", 'SHRINKWRAP')
    mod_sw.target       = body
    mod_sw.wrap_method  = 'NEAREST_SURFACEPOINT'
    mod_sw.wrap_mode    = 'OUTSIDE_SURFACE'
    mod_sw.offset       = p.offset

    bpy.ops.object.modifier_apply(modifier=mod_sw.name)
    _buf_post = np.empty(_n_proxy * 3, dtype=np.float64)
    proxy.data.vertices.foreach_get("co", _buf_post)
    proxy_post = [mathutils.Vector(_buf_post[i*3:i*3+3]) for i in range(_n_proxy)]

    # Zero out displacement for proxy vertices that are topologically closer
    # to a preserved clothing vertex than a fitted one, so deformation does
    # not bleed into the preserved region via BVH interpolation.
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
            _, _, d_fit  = kd_fitted.find(pos)
            if d_pres < d_fit:
                proxy_post[pi] = proxy_pre[pi].copy()

    return proxy_pre, proxy_post


def _efit_transfer_displacements(cloth, proxy, proxy_pre, proxy_post, body,
                                 fitted_indices, source_groups):
    """Transfer shrinkwrap displacement from the proxy to the clothing via BVH interpolation.

    The BVHTree is built from the proxy's PRE-shrinkwrap positions so each cloth vertex
    maps to the topologically adjacent proxy face rather than a geometrically coincident
    but topologically distant one (e.g. the opposite leg in a pants mesh).

    Also caches the nearest body-surface normal per fitted vertex (used by the live preview
    to apply offset changes without re-running shrinkwrap) and precomputes per-vertex weights
    for offset influence groups.

    Returns (cloth_displacements, cloth_body_normals, offset_group_weights, cloth_adj).
    """
    proxy_faces = [tuple(f.vertices) for f in proxy.data.polygons]
    bvh         = BVHTree.FromPolygons(proxy_pre, proxy_faces)
    proxy_polys = proxy.data.polygons

    # Compute per-fitted-vertex displacement via inverse-distance weighted
    # barycentric interpolation from the three nearest proxy face vertices.
    cloth_displacements = {}
    for vi in fitted_indices:
        v = cloth.data.vertices[vi]
        loc, normal, face_idx, dist = bvh.find_nearest(v.co)

        if face_idx is None:
            cloth_displacements[vi] = mathutils.Vector((0.0, 0.0, 0.0))
            continue

        face = proxy_polys[face_idx]
        fv   = list(face.vertices)

        # Weight each proxy face vertex's displacement by 1/distance.
        # 0.00001 floor avoids division-by-zero when positions coincide exactly.
        weights = [1.0 / max((v.co - proxy_pre[fi]).length, 0.00001) for fi in fv]
        w_sum   = sum(weights)

        avg_disp = mathutils.Vector((0.0, 0.0, 0.0))
        for fi, w in zip(fv, weights):
            avg_disp += (proxy_post[fi] - proxy_pre[fi]) * (w / w_sum)

        cloth_displacements[vi] = avg_disp

    # Cache the nearest body-surface normal per fitted vertex.  The preview
    # engine uses these to apply offset-slider changes live without re-running
    # the full shrinkwrap.
    body_faces   = [tuple(f.vertices) for f in body.data.polygons]
    body_verts   = [v.co for v in body.data.vertices]
    bvh_body     = BVHTree.FromPolygons(body_verts, body_faces)

    cloth_body_normals = {}
    cloth_body_distances = {}
    for vi in fitted_indices:
        v = cloth.data.vertices[vi]
        loc, normal, face_idx, dist = bvh_body.find_nearest(v.co)
        if normal is not None:
            cloth_body_normals[vi] = normal.normalized()
        else:
            cloth_body_normals[vi] = mathutils.Vector((0.0, 0.0, 0.0))
        cloth_body_distances[vi] = dist if dist is not None else 0.0

    # Precompute per-fitted-vertex weights for offset influence groups.
    # In EVGF mode the exclusive groups carry their own influence sliders;
    # in Full Mesh Fit mode the offset_groups list is used instead.
    offset_group_weights = state._compute_offset_group_weights(
        cloth, source_groups, fitted_indices)

    # Build a fitted-only edge adjacency dict.  Edges that cross the
    # preserve boundary are excluded so adaptive smoothing cannot bleed
    # displacement into the preserved region.
    # Uses foreach_get for a bulk read then numpy masking to filter edges
    # before the Python adjacency loop, which is much faster on large meshes.
    n_verts    = len(cloth.data.vertices)
    cloth_adj  = {vi: [] for vi in fitted_indices}
    n_edges    = len(cloth.data.edges)
    edge_buf   = np.empty(n_edges * 2, dtype=np.int32)
    cloth.data.edges.foreach_get("vertices", edge_buf)
    edges = edge_buf.reshape(-1, 2)
    fitted_mask = np.zeros(n_verts, dtype=bool)
    fitted_mask[np.array(fitted_indices, dtype=np.int32)] = True
    both_fitted = fitted_mask[edges[:, 0]] & fitted_mask[edges[:, 1]]
    for a, b in edges[both_fitted]:
        a, b = int(a), int(b)
        cloth_adj[a].append(b)
        cloth_adj[b].append(a)

    return cloth_displacements, cloth_body_normals, cloth_body_distances, offset_group_weights, cloth_adj


def _efit_apply_smoothing(cloth, all_originals, cloth_displacements, cloth_adj,
                          fitted_indices, fit, p, proximity_weights=None):
    """Apply adaptive displacement smoothing and write final vertex positions.

    Smooths aggressively where the displacement field has sharp jumps (e.g. the
    centerline crease between pant legs) and leaves smooth regions nearly untouched.
    Each pass computes a per-vertex gradient (max displacement diff to edge neighbors);
    vertices above the median-scaled threshold blend hard toward their neighbor average
    while those below blend lightly.
    """
    smoothed       = {vi: cloth_displacements[vi].copy() for vi in fitted_indices}
    ds_passes      = p.disp_smooth_passes
    ds_thresh_mult = p.disp_smooth_threshold
    ds_min         = p.disp_smooth_min
    ds_max         = p.disp_smooth_max

    smoothed = state._apply_disp_smoothing(
        smoothed, fitted_indices, cloth_adj,
        ds_passes, ds_thresh_mult, ds_min, ds_max)

    # Write all fitted vertices in a single foreach_set call instead of
    # N individual Python-to-C bridge crossings.
    n_verts = len(cloth.data.vertices)
    co_buf  = np.empty(n_verts * 3, dtype=np.float64)
    cloth.data.vertices.foreach_get("co", co_buf)
    for vi in fitted_indices:
        pw     = proximity_weights[vi] if proximity_weights else 1.0
        result = all_originals[vi] + smoothed[vi] * fit * pw
        base   = vi * 3
        co_buf[base]     = result.x
        co_buf[base + 1] = result.y
        co_buf[base + 2] = result.z
    cloth.data.vertices.foreach_set("co", co_buf)

    cloth.data.update()


def _efit_apply_offset_tuning(cloth, cloth_body_normals, offset_group_weights,
                              source_groups, p):
    """Apply per-group offset influence multipliers along cached body-surface normals.

    A group influence of 100% is neutral (no change); 0% pulls the vertices flush to
    the body surface; 200% doubles the gap.
    """
    base_offset = p.offset
    n_verts = len(cloth.data.vertices)
    co_buf  = np.empty(n_verts * 3, dtype=np.float64)
    cloth.data.vertices.foreach_get("co", co_buf)
    changed = False
    for og in source_groups:
        if not og.group_name:
            continue
        og_weights = offset_group_weights.get(og.group_name)
        if not og_weights:
            continue
        # 0% => -1 (no offset), 100% => 0 (neutral), 200% => +1 (double)
        mult_delta = og.influence / 100.0 - 1.0
        if abs(mult_delta) < 0.0001:
            continue
        for vi, w in og_weights.items():
            if vi in cloth_body_normals:
                n     = cloth_body_normals[vi]
                delta = base_offset * mult_delta * w
                base  = vi * 3
                co_buf[base]     += n.x * delta
                co_buf[base + 1] += n.y * delta
                co_buf[base + 2] += n.z * delta
                changed = True
    if changed:
        cloth.data.vertices.foreach_set("co", co_buf)
    cloth.data.update()


def _efit_apply_preserve_follow(cloth, all_originals, fitted_indices, preserved_indices,
                                pre_offset_positions, p):
    """Move preserved vertices to gently follow nearby fitted areas.

    Builds a KDTree of fitted vertices in rest-pose space (stable across deformation),
    then for each preserved vertex computes an inverse-distance-weighted average of
    the K nearest fitted vertices' displacements and applies it scaled by follow_strength.
    """
    strength = p.follow_strength
    if strength <= 0.0:
        return

    kd_follow = KDTree(len(fitted_indices))
    for i, vi in enumerate(fitted_indices):
        # Rest-pose coords keep neighbor lookup stable across deformation.
        kd_follow.insert(all_originals[vi], i)
    kd_follow.balance()

    K_follow = min(p.follow_neighbors, len(fitted_indices))

    n_verts = len(cloth.data.vertices)
    co_buf  = np.empty(n_verts * 3, dtype=np.float64)
    cloth.data.vertices.foreach_get("co", co_buf)

    for vi in preserved_indices:
        rest_pos  = all_originals[vi]
        neighbors = kd_follow.find_n(rest_pos, K_follow)

        total_disp   = mathutils.Vector((0.0, 0.0, 0.0))
        total_weight = 0.0

        for _co, idx, dist in neighbors:
            ni    = fitted_indices[idx]
            disp  = pre_offset_positions[ni] - all_originals[ni]
            w     = 1.0 / max(dist, 0.0001)
            total_disp   += disp * w
            total_weight += w

        if total_weight > 0.0:
            avg_disp = total_disp / total_weight
            res  = rest_pos + avg_disp * strength
            base = vi * 3
            co_buf[base]     = res.x
            co_buf[base + 1] = res.y
            co_buf[base + 2] = res.z

    cloth.data.vertices.foreach_set("co", co_buf)
    cloth.data.update()


class EFIT_OT_fit(Operator):
    bl_idname = "efit.fit"
    bl_label = "Fit Clothing"
    bl_description = "Fit the clothing to the body mesh with a smooth, elastic result"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = context.scene.efit_props
        if (p.clothing_obj is None
                or p.body_obj is None
                or p.clothing_obj == p.body_obj
                or state._efit_cache):
            return False
        if p.fit_mode == 'EXCLUSIVE':
            cloth = p.clothing_obj
            has_valid = any(
                eg.group_name and cloth.vertex_groups.get(eg.group_name)
                for eg in p.exclusive_groups
            )
            if not has_valid:
                cls.poll_message_set(
                    "Add at least one vertex group to 'Groups to Fit' "
                    "(under Advanced Settings) before fitting."
                )
                return False
        return True

    def execute(self, context):
        p     = context.scene.efit_props
        cloth = p.clothing_obj
        body  = p.body_obj

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

        if p.fit_mode == 'EXCLUSIVE':
            valid_groups = [eg for eg in p.exclusive_groups
                            if eg.group_name and cloth.vertex_groups.get(eg.group_name)]
            if not valid_groups:
                self.report({'ERROR'},
                            "Exclusive Vertex Group Fit requires at least one group in the "
                            "'Groups to Fit' list. Add a vertex group under Advanced Settings.")
                return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Clear any active preview before starting a new fit.
        state._efit_cache.clear()

        if p.cleanup:
            # Remove any leftover EFit_ modifiers and the stale originals without
            # restoring vertex positions. Position restore is only correct for
            # Cancel/Remove Fit; starting a new fit should always begin from
            # whatever positions the mesh is currently in.
            for m in [m for m in cloth.modifiers if m.name.startswith(EFIT_PREFIX)]:
                cloth.modifiers.remove(m)
            if "_efit_originals" in cloth:
                del cloth["_efit_originals"]
            state._efit_originals.pop(cloth.name, None)
            for obj in list(bpy.data.objects):
                if obj.name.startswith(f"{EFIT_PREFIX}Proxy"):
                    bpy.data.objects.remove(obj, do_unlink=True)

        # Resolve preserve group: check that the named vertex group actually exists.
        preserve_name = (p.preserve_group or "").strip()
        has_preserve  = bool(preserve_name and cloth.vertex_groups.get(preserve_name))

        if preserve_name and not cloth.vertex_groups.get(preserve_name):
            self.report({'WARNING'},
                        f"Preserve group '{preserve_name}' not found, skipping.")

        # -- Save originals --
        all_originals, undo_flat = _efit_save_originals(cloth)
        cloth["_efit_originals"] = undo_flat
        state._efit_originals[cloth.name] = undo_flat

        saved_uvs = _save_uvs(cloth.data) if p.preserve_uvs else None

        # -- Create and subdivide the proxy mesh --
        proxy, actual_tris, subdiv_levels = _efit_create_proxy(context, cloth, p)
        if proxy is None:
            self.report({'ERROR'}, "Could not create proxy mesh.")
            return {'CANCELLED'}

        # -- Classify preserved vs fitted vertices --
        fitted_indices, preserved_indices, has_preserve, preserve_name = \
            _efit_classify_vertices(cloth, p, has_preserve, preserve_name)

        # -- Shrinkwrap proxy onto body --
        proxy_pre, proxy_post = _efit_shrinkwrap_proxy(
            context, proxy, body, all_originals,
            fitted_indices, preserved_indices, has_preserve, p)

        # -- Transfer displacement via BVH surface interpolation --
        source_groups = p.exclusive_groups if p.fit_mode == 'EXCLUSIVE' else p.offset_groups
        cloth_displacements, cloth_body_normals, cloth_body_distances, offset_group_weights, cloth_adj = \
            _efit_transfer_displacements(
                cloth, proxy, proxy_pre, proxy_post, body, fitted_indices, source_groups)

        bpy.data.objects.remove(proxy, do_unlink=True)

        # -- Proximity falloff weights (between steps 5 and 6) --
        proximity_weights = None
        if p.use_proximity_falloff:
            proximity_weights = state._compute_proximity_weights(
                cloth_body_distances, fitted_indices,
                p.proximity_start, p.proximity_end, p.proximity_curve)

        # -- Adaptive displacement smoothing --
        _efit_apply_smoothing(
            cloth, all_originals, cloth_displacements,
            cloth_adj, fitted_indices, p.fit_amount, p,
            proximity_weights=proximity_weights)

        if saved_uvs:
            _restore_uvs(cloth.data, saved_uvs)

        # Save each fitted vertex's position before any offset fine-tuning is applied.
        # The preserve group follow step reads from these saved positions, so offset
        # adjustments on fitted areas cannot unintentionally move nearby preserved vertices.
        # Only snapshot when needed -- skips an expensive per-vertex copy for users
        # with no preserve group and no offset groups.
        needs_pre_pos = bool(offset_group_weights) or (has_preserve and preserved_indices)
        if needs_pre_pos:
            _n    = len(cloth.data.vertices)
            _snap = np.empty(_n * 3, dtype=np.float64)
            cloth.data.vertices.foreach_get("co", _snap)
            pre_offset_positions = {
                vi: mathutils.Vector(_snap[vi*3:vi*3+3]) for vi in fitted_indices
            }
        else:
            pre_offset_positions = {}

        # -- Offset fine-tuning --
        if offset_group_weights:
            _efit_apply_offset_tuning(
                cloth, cloth_body_normals, offset_group_weights, source_groups, p)

        # -- Move preserved vertices to follow nearby fitted areas --
        if has_preserve and preserved_indices and fitted_indices:
            _efit_apply_preserve_follow(
                cloth, all_originals, fitted_indices,
                preserved_indices, pre_offset_positions, p)

        # -- Populate preview cache (slider changes will re-apply from here) --
        state._efit_cache = {
            'cloth_name':           cloth.name,
            'all_originals':        all_originals,
            'cloth_displacements':  cloth_displacements,
            'cloth_adj':            cloth_adj,
            'fitted_indices':       fitted_indices,
            'preserved_indices':    preserved_indices,
            'has_preserve':         has_preserve,
            'preserve_name':        preserve_name,
            'saved_uvs':            saved_uvs,
            'cloth_body_normals':   cloth_body_normals,
            'cloth_body_distances': cloth_body_distances,
            'proximity_weights':    proximity_weights,
            'original_offset':      p.offset,
            'offset_group_weights': offset_group_weights,
        }

        # Reselect clothing.
        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        # Add live preview modifiers so smoothing is visible immediately.
        _sync_preview_modifiers(cloth, p, has_preserve, preserve_name)

        self.report({'INFO'},
                    f"Preview ready. Adjust sliders, then Apply or Cancel. "
                    f"({actual_tris:,} tris, {subdiv_levels} subdivision levels)")
        return {'FINISHED'}


class EFIT_OT_preview_apply(Operator):
    """Accept the current preview and finalize the fit."""
    bl_idname      = "efit.preview_apply"
    bl_label       = "Apply Fit"
    bl_description = "Accept the current fit and apply any post-processing options"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(state._efit_cache)

    def execute(self, context):
        c = state._efit_cache
        if not c:
            self.report({'WARNING'}, "No preview to apply.")
            return {'CANCELLED'}

        p     = context.scene.efit_props
        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            self.report({'ERROR'}, "Clothing object no longer exists.")
            state._efit_cache.clear()
            return {'CANCELLED'}

        preserve_name     = c.get('preserve_name', '')
        has_preserve      = c['has_preserve']
        preserved_indices = c['preserved_indices']
        saved_uvs         = c.get('saved_uvs')

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        # Apply the corrective smooth modifier if present.
        m_cs = cloth.modifiers.get(f"{EFIT_PREFIX}Smooth")
        if m_cs is not None:
            bpy.ops.object.modifier_apply(modifier=m_cs.name)

        # Symmetrize: enter edit mode, select all non-preserved verts, run symmetrize.
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

        # Apply the laplacian smooth modifier if present.
        m_lap = cloth.modifiers.get(f"{EFIT_PREFIX}Laplacian")
        if m_lap is not None:
            bpy.ops.object.modifier_apply(modifier=m_lap.name)

        if saved_uvs:
            _restore_uvs(cloth.data, saved_uvs)

        state._efit_cache.clear()
        p.fit_mode = 'FULL'
        p.ui_tab   = 'FULL'

        bpy.ops.object.select_all(action='DESELECT')
        cloth.select_set(True)
        context.view_layer.objects.active = cloth

        self.report({'INFO'}, "Fit applied.")
        return {'FINISHED'}


class EFIT_OT_preview_cancel(Operator):
    """Cancel the preview and restore the clothing to its original shape."""
    bl_idname      = "efit.preview_cancel"
    bl_label       = "Cancel Fit"
    bl_description = "Discard the previewed fit and restore original mesh"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(state._efit_cache)

    def execute(self, context):
        c = state._efit_cache
        if not c:
            self.report({'WARNING'}, "No preview to cancel.")
            return {'CANCELLED'}

        cloth = bpy.data.objects.get(c['cloth_name'])
        if cloth is None:
            state._efit_cache.clear()
            self.report({'ERROR'}, "Clothing object no longer exists.")
            return {'CANCELLED'}

        # Remove live preview modifiers before restoring vertex positions.
        for mod_name in (f"{EFIT_PREFIX}Smooth", f"{EFIT_PREFIX}Laplacian"):
            m = cloth.modifiers.get(mod_name)
            if m is not None:
                cloth.modifiers.remove(m)

        flat = state._efit_originals.get(cloth.name)
        if flat is not None:
            cloth.data.vertices.foreach_set("co", np.asarray(flat, dtype=np.float64))
        else:
            all_originals = c['all_originals']
            for vi, co in all_originals.items():
                cloth.data.vertices[vi].co = co
        cloth.data.update()

        state._efit_cache.clear()
        state._efit_originals.pop(cloth.name, None)
        if "_efit_originals" in cloth:
            del cloth["_efit_originals"]
        p = context.scene.efit_props
        p.fit_mode = 'FULL'
        p.ui_tab   = 'FULL'
        self.report({'INFO'}, "Fit cancelled. Clothing restored.")
        return {'FINISHED'}


class EFIT_OT_remove(Operator):
    """Remove all fit data from the clothing."""
    bl_idname      = "efit.remove"
    bl_label       = "Remove Fit"
    bl_description = "Remove all fit data from the clothing and restore it"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.efit_props.clothing_obj is not None

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
    """Remove shape keys and unapplied modifiers from the clothing."""
    bl_idname      = "efit.clear_blockers"
    bl_label       = "Clear Blockers"
    bl_description = "Remove shape keys and unapplied modifiers from the clothing so it can be fitted"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = context.scene.efit_props
        return p.clothing_obj is not None and p.clothing_obj.type == 'MESH'

    def execute(self, context):
        cloth = context.scene.efit_props.clothing_obj
        if not cloth or cloth.type != 'MESH':
            self.report({'ERROR'}, "Select a valid clothing mesh first.")
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        removed = []

        # Remove all shape keys via the operator (handles Basis key correctly).
        if cloth.data.shape_keys:
            count = len(cloth.data.shape_keys.key_blocks)
            bpy.ops.object.select_all(action='DESELECT')
            cloth.select_set(True)
            context.view_layer.objects.active = cloth
            bpy.ops.object.shape_key_remove(all=True)
            removed.append(f"{count} shape keys")

        # Remove non-EFit, non-armature modifiers.
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
    bl_idname      = "efit.reset_defaults"
    bl_label       = "Reset Defaults"
    bl_description = "Reset all sliders to their default values"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.efit_props
        for prop_name in (
            'fit_mode', 'ui_tab',
            'fit_amount', 'offset', 'proxy_triangles', 'preserve_uvs',
            'smooth_factor', 'smooth_iterations',
            'post_symmetrize', 'symmetrize_axis',
            'post_laplacian', 'laplacian_factor', 'laplacian_iterations',
            'follow_strength', 'cleanup',
            'disp_smooth_passes', 'disp_smooth_threshold',
            'disp_smooth_min', 'disp_smooth_max', 'follow_neighbors',
            'use_proximity_falloff', 'proximity_mode',
            'proximity_start', 'proximity_end', 'proximity_curve',
            'show_fit_settings', 'show_shape_preservation', 'show_preserve_group',
            'show_displacement_smoothing',
            'show_offset_fine_tuning', 'show_post_fit', 'show_misc',
        ):
            p.property_unset(prop_name)
        if state._efit_cache:
            _efit_preview_update(context)
        self.report({'INFO'}, "All sliders reset to defaults.")
        return {'FINISHED'}


class EFIT_OT_offset_group_add(Operator):
    """Add a new vertex group offset entry."""
    bl_idname      = "efit.offset_group_add"
    bl_label       = "Add Offset Group"
    bl_description = "Add a vertex group whose offset influence can be fine-tuned"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item           = context.scene.efit_props.offset_groups.add()
        item.influence = 100
        return {'FINISHED'}


class EFIT_OT_offset_group_remove(Operator):
    """Remove the offset group entry at the given list index."""
    bl_idname      = "efit.offset_group_remove"
    bl_label       = "Remove Offset Group"
    bl_description = "Remove this vertex group offset entry"
    bl_options     = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        groups = context.scene.efit_props.offset_groups
        if 0 <= self.index < len(groups):
            groups.remove(self.index)
            if state._efit_cache:
                _efit_preview_update(context)
        return {'FINISHED'}


class EFIT_OT_exclusive_group_add(Operator):
    """Add a vertex group to the Exclusive Vertex Group Fit list."""
    bl_idname      = "efit.exclusive_group_add"
    bl_label       = "Add Exclusive Group"
    bl_description = "Add a vertex group to fit exclusively"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Disabled during an active preview so the list cannot change mid-fit.
        return not state._efit_cache

    def execute(self, context):
        context.scene.efit_props.exclusive_groups.add()
        return {'FINISHED'}


class EFIT_OT_exclusive_group_remove(Operator):
    """Remove a vertex group entry from the Exclusive Vertex Group Fit list."""
    bl_idname      = "efit.exclusive_group_remove"
    bl_label       = "Remove Exclusive Group"
    bl_description = "Remove this vertex group from the exclusive fit list"
    bl_options     = {'REGISTER', 'UNDO'}

    index: IntProperty()

    @classmethod
    def poll(cls, context):
        return not state._efit_cache

    def execute(self, context):
        groups = context.scene.efit_props.exclusive_groups
        if 0 <= self.index < len(groups):
            groups.remove(self.index)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Update operators
# ---------------------------------------------------------------------------

class EFIT_OT_check_update(Operator):
    """Check GitHub for a newer release of Elastic Clothing Fit."""
    bl_idname      = "efit.check_update"
    bl_label       = "Check for Updates"
    bl_description = "Query the GitHub releases API to see if a newer version is available"
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        # Grey out during an active preview so a network call cannot start mid-fit.
        return not state._efit_cache

    def execute(self, context):
        updater.check_for_update()
        return {'FINISHED'}


class EFIT_OT_download_update(Operator):
    """Download the latest release zip in the background."""
    bl_idname      = "efit.download_update"
    bl_label       = "Download Update"
    bl_description = "Download the latest release zip file in the background"
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return updater.get_state()['status'] == 'available'

    def execute(self, context):
        updater.download_and_prepare()
        return {'FINISHED'}


class EFIT_OT_install_restart(Operator):
    """Write the install startup script and relaunch Blender."""
    bl_idname      = "efit.install_restart"
    bl_label       = "Restart and Install"
    bl_description = "Save if requested, write an auto-install script, and relaunch Blender"
    bl_options     = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return updater.get_state()['status'] == 'ready'

    def execute(self, context):
        p = context.scene.efit_props
        if p.update_save_file and bpy.data.filepath and bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        reopen = bpy.data.filepath if (bpy.data.filepath and p.update_reopen_file) else ''
        updater.install_and_restart(reopen_filepath=reopen)
        return {'FINISHED'}


