# tests/test_disp_smoothing_vectorised.py
#
# Parity tests for the fully-vectorised neighbour-averaging path added to
# state._apply_disp_smoothing.
#
# Compares a numpy re-implementation of the vectorised algorithm against the
# pure-Python reference replica from test_disp_smoothing.py.  Any divergence
# signals a bug in the production code.
#
# Requires numpy — skipped automatically in the test venv where numpy is absent.
# Runs inside Blender headless suites which do have numpy available.
#
# Root cause guarded against: the per-vertex Python loop
#   for i, vi in enumerate(fitted_indices):
#       neighbor_positions = [vi_to_pos[ni] for ni in neighbors if ni in vi_to_pos]
#       avg = buf_a[neighbor_positions].mean(axis=0)
#       buf_b[i] = buf_a[i] * (1 - blend[i]) + avg * blend[i]
# rebuilt a list of neighbour indices on every vertex of every pass — O(N * passes)
# Python allocations per tick.  Replaced with a vectorised np.add.at scatter.

import math
import statistics
import pytest

np = pytest.importorskip("numpy", reason="numpy not available in test venv")


# ---------------------------------------------------------------------------
# Reference: pure-Python replica (identical to test_disp_smoothing.py)
# ---------------------------------------------------------------------------

def _vec_norm(a, b):
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))


def _vec_blend(a, b, t):
    return [a[k] * (1.0 - t) + b[k] * t for k in range(3)]


def _vec_mean(vecs):
    n = len(vecs)
    return [sum(v[k] for v in vecs) / n for k in range(3)]


def _apply_disp_smoothing_py(smoothed_arr, fitted_indices, cloth_adj,
                              ds_passes, ds_thresh_mult, ds_min, ds_max):
    vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}
    N = len(fitted_indices)
    arr = [list(row) for row in smoothed_arr]

    for _pass in range(ds_passes):
        gradient = [0.0] * N
        for i, vi in enumerate(fitted_indices):
            neighbors = cloth_adj.get(vi, [])
            if not neighbors:
                continue
            max_diff = 0.0
            for ni in neighbors:
                ni_pos = vi_to_pos.get(ni)
                if ni_pos is None:
                    continue
                diff = _vec_norm(arr[i], arr[ni_pos])
                if diff > max_diff:
                    max_diff = diff
            gradient[i] = max_diff

        median_grad = statistics.median(gradient) if gradient else 0.0
        threshold = max(median_grad * ds_thresh_mult, 0.0001)
        blend = []
        for g in gradient:
            if g <= threshold:
                blend.append(ds_min)
            else:
                t = min(1.0, (g - threshold) / max(threshold, 0.0001))
                blend.append(ds_min + (ds_max - ds_min) * t)

        new_arr = [list(row) for row in arr]
        for i, vi in enumerate(fitted_indices):
            neighbors = cloth_adj.get(vi, [])
            if not neighbors:
                continue
            neighbor_positions = [vi_to_pos[ni] for ni in neighbors if ni in vi_to_pos]
            if not neighbor_positions:
                continue
            avg = _vec_mean([arr[ni_pos] for ni_pos in neighbor_positions])
            new_arr[i] = _vec_blend(arr[i], avg, blend[i])
        arr = new_arr

    return arr


# ---------------------------------------------------------------------------
# Under test: numpy-vectorised replica (mirrors production state.py)
# ---------------------------------------------------------------------------

def _apply_disp_smoothing_np(smoothed_arr_list, fitted_indices, cloth_adj,
                              ds_passes, ds_thresh_mult, ds_min, ds_max):
    """Numpy-vectorised replica of state._apply_disp_smoothing.

    Mirrors the logic added in the post-M006 neighbour-averaging fix:
    - COO src_rows/dst_rows (undirected edges, j > i each stored once)
    - smooth_degree, smooth_has_nbrs pre-computed once outside the pass loop
    - np.add.at scatter for neighbour sum; divide by degree for mean
    - Isolated vertices (no fitted neighbours) passed through unchanged
    """
    N = len(fitted_indices)
    vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}

    _src, _dst = [], []
    for i, vi in enumerate(fitted_indices):
        for ni in cloth_adj.get(vi, []):
            ni_pos = vi_to_pos.get(ni)
            if ni_pos is not None and ni_pos > i:
                _src.append(i)
                _dst.append(ni_pos)
    src_rows = np.array(_src, dtype=np.int32)
    dst_rows = np.array(_dst, dtype=np.int32)
    has_edges = len(src_rows) > 0

    _degree = np.zeros(N, dtype=np.float64)
    if has_edges:
        np.add.at(_degree, src_rows, 1.0)
        np.add.at(_degree, dst_rows, 1.0)
    smooth_degree   = np.where(_degree > 0.0, _degree, 1.0)
    smooth_has_nbrs = _degree > 0.0

    buf_a = np.array(smoothed_arr_list, dtype=np.float64)
    buf_b = np.empty_like(buf_a)

    for _pass in range(ds_passes):
        gradient = np.zeros(N, dtype=np.float64)
        if has_edges:
            diffs = buf_a[src_rows] - buf_a[dst_rows]
            norms = np.sqrt((diffs ** 2).sum(axis=1))
            np.maximum.at(gradient, src_rows, norms)
            np.maximum.at(gradient, dst_rows, norms)

        median_grad = float(np.median(gradient))
        threshold = max(median_grad * ds_thresh_mult, 0.0001)
        t = np.clip((gradient - threshold) / max(threshold, 0.0001), 0.0, 1.0)
        blend = np.where(gradient <= threshold,
                         ds_min,
                         ds_min + (ds_max - ds_min) * t)

        if has_edges:
            neighbor_sum = np.zeros_like(buf_a)
            np.add.at(neighbor_sum, src_rows, buf_a[dst_rows])
            np.add.at(neighbor_sum, dst_rows, buf_a[src_rows])
            avg = neighbor_sum / smooth_degree[:, None]
            blended = buf_a * (1.0 - blend[:, None]) + avg * blend[:, None]
            buf_b[:] = np.where(smooth_has_nbrs[:, None], blended, buf_a)
        else:
            buf_b[:] = buf_a

        buf_a, buf_b = buf_b, buf_a

    return buf_a.tolist()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVectorisedAveragingParity:
    """Compare _apply_disp_smoothing_np against _apply_disp_smoothing_py.

    Any divergence means the vectorised production path is wrong.
    """

    @staticmethod
    def _check(smoothed_arr, fitted_indices, cloth_adj, passes, thresh, dmin, dmax):
        py_out = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj, passes, thresh, dmin, dmax)
        np_out = _apply_disp_smoothing_np(
            smoothed_arr, fitted_indices, cloth_adj, passes, thresh, dmin, dmax)
        for i, (py_row, np_row) in enumerate(zip(py_out, np_out)):
            for k in range(3):
                assert np_row[k] == pytest.approx(py_row[k], abs=1e-10), (
                    f"Divergence at row {i} component {k}: "
                    f"pure-Python={py_row[k]:.15g}  numpy={np_row[k]:.15g}"
                )

    def test_2x2_grid_single_pass(self):
        """2x2 grid, 1 pass."""
        fitted = [0, 1, 2, 3]
        arr = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
               [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]
        adj = {0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2]}
        self._check(arr, fitted, adj, passes=1, thresh=1.0, dmin=0.1, dmax=0.9)

    def test_2x2_grid_15_passes(self):
        """2x2 grid, 15 passes (production default ds_passes)."""
        fitted = [0, 1, 2, 3]
        arr = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
               [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]
        adj = {0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2]}
        self._check(arr, fitted, adj, passes=15, thresh=2.0, dmin=0.05, dmax=0.95)

    def test_line_topology_5_passes(self):
        """Linear chain v0-v1-v2-v3-v4, 5 passes."""
        fitted = [0, 1, 2, 3, 4]
        arr = [[float(i), 0.0, 0.0] for i in range(5)]
        adj = {0: [1], 1: [0, 2], 2: [1, 3], 3: [2, 4], 4: [3]}
        self._check(arr, fitted, adj, passes=5, thresh=1.0, dmin=0.1, dmax=0.8)

    def test_isolated_vertex_passes_through_unchanged(self):
        """Vertex with no fitted neighbours is unchanged after any number of passes."""
        fitted = [0, 1, 2]
        arr = [[0.0, 0.0, 0.0], [5.0, 5.0, 5.0], [1.0, 0.0, 0.0]]
        adj = {0: [2], 1: [], 2: [0]}
        np_out = _apply_disp_smoothing_np(
            arr, fitted, adj, ds_passes=10,
            ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9)
        # v1 (row 1, no neighbours) must be unchanged
        for k in range(3):
            assert np_out[1][k] == pytest.approx(5.0, abs=1e-10), (
                f"Isolated vertex changed at component {k}: {np_out[1][k]}"
            )

    def test_sparse_vertex_indices(self):
        """Non-contiguous indices (v100, v200, v300, v400), 3 passes."""
        fitted = [100, 200, 300, 400]
        arr = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
               [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]
        adj = {100: [200, 300], 200: [100, 400],
               300: [100, 400], 400: [200, 300]}
        self._check(arr, fitted, adj, passes=3, thresh=1.5, dmin=0.05, dmax=0.9)

    def test_zero_passes_returns_input_unchanged(self):
        """ds_passes=0: output is numerically identical to input."""
        fitted = [0, 1, 2, 3]
        arr = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6],
               [0.7, 0.8, 0.9], [1.0, 1.1, 1.2]]
        adj = {0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2]}
        np_out = _apply_disp_smoothing_np(
            arr, fitted, adj, ds_passes=0,
            ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9)
        for i, row in enumerate(arr):
            for k in range(3):
                assert np_out[i][k] == pytest.approx(row[k], abs=1e-15)

    def test_uniform_displacements_unchanged(self):
        """Uniform displacements produce zero gradient; output equals input."""
        fitted = [0, 1, 2, 3]
        same = [0.5, -0.3, 1.1]
        arr = [list(same) for _ in range(4)]
        adj = {0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2]}
        np_out = _apply_disp_smoothing_np(
            arr, fitted, adj, ds_passes=5,
            ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9)
        for i in range(4):
            for k in range(3):
                assert np_out[i][k] == pytest.approx(same[k], abs=1e-10)
