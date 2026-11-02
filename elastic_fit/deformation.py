"""Prepared fit data and array calculations shared by initial fit and preview.

Original coordinates have shape (N, 3). Displacement and normal row i belongs
to fitted_indices[i], not mesh vertex i. Inputs stay unchanged during evaluation.
Body distances and proximity weights have shape (M,) in the same fitted-row order.
Mesh edges have shape (E, 2) and contain original vertex indices.
Blender access and mesh writes belong to the callers.
"""
import time

import numpy as np


def compute_proximity_weights(distances, start, end, curve_key):
    """Return aligned falloff rows, with full weight at start and zero at end."""
    span = max(end - start, 0.0001)
    t_arr = np.clip((distances - start) / span, 0.0, 1.0)
    if curve_key == 'LINEAR':
        w_arr = 1.0 - t_arr
    elif curve_key == 'SHARP':
        w_arr = (1.0 - t_arr) ** 2
    elif curve_key == 'ROOT':
        w_arr = np.sqrt(np.maximum(0.0, 1.0 - t_arr))
    else:
        s = 1.0 - t_arr
        w_arr = s * s * (3.0 - 2.0 * s)
    return np.where(distances <= start, 1.0, np.where(distances >= end, 0.0, w_arr))


class PreparedFit:
    """Own one fit's aligned inputs, topology and derived caches.

    Preserved indices are eligible follow targets. Other non-fitted vertices stay fixed.
    Property values are read without modifying them. A batch_tree class selects
    the real batch backend. None selects the existing mathutils backend, imported
    only when preserve-follow needs it. Output buffers never alias the inputs.
    """

    def __init__(self, originals, displacements, fitted_indices, edges, body_normals,
                 preserved_indices=(), original_offset=0.0, body_distances=None,
                 offset_group_weights=None, vg_membership=None):
        self.originals = originals
        self.displacements = displacements
        self.body_normals = body_normals
        self.fitted_indices = tuple(fitted_indices)
        self.preserved_indices = tuple(preserved_indices)
        self.original_offset = original_offset
        self.body_distances = body_distances
        self.vg_membership = vg_membership if vg_membership is not None else {}
        count = len(self.fitted_indices)
        if originals.ndim != 2 or originals.shape[1] != 3:
            raise ValueError('Original coordinates must have shape (N, 3)')
        if displacements.shape != (count, 3) or body_normals.shape != (count, 3):
            raise ValueError('Displacement and normal rows must match fitted vertices')
        self.fitted_set = set(self.fitted_indices)
        if len(self.fitted_set) != count or self.fitted_set.intersection(self.preserved_indices):
            raise ValueError('Fitted vertices must be unique and separate from preserved vertices')
        if any(vi < 0 or vi >= len(originals) for vi in (*self.fitted_indices, *self.preserved_indices)):
            raise ValueError('Fit indices must refer to original vertices')
        self.fitted_array = np.array(self.fitted_indices, dtype=np.int32)
        self.preserved_array = np.array(self.preserved_indices, dtype=np.int64)
        self.fitted_originals = originals[self.fitted_array]
        self.row_of_vertex = {vi: row for row, vi in enumerate(self.fitted_indices)}
        vertex_rows = np.full(len(originals), -1, dtype=np.int32)
        vertex_rows[self.fitted_array] = np.arange(count, dtype=np.int32)
        row_edges = vertex_rows[edges]
        row_edges = row_edges[(row_edges >= 0).all(axis=1) & (row_edges[:, 0] != row_edges[:, 1])]
        row_edges = np.sort(row_edges, axis=1)
        # Retain source-row order and the original neighbor order within each row.
        self.source_rows, self.destination_rows = row_edges[np.argsort(row_edges[:, 0], kind='stable')].T
        degree = np.zeros(count, dtype=np.float64)
        np.add.at(degree, self.source_rows, 1.0)
        np.add.at(degree, self.destination_rows, 1.0)
        self.degree = np.where(degree > 0.0, degree, 1.0)
        self.has_neighbors = degree > 0.0
        self.follow_tree = None
        self._follow_factory = None
        self._preserved_batch_originals = None
        self.proximity_key = None
        self.proximity_weights = None
        self.last_timings = {}
        self.set_offset_weights(offset_group_weights if offset_group_weights is not None else {})

    def set_offset_weights(self, weights):
        """Replace group membership and its derived scatter arrays together."""
        self.offset_group_weights = weights
        self._offset_arrays = {}
        for name, group in weights.items():
            vertices = [vi for vi in group if vi in self.row_of_vertex]
            rows = np.array([self.row_of_vertex[vi] for vi in vertices], dtype=np.int32)
            self._offset_arrays[name] = (np.array(vertices, dtype=np.int32), self.body_normals[rows],
                                         np.array([group[vi] for vi in vertices], dtype=np.float64))

    def _smooth(self, displacements, p):
        count = len(self.fitted_indices)
        source, destination = self.source_rows, self.destination_rows
        has_edges = len(source) > 0
        buf_a = displacements.copy()
        buf_b = np.empty_like(buf_a)
        for _pass in range(p.disp_smooth_passes):
            gradient = np.zeros(count, dtype=np.float64)
            if has_edges:
                diffs = buf_a[source] - buf_a[destination]
                norms = np.sqrt((diffs ** 2).sum(axis=1))
                np.maximum.at(gradient, source, norms)
                np.maximum.at(gradient, destination, norms)
            median_grad = float(np.median(gradient))
            threshold = max(median_grad * p.disp_smooth_threshold, 0.0001)
            t = np.clip((gradient - threshold) / max(threshold, 0.0001), 0.0, 1.0)
            blend = np.where(gradient <= threshold, p.disp_smooth_min,
                             p.disp_smooth_min + (p.disp_smooth_max - p.disp_smooth_min) * t)
            if has_edges:
                neighbor_sum = np.zeros_like(buf_a)
                np.add.at(neighbor_sum, source, buf_a[destination])
                np.add.at(neighbor_sum, destination, buf_a[source])
                avg = neighbor_sum / self.degree[:, None]
                blended = buf_a * (1.0 - blend[:, None]) + avg * blend[:, None]
                buf_b[:] = np.where(self.has_neighbors[:, None], blended, buf_a)
            else:
                buf_b[:] = buf_a
            buf_a, buf_b = buf_b, buf_a
        return buf_a

    def _follow(self, coordinates, pre_offset, p, batch_tree):
        if p.follow_strength <= 0.0 or not self.preserved_indices or not self.fitted_indices:
            return
        count = min(p.follow_neighbors, len(self.fitted_indices))
        fitted_disp = pre_offset - self.fitted_originals
        if self.follow_tree is None or self._follow_factory is not batch_tree:
            if batch_tree is not None:
                self.follow_tree = batch_tree(self.fitted_originals.astype(np.float32))
                self._preserved_batch_originals = self.originals[self.preserved_array].astype(np.float32)
            else:
                from mathutils.kdtree import KDTree
                self.follow_tree = KDTree(len(self.fitted_indices))
                for row, vi in enumerate(self.fitted_indices):
                    self.follow_tree.insert(self.originals[vi], row)
                self.follow_tree.balance()
            self._follow_factory = batch_tree
        if batch_tree is not None:
            rest = self._preserved_batch_originals
            dists, indices = self.follow_tree.query(rest, k=count)
            inv_d = 1.0 / np.maximum(dists, np.float32(1e-4))
            weight_sum = inv_d.sum(axis=1, keepdims=True)
            neighbor_disp = fitted_disp.astype(np.float32)[indices]
            weighted = (neighbor_disp * inv_d[:, :, None]).sum(axis=1) / weight_sum
            mask = np.abs(weighted).sum(axis=1) >= 1e-7
            if mask.any():
                coordinates[self.preserved_array[mask]] = rest[mask] + weighted[mask] * np.float32(p.follow_strength)
        else:
            from mathutils import Vector
            for vi in self.preserved_indices:
                rest = self.originals[vi]
                neighbors = self.follow_tree.find_n(Vector(rest), count)
                tx = ty = tz = total_weight = 0.0
                for _co, row, distance in neighbors:
                    displacement = fitted_disp[row]
                    weight = 1.0 / max(distance, 0.0001)
                    tx += displacement[0] * weight
                    ty += displacement[1] * weight
                    tz += displacement[2] * weight
                    total_weight += weight
                if total_weight > 0.0:
                    inv_weight = 1.0 / total_weight
                    dx, dy, dz = tx * inv_weight, ty * inv_weight, tz * inv_weight
                    if abs(dx) + abs(dy) + abs(dz) >= 1e-7:
                        coordinates[vi] = (rest[0] + dx * p.follow_strength,
                                           rest[1] + dy * p.follow_strength,
                                           rest[2] + dz * p.follow_strength)

    def evaluate(self, p, proximity_weights=None, batch_tree=None, profile=False, initial_fit=False):
        """Evaluate the fit, retaining initial-only mesh rounding when requested."""
        timings = {} if profile else None
        if profile:
            start = time.perf_counter()
        offset_delta = p.offset - self.original_offset
        adjusted = (self.displacements + self.body_normals * offset_delta
                    if offset_delta != 0.0 else self.displacements)
        if profile:
            timings['adj'] = time.perf_counter() - start
            start = time.perf_counter()
        smoothed = self._smooth(adjusted, p)
        if profile:
            timings['smooth'] = time.perf_counter() - start
            start = time.perf_counter()
        coordinates = self.originals.copy()
        if proximity_weights is not None:
            fitted_positions = self.fitted_originals + smoothed * (p.fit_amount * proximity_weights[:, None])
        else:
            fitted_positions = self.fitted_originals + smoothed * p.fit_amount
        if initial_fit:
            # Initial fitting historically wrote the float32 mesh before taking the follow snapshot.
            fitted_positions = fitted_positions.astype(np.float32).astype(np.float64)
        coordinates[self.fitted_array] = fitted_positions
        if profile:
            timings['cobuf'] = time.perf_counter() - start
            start = time.perf_counter()
        if self.offset_group_weights and self.original_offset != 0.0:
            groups = p.exclusive_groups if p.fit_mode == 'EXCLUSIVE' else p.offset_groups
            for group in groups:
                name = group.group_name or ''
                if not name or name not in self._offset_arrays:
                    continue
                multiplier = group.influence / 100.0 - 1.0
                if abs(multiplier) < 0.0001:
                    continue
                vertices, normals, weights = self._offset_arrays[name]
                deltas = normals * (self.original_offset * multiplier * weights[:, None])
                np.add.at(coordinates, vertices, deltas)
        if profile:
            timings['offgrp'] = time.perf_counter() - start
            start = time.perf_counter()
        if initial_fit:
            # Group offsets crossed a second mesh boundary before preserve-follow.
            coordinates[self.fitted_array] = coordinates[self.fitted_array].astype(np.float32)
        self._follow(coordinates, fitted_positions, p, batch_tree)
        if profile:
            timings['preserve'] = time.perf_counter() - start
            self.last_timings = timings
        return coordinates
