# pipeline.py
# Core fitting pipeline helpers called exclusively by EFIT_OT_fit.execute.
# Separated from operators.py so the algorithm layer can be read and tested
# independently of Blender operator registration.

import numpy as np
import mathutils
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

import bmesh
import bpy

from . import state
from .state import EFIT_PREFIX, _calc_subdivisions
from .properties import _resolve_vg_name


def _build_face_list(mesh_data):
    """Build polygon vertex-index tuples via bulk foreach_get reads.

    Returns list[tuple[int, ...]] as required by BVHTree.FromPolygons.
    Replaces per-polygon Python generators ([tuple(f.vertices) for f in ...])
    with three C-level bulk reads, which is significantly faster on dense meshes.
    """
    n_loops = len(mesh_data.loops)
    n_polys = len(mesh_data.polygons)
    loop_vi    = np.empty(n_loops, dtype=np.int32)
    loop_start = np.empty(n_polys, dtype=np.int32)
    loop_total = np.empty(n_polys, dtype=np.int32)
    mesh_data.loops.foreach_get("vertex_index", loop_vi)
    mesh_data.polygons.foreach_get("loop_start", loop_start)
    mesh_data.polygons.foreach_get("loop_total", loop_total)
    return [tuple(loop_vi[s:s+t]) for s, t in zip(loop_start, loop_total)]


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

    _lt = np.empty(len(proxy.data.polygons), dtype=np.int32)
    proxy.data.polygons.foreach_get("loop_total", _lt)
    current_tris  = int(np.sum(np.maximum(0, _lt - 2)))
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

    _lt2 = np.empty(len(proxy.data.polygons), dtype=np.int32)
    proxy.data.polygons.foreach_get("loop_total", _lt2)
    actual_tris = int(np.sum(np.maximum(0, _lt2 - 2)))
    return proxy, actual_tris, subdiv_levels


def _efit_create_hull_proxy(context, body):
    """Create a convex-hull proxy of the body mesh as a shrinkwrap target.

    The convex hull fills concave regions (crotch, inner thigh, armpits) so
    the shrinkwrap step cannot pull clothing vertices into those cavities.
    The resulting object is a watertight convex mesh suitable as a shrinkwrap
    target. No subdivision is applied -- resolution only needs to match the
    body surface closely enough for the BVH to produce smooth displacements.

    Returns the hull object on success, or None on failure.
    The caller is responsible for removing the object when the fit completes.
    """
    # Duplicate the body so we work on a clean copy with modifiers stripped.
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    context.view_layer.objects.active = body
    if 'FINISHED' not in bpy.ops.object.duplicate(linked=False):
        return None
    hull_obj = context.active_object
    if hull_obj is body:
        return None
    hull_obj.name = f"{EFIT_PREFIX}HullProxy"

    # Strip modifiers so the hull is built from rest-pose geometry.
    for m in list(hull_obj.modifiers):
        hull_obj.modifiers.remove(m)

    # Build the convex hull in-place using bmesh.
    bm = bmesh.new()
    bm.from_mesh(hull_obj.data)
    result = bmesh.ops.convex_hull(bm, input=bm.verts)

    # convex_hull tags geometry not part of the hull in result["geom_interior"]
    # and result["geom_unused"]. Delete those so only hull faces remain.
    interior = set(result.get("geom_interior", []))
    unused   = set(result.get("geom_unused",   []))
    to_delete = interior | unused
    if to_delete:
        bmesh.ops.delete(
            bm,
            geom=[g for g in to_delete if isinstance(g, bmesh.types.BMFace)],
            context='FACES',
        )

    bm.to_mesh(hull_obj.data)
    bm.free()
    hull_obj.data.update()

    return hull_obj


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
            cloth.vertex_groups[_resolve_vg_name(eg.group_name)].index
            for eg in p.exclusive_groups
            if _resolve_vg_name(eg.group_name) and cloth.vertex_groups.get(_resolve_vg_name(eg.group_name))
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
        n = len(cloth.data.vertices)
        preserved_set = set()
        for v in cloth.data.vertices:
            for g in v.groups:
                if g.group == preserve_vg_idx and g.weight > 0.0:
                    preserved_set.add(v.index)
                    break
        preserved_indices = sorted(preserved_set)
        fitted_indices = [vi for vi in range(n) if vi not in preserved_set]
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
        # Read from cache if already built this fit cycle; build and cache on miss.
        kd_preserve = state._efit_cache.get('kd_preserve')
        if kd_preserve is None:
            kd_preserve = KDTree(len(preserved_indices))
            for i, vi in enumerate(preserved_indices):
                kd_preserve.insert(all_originals[vi], i)
            kd_preserve.balance()
            state._efit_cache['kd_preserve'] = kd_preserve

        kd_fitted = state._efit_cache.get('kd_fitted')
        if kd_fitted is None:
            kd_fitted = KDTree(len(fitted_indices))
            for i, vi in enumerate(fitted_indices):
                kd_fitted.insert(all_originals[vi], i)
            kd_fitted.balance()
            state._efit_cache['kd_fitted'] = kd_fitted

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

    Returns (cloth_displacements, cloth_body_normals, cloth_body_distances, offset_group_weights, cloth_adj, vg_membership, bvh).
    """
    proxy_faces = _build_face_list(proxy.data)
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
    body_key = (body.name, len(body.data.vertices), len(body.data.polygons))
    bvh_body = state._bvh_cache.get(body_key)
    if bvh_body is None:
        body_faces = _build_face_list(body.data)
        body_verts = [v.co for v in body.data.vertices]
        bvh_body   = BVHTree.FromPolygons(body_verts, body_faces)
        state._bvh_cache.clear()
        state._bvh_cache[body_key] = bvh_body

    cloth_body_normals = {}
    cloth_body_distances = {}
    for vi in fitted_indices:
        v = cloth.data.vertices[vi]
        loc, normal, face_idx, dist = bvh_body.find_nearest(v.co)
        if normal is not None:
            cloth_body_normals[vi] = normal.normalized()
        else:
            cloth_body_normals[vi] = mathutils.Vector((0.0, 0.0, 0.0))
        if dist is None:
            cloth_body_distances[vi] = 0.0
        elif loc is not None and normal is not None:
            # Detect inside/outside via ray cast along the nearest face normal.
            # A ray fired outward from an inside vertex hits the far body wall
            # (hit is not None); from an outside vertex the ray exits the mesh
            # without a hit (hit is None).  This is reliable for non-convex
            # meshes where the dot-product sign test fails: in concave regions
            # (inner thigh, crotch, armpits) the nearest face normal can point
            # inward relative to an outside query point, causing the dot test to
            # misidentify outside verts as inside and apply their full (large)
            # displacement unconditionally -- which explodes the mesh.
            n_unit = normal.normalized()
            hit, _, _, _ = bvh_body.ray_cast(v.co + n_unit * 0.0001, n_unit)
            cloth_body_distances[vi] = 0.0 if (hit is not None) else dist
        else:
            cloth_body_distances[vi] = dist

    # Precompute per-fitted-vertex weights for offset influence groups.
    # In EVGF mode the exclusive groups carry their own influence sliders;
    # in Full Mesh Fit mode the offset_groups list is used instead.

    # Build VG membership cache: {vg_idx: {vi: weight}} for all vertex groups.
    # Stores weights at build time so _compute_offset_group_weights can do a
    # single-pass dict comprehension with zero additional RNA reads (C2 fix).
    fitted_set_vg = set(fitted_indices)
    vg_membership = {}
    for v in cloth.data.vertices:
        if v.index not in fitted_set_vg:
            continue
        for g in v.groups:
            if g.weight > 0.0:
                vg_membership.setdefault(g.group, {})[v.index] = g.weight

    offset_group_weights = state._compute_offset_group_weights(
        cloth, source_groups, fitted_indices, vg_membership=vg_membership)

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

    return cloth_displacements, cloth_body_normals, cloth_body_distances, offset_group_weights, cloth_adj, vg_membership, bvh


def _efit_apply_smoothing(cloth, all_originals, cloth_displacements, cloth_adj,
                          fitted_indices, fit, p, proximity_weights=None):
    """Apply adaptive displacement smoothing and write final vertex positions.

    Smooths aggressively where the displacement field has sharp jumps (e.g. the
    centerline crease between pant legs) and leaves smooth regions nearly untouched.
    Each pass computes a per-vertex gradient (max displacement diff to edge neighbors);
    vertices above the median-scaled threshold blend hard toward their neighbor average
    while those below blend lightly.
    """
    smoothed = state._smooth_displacements(
        cloth_displacements, fitted_indices, cloth_adj, p)

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
        og_name = _resolve_vg_name(og.group_name)
        if not og_name:
            continue
        og_weights = offset_group_weights.get(og_name)
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

    # Lazily build and cache the KDTree on first call.
    # Rest-pose positions are used so neighbor selection stays stable
    # as the mesh deforms across slider changes.
    kd_follow = state._efit_cache.get('kd_follow')
    if kd_follow is None:
        kd_follow = KDTree(len(fitted_indices))
        for i, vi in enumerate(fitted_indices):
            # Rest-pose coords keep neighbor lookup stable across deformation.
            kd_follow.insert(all_originals[vi], i)
        kd_follow.balance()
        state._efit_cache['kd_follow'] = kd_follow

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
            disp  = mathutils.Vector(pre_offset_positions[ni]) - all_originals[ni]
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
