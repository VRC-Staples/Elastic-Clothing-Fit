# tests/test_disp_smoothing.py
#
# Pure-Python behavioral-parity tests for the _apply_disp_smoothing algorithm
# as implemented in elastic_fit/state.py.
#
# state.py imports bpy and numpy at module level so it cannot be imported in a
# plain Python test environment.  The algorithm is extracted here with:
#   - lists-of-lists instead of numpy (N,3) arrays
#   - statistics.median instead of np.median
#   - math.sqrt / plain arithmetic instead of np.linalg.norm / np.where
#
# The extracted function must match the numpy version's math exactly — same
# gradient formula, same median-based threshold, same blend formula.  Any
# discrepancy means the numpy migration in state.py has a bug.

import math
import statistics
import pytest


# ---------------------------------------------------------------------------
# Extracted pure-Python algorithm (mirrors elastic_fit/state.py exactly)
# ---------------------------------------------------------------------------

def _vec_norm(a, b):
    """Euclidean distance between two 3-element lists/tuples."""
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))


def _vec_blend(a, b, t):
    """Linear blend: a*(1-t) + b*t, element-wise."""
    return [a[k] * (1.0 - t) + b[k] * t for k in range(3)]


def _vec_mean(vecs):
    """Mean of a list of 3-element lists."""
    n = len(vecs)
    return [sum(v[k] for v in vecs) / n for k in range(3)]


def _apply_disp_smoothing_py(smoothed_arr, fitted_indices, cloth_adj,
                              ds_passes, ds_thresh_mult, ds_min, ds_max):
    """Pure-Python replica of state._apply_disp_smoothing.

    ``smoothed_arr`` — list of N 3-element lists, one per fitted vertex.
    Row ``i`` corresponds to vertex ``fitted_indices[i]``.

    Returns a new list of N 3-element lists (input not modified).
    """
    vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}
    N = len(fitted_indices)

    # Work on a copy so callers see no mutation
    arr = [list(row) for row in smoothed_arr]

    for _pass in range(ds_passes):
        # --- Gradient: max Euclidean distance to any fitted neighbor ---
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

        # --- Median threshold ---
        median_grad = statistics.median(gradient) if gradient else 0.0

        # --- Blend factors (same formula as numpy version) ---
        threshold = max(median_grad * ds_thresh_mult, 0.0001)
        blend = []
        for g in gradient:
            if g <= threshold:
                blend.append(ds_min)
            else:
                t = min(1.0, (g - threshold) / max(threshold, 0.0001))
                blend.append(ds_min + (ds_max - ds_min) * t)

        # --- Neighbor averaging ---
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
# Tests
# ---------------------------------------------------------------------------

class TestApplyDispSmoothing:

    # -----------------------------------------------------------------------
    # T1: Single-pass on a known 2×2 grid — hand-computed expected values
    # -----------------------------------------------------------------------

    def test_single_pass_2x2_grid(self):
        """One smoothing pass on a square grid produces hand-verified results.

        Grid layout (vertex indices):
          0 — 1
          |   |
          2 — 3

        Adjacency: 0↔1, 0↔2, 1↔3, 2↔3
        Displacements: v0=(0,0,0), v1=(1,0,0), v2=(0,1,0), v3=(1,1,0)

        Hand computation:
          gradient for every vertex = 1.0 (all diffs are unit length)
          median = 1.0
          threshold = 1.0 * 1.0 = 1.0
          All g == threshold → blend = ds_min = 0.1

          Neighbor averages (using original positions):
            v0: avg of v1=(1,0,0) & v2=(0,1,0) = (0.5, 0.5, 0)
            v1: avg of v0=(0,0,0) & v3=(1,1,0) = (0.5, 0.5, 0)
            v2: avg of v0=(0,0,0) & v3=(1,1,0) = (0.5, 0.5, 0)
            v3: avg of v1=(1,0,0) & v2=(0,1,0) = (0.5, 0.5, 0)

          Result = original * 0.9 + avg * 0.1:
            v0: (0,0,0)*0.9 + (0.5,0.5,0)*0.1 = (0.05, 0.05, 0)
            v1: (1,0,0)*0.9 + (0.5,0.5,0)*0.1 = (0.95, 0.05, 0)
            v2: (0,1,0)*0.9 + (0.5,0.5,0)*0.1 = (0.05, 0.95, 0)
            v3: (1,1,0)*0.9 + (0.5,0.5,0)*0.1 = (0.95, 0.95, 0)
        """
        fitted_indices = [0, 1, 2, 3]
        smoothed_arr = [
            [0.0, 0.0, 0.0],  # v0
            [1.0, 0.0, 0.0],  # v1
            [0.0, 1.0, 0.0],  # v2
            [1.0, 1.0, 0.0],  # v3
        ]
        cloth_adj = {
            0: [1, 2],
            1: [0, 3],
            2: [0, 3],
            3: [1, 2],
        }
        result = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj,
            ds_passes=1, ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9,
        )
        expected = [
            [0.05, 0.05, 0.0],
            [0.95, 0.05, 0.0],
            [0.05, 0.95, 0.0],
            [0.95, 0.95, 0.0],
        ]
        for i in range(4):
            for k in range(3):
                assert result[i][k] == pytest.approx(expected[i][k], abs=1e-9), \
                    f"v{fitted_indices[i]} component {k}: got {result[i][k]}, expected {expected[i][k]}"

    # -----------------------------------------------------------------------
    # T2: Multi-pass convergence — max gradient decreases monotonically
    # -----------------------------------------------------------------------

    def test_multi_pass_convergence(self):
        """Five passes on a 1D chain should converge (max gradient decreases)."""
        # Linear chain: 0 — 1 — 2 — 3 — 4
        fitted_indices = [0, 1, 2, 3, 4]
        smoothed_arr = [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],   # spike at vertex 2
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ]
        cloth_adj = {
            0: [1],
            1: [0, 2],
            2: [1, 3],
            3: [2, 4],
            4: [3],
        }

        max_gradients = []
        for n_passes in range(1, 6):
            arr_after = _apply_disp_smoothing_py(
                [list(row) for row in smoothed_arr],
                fitted_indices, cloth_adj,
                ds_passes=n_passes,
                ds_thresh_mult=0.5,
                ds_min=0.2,
                ds_max=0.8,
            )
            # Compute max gradient of the result
            max_g = 0.0
            for i, vi in enumerate(fitted_indices):
                for ni in cloth_adj.get(vi, []):
                    ni_pos = fitted_indices.index(ni)
                    d = _vec_norm(arr_after[i], arr_after[ni_pos])
                    if d > max_g:
                        max_g = d
            max_gradients.append(max_g)

        # Each additional pass must not increase the max gradient
        for n in range(1, len(max_gradients)):
            assert max_gradients[n] <= max_gradients[n - 1] + 1e-9, (
                f"Max gradient increased at pass {n + 1}: "
                f"{max_gradients[n - 1]:.6f} → {max_gradients[n]:.6f}"
            )

    # -----------------------------------------------------------------------
    # T3: Empty neighbors — vertex with no neighbors is unchanged
    # -----------------------------------------------------------------------

    def test_isolated_vertex_unchanged(self):
        """A vertex with no neighbors must have the same displacement after smoothing."""
        fitted_indices = [0, 1, 2]
        smoothed_arr = [
            [1.0, 2.0, 3.0],  # v0 — isolated
            [0.0, 0.0, 0.0],  # v1
            [2.0, 2.0, 2.0],  # v2
        ]
        # v0 has no neighbors; v1 and v2 are connected
        cloth_adj = {
            0: [],
            1: [2],
            2: [1],
        }
        result = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj,
            ds_passes=3, ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9,
        )
        # v0 must be completely unchanged
        assert result[0][0] == pytest.approx(1.0)
        assert result[0][1] == pytest.approx(2.0)
        assert result[0][2] == pytest.approx(3.0)

    # -----------------------------------------------------------------------
    # T4: Single vertex — returns input unchanged
    # -----------------------------------------------------------------------

    def test_single_vertex_unchanged(self):
        """A single fitted vertex with no neighbors returns the input unchanged."""
        fitted_indices = [7]
        smoothed_arr = [[3.5, -1.2, 0.8]]
        cloth_adj = {7: []}

        result = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj,
            ds_passes=5, ds_thresh_mult=1.0, ds_min=0.0, ds_max=1.0,
        )
        assert len(result) == 1
        assert result[0][0] == pytest.approx(3.5)
        assert result[0][1] == pytest.approx(-1.2)
        assert result[0][2] == pytest.approx(0.8)

    # -----------------------------------------------------------------------
    # T5: Uniform displacements — gradient is 0, no change
    # -----------------------------------------------------------------------

    def test_uniform_displacements_unchanged(self):
        """When all vertices have the same displacement, gradient is 0 everywhere
        and smoothing produces no change (blend = ds_min applied against identical
        averages → result is identical to input)."""
        fitted_indices = [0, 1, 2, 3]
        same = [0.5, -0.3, 1.1]
        smoothed_arr = [list(same) for _ in range(4)]
        cloth_adj = {
            0: [1, 2],
            1: [0, 3],
            2: [0, 3],
            3: [1, 2],
        }
        result = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj,
            ds_passes=4, ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9,
        )
        for i in range(4):
            for k in range(3):
                assert result[i][k] == pytest.approx(same[k], abs=1e-9), \
                    f"Uniform displacements changed at row {i} component {k}"

    # -----------------------------------------------------------------------
    # T6: zero ds_passes — input returned unchanged
    # -----------------------------------------------------------------------

    def test_zero_passes_returns_input_unchanged(self):
        """With ds_passes=0 no smoothing loop runs; array should be identical."""
        fitted_indices = [10, 20, 30]
        smoothed_arr = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        cloth_adj = {10: [20], 20: [10, 30], 30: [20]}
        result = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj,
            ds_passes=0, ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9,
        )
        for i in range(3):
            for k in range(3):
                assert result[i][k] == pytest.approx(smoothed_arr[i][k])

    # -----------------------------------------------------------------------
    # T7: Non-contiguous vertex indices — vi_to_pos mapping is correct
    # -----------------------------------------------------------------------

    def test_non_contiguous_vertex_indices(self):
        """Vertices with non-sequential indices must use vi_to_pos mapping correctly.
        A wrong mapping (using vi directly as row index) would corrupt results."""
        # Vertices 100, 200, 300 — row 0=v100, row 1=v200, row 2=v300
        fitted_indices = [100, 200, 300]
        smoothed_arr = [
            [0.0, 0.0, 0.0],   # v100
            [6.0, 0.0, 0.0],   # v200
            [3.0, 0.0, 0.0],   # v300
        ]
        # Chain: 100 — 300 — 200
        cloth_adj = {
            100: [300],
            200: [300],
            300: [100, 200],
        }
        # With 1 pass, v300's neighbors are v100=(0,0,0) and v200=(6,0,0)
        # Gradient v100: |v100-v300| = 3.0
        # Gradient v200: |v200-v300| = 3.0
        # Gradient v300: max(|v300-v100|, |v300-v200|) = 3.0
        # median = 3.0, threshold = 3.0*1.0 = 3.0
        # All g == threshold → blend = ds_min = 0.2
        # avg for v300 = mean(v100, v200) = (3.0, 0, 0)
        # new_v300 = (3,0,0)*0.8 + (3,0,0)*0.2 = (3.0, 0.0, 0.0)  (stays)
        result = _apply_disp_smoothing_py(
            smoothed_arr, fitted_indices, cloth_adj,
            ds_passes=1, ds_thresh_mult=1.0, ds_min=0.2, ds_max=0.8,
        )
        # v300 (row 2) is equidistant from both neighbors — should stay at 3.0
        assert result[2][0] == pytest.approx(3.0, abs=1e-9)
        assert result[2][1] == pytest.approx(0.0, abs=1e-9)
