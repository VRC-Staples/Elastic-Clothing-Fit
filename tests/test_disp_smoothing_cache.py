# tests/test_disp_smoothing_cache.py
#
# Regression tests for the smoothing topology cache introduced to fix
# preview-mode latency (commit e4c5b4c).
#
# Root cause: vi_to_pos, src_rows, and dst_rows inside _apply_disp_smoothing
# are pure functions of fitted_indices and cloth_adj — static for the entire
# preview session.  Before the fix they were rebuilt on every slider tick,
# causing seconds of latency.  The fix passes them in as optional kwargs
# so the preview path supplies pre-built arrays while the pipeline one-shot
# path builds them locally.
#
# Two classes of test:
#
#   TestCachedTopologyParity
#     Behavioral: calling _apply_disp_smoothing_py with pre-supplied topology
#     structures produces identical output to calling it without them (the
#     build-locally fallback).  Guards against the cache returning wrong results
#     or the two code paths diverging.
#
#   TestCachedTopologySourceInvariant
#     Structural: AST checks on state.py and operators.py that confirm:
#     - vi_to_pos / src_rows / dst_rows are NOT unconditionally rebuilt at the
#       top of _apply_disp_smoothing (they must be inside None-guards)
#     - _smooth_displacements reads the topology from _efit_cache
#     - operators.py writes all three keys into the cache at fit time
#
# The pytest venv has no numpy (see KNOWLEDGE.md).  All behavioral tests use
# the extracted pure-Python replica, identical to test_disp_smoothing.py.
# The structural tests use ast (stdlib only).

import ast
import math
import statistics
import pytest


# ---------------------------------------------------------------------------
# Pure-Python replica of _apply_disp_smoothing
# Identical to the replica in test_disp_smoothing.py — kept local so this
# file is self-contained and does not couple to another test module.
# ---------------------------------------------------------------------------

def _vec_norm(a, b):
    """Euclidean distance between two 3-element sequences."""
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))


def _vec_blend(a, b, t):
    """Linear blend: a*(1-t) + b*t, element-wise."""
    return [a[k] * (1.0 - t) + b[k] * t for k in range(3)]


def _vec_mean(vecs):
    """Mean of a list of 3-element lists."""
    n = len(vecs)
    return [sum(v[k] for v in vecs) / n for k in range(3)]


def _build_topology(fitted_indices, cloth_adj):
    """Build vi_to_pos, src_list, dst_list — pure-Python equivalent of the
    state.py topology builder.

    Returns (vi_to_pos, src_list, dst_list) where src_list and dst_list are
    plain Python lists of int (stand-ins for np.int32 arrays).
    """
    vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}
    src_list, dst_list = [], []
    for i, vi in enumerate(fitted_indices):
        for ni in cloth_adj.get(vi, []):
            ni_pos = vi_to_pos.get(ni)
            if ni_pos is not None and ni_pos > i:
                src_list.append(i)
                dst_list.append(ni_pos)
    return vi_to_pos, src_list, dst_list


def _apply_disp_smoothing_py(smoothed_arr, fitted_indices, cloth_adj,
                              ds_passes, ds_thresh_mult, ds_min, ds_max,
                              vi_to_pos=None, src_list=None, dst_list=None):
    """Pure-Python replica of state._apply_disp_smoothing, extended with the
    optional topology kwargs introduced by the cache fix.

    When vi_to_pos / src_list / dst_list are None the function builds them
    locally (pre-fix behaviour).  When supplied it uses them directly
    (post-fix cached behaviour).

    The gradient computation uses the same COO edge-pair logic as the numpy
    version: iterate edge pairs from src_list/dst_list, propagate max-norm
    to both endpoints.  This mirrors the np.maximum.at scatter in state.py.
    """
    N = len(fitted_indices)

    # --- topology: build locally or use supplied ---
    if vi_to_pos is None:
        vi_to_pos = {vi: i for i, vi in enumerate(fitted_indices)}
    if src_list is None or dst_list is None:
        src_list, dst_list = [], []
        for i, vi in enumerate(fitted_indices):
            for ni in cloth_adj.get(vi, []):
                ni_pos = vi_to_pos.get(ni)
                if ni_pos is not None and ni_pos > i:
                    src_list.append(i)
                    dst_list.append(ni_pos)

    arr = [list(row) for row in smoothed_arr]
    buf = [None] * N  # pre-allocated destination buffer (mirrors buf_b)

    for _pass in range(ds_passes):
        # --- Gradient via COO scatter-max (mirrors np.maximum.at) ---
        gradient = [0.0] * N
        for s, d in zip(src_list, dst_list):
            norm = _vec_norm(arr[s], arr[d])
            if norm > gradient[s]:
                gradient[s] = norm
            if norm > gradient[d]:
                gradient[d] = norm

        # --- Median threshold ---
        median_grad = statistics.median(gradient) if gradient else 0.0
        threshold = max(median_grad * ds_thresh_mult, 0.0001)

        # --- Blend factors ---
        blend = []
        for g in gradient:
            if g <= threshold:
                blend.append(ds_min)
            else:
                t = min(1.0, (g - threshold) / max(threshold, 0.0001))
                blend.append(ds_min + (ds_max - ds_min) * t)

        # --- Neighbor averaging into buf (mirrors np.copyto + loop) ---
        for i in range(N):
            buf[i] = list(arr[i])  # default: carry through unchanged
        for i, vi in enumerate(fitted_indices):
            neighbors = cloth_adj.get(vi, [])
            if not neighbors:
                continue
            neighbor_positions = [vi_to_pos[ni] for ni in neighbors if ni in vi_to_pos]
            if not neighbor_positions:
                continue
            avg = _vec_mean([arr[ni_pos] for ni_pos in neighbor_positions])
            buf[i] = _vec_blend(arr[i], avg, blend[i])

        # Swap buffers (mirrors buf_a, buf_b = buf_b, buf_a)
        arr, buf = buf, arr

    return arr


# ---------------------------------------------------------------------------
# Shared test mesh fixtures
# ---------------------------------------------------------------------------

def _grid_2x2():
    """2×2 grid: 0—1, 0—2, 1—3, 2—3."""
    fitted_indices = [0, 1, 2, 3]
    displacements = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 1.0, 0.0],
    ]
    cloth_adj = {0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2]}
    return fitted_indices, displacements, cloth_adj


def _chain_5():
    """Linear chain: 0—1—2—3—4 with a displacement spike at v2."""
    fitted_indices = [0, 1, 2, 3, 4]
    displacements = [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ]
    cloth_adj = {0: [1], 1: [0, 2], 2: [1, 3], 3: [2, 4], 4: [3]}
    return fitted_indices, displacements, cloth_adj


def _non_contiguous():
    """Vertices 100, 200, 300 — tests vi_to_pos mapping with sparse indices."""
    fitted_indices = [100, 200, 300]
    displacements = [
        [0.0, 0.0, 0.0],
        [6.0, 0.0, 0.0],
        [3.0, 0.0, 0.0],
    ]
    cloth_adj = {100: [300], 200: [300], 300: [100, 200]}
    return fitted_indices, displacements, cloth_adj


# ===========================================================================
# TestCachedTopologyParity
#
# For each fixture and parameter set, run _apply_disp_smoothing_py twice:
#   - without topology kwargs (builds locally — pre-fix behaviour)
#   - with pre-built topology kwargs (cached path — post-fix behaviour)
# Assert the outputs are element-wise identical.
# ===========================================================================

class TestCachedTopologyParity:

    def _assert_parity(self, fitted_indices, displacements, cloth_adj,
                       ds_passes, ds_thresh_mult, ds_min, ds_max):
        """Core helper: both paths must produce identical results."""
        result_uncached = _apply_disp_smoothing_py(
            [list(r) for r in displacements],
            fitted_indices, cloth_adj,
            ds_passes, ds_thresh_mult, ds_min, ds_max,
            vi_to_pos=None, src_list=None, dst_list=None,
        )
        vi_to_pos, src_list, dst_list = _build_topology(fitted_indices, cloth_adj)
        result_cached = _apply_disp_smoothing_py(
            [list(r) for r in displacements],
            fitted_indices, cloth_adj,
            ds_passes, ds_thresh_mult, ds_min, ds_max,
            vi_to_pos=vi_to_pos, src_list=src_list, dst_list=dst_list,
        )
        assert len(result_cached) == len(result_uncached)
        for i in range(len(result_cached)):
            for k in range(3):
                assert result_cached[i][k] == pytest.approx(result_uncached[i][k], abs=1e-12), (
                    f"Mismatch at row {i} component {k}: "
                    f"cached={result_cached[i][k]}, uncached={result_uncached[i][k]}"
                )

    # --- 2×2 grid ---

    def test_grid_2x2_single_pass(self):
        fi, disp, adj = _grid_2x2()
        self._assert_parity(fi, disp, adj, ds_passes=1,
                            ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9)

    def test_grid_2x2_fifteen_passes_default_params(self):
        """Default ds_passes=15 — the exact parameter combination that caused
        the regression.  Both paths must agree."""
        fi, disp, adj = _grid_2x2()
        self._assert_parity(fi, disp, adj, ds_passes=15,
                            ds_thresh_mult=2.0, ds_min=0.05, ds_max=0.80)

    def test_grid_2x2_zero_passes(self):
        fi, disp, adj = _grid_2x2()
        self._assert_parity(fi, disp, adj, ds_passes=0,
                            ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9)

    def test_grid_2x2_max_passes(self):
        fi, disp, adj = _grid_2x2()
        self._assert_parity(fi, disp, adj, ds_passes=50,
                            ds_thresh_mult=2.0, ds_min=0.05, ds_max=0.80)

    # --- 5-vertex chain ---

    def test_chain_single_pass(self):
        fi, disp, adj = _chain_5()
        self._assert_parity(fi, disp, adj, ds_passes=1,
                            ds_thresh_mult=0.5, ds_min=0.2, ds_max=0.8)

    def test_chain_fifteen_passes_default_params(self):
        fi, disp, adj = _chain_5()
        self._assert_parity(fi, disp, adj, ds_passes=15,
                            ds_thresh_mult=2.0, ds_min=0.05, ds_max=0.80)

    # --- non-contiguous vertex indices ---

    def test_non_contiguous_indices_parity(self):
        """Sparse vertex indices: vi_to_pos mapping must agree on both paths."""
        fi, disp, adj = _non_contiguous()
        self._assert_parity(fi, disp, adj, ds_passes=5,
                            ds_thresh_mult=1.0, ds_min=0.1, ds_max=0.9)

    # --- edge cases ---

    def test_single_vertex_no_edges(self):
        fi = [42]
        disp = [[1.5, -2.0, 0.3]]
        adj = {42: []}
        self._assert_parity(fi, disp, adj, ds_passes=5,
                            ds_thresh_mult=1.0, ds_min=0.0, ds_max=1.0)

    def test_uniform_displacements(self):
        """Uniform input: cached and uncached must agree (gradient=0 everywhere)."""
        fi, _, adj = _grid_2x2()
        disp = [[0.7, 0.7, 0.7]] * 4
        self._assert_parity(fi, disp, adj, ds_passes=10,
                            ds_thresh_mult=2.0, ds_min=0.05, ds_max=0.80)

    # --- topology reuse across multiple calls ---

    def test_topology_reuse_across_calls(self):
        """Simulates the preview session: topology built once, reused N times.

        Varies the displacement input across calls (as a slider drag would).
        Each call with the same pre-built topology must match the uncached
        result, demonstrating the topology arrays are safe to reuse.
        """
        fi, _, adj = _chain_5()
        vi_to_pos, src_list, dst_list = _build_topology(fi, adj)

        for scale in [0.1, 0.5, 1.0, 2.0, 5.0]:
            disp = [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, scale],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ]
            uncached = _apply_disp_smoothing_py(
                [list(r) for r in disp], fi, adj,
                ds_passes=15, ds_thresh_mult=2.0, ds_min=0.05, ds_max=0.80,
            )
            cached = _apply_disp_smoothing_py(
                [list(r) for r in disp], fi, adj,
                ds_passes=15, ds_thresh_mult=2.0, ds_min=0.05, ds_max=0.80,
                vi_to_pos=vi_to_pos, src_list=src_list, dst_list=dst_list,
            )
            for i in range(len(fi)):
                for k in range(3):
                    assert cached[i][k] == pytest.approx(uncached[i][k], abs=1e-12), (
                        f"scale={scale} row={i} component={k}: "
                        f"cached={cached[i][k]}, uncached={uncached[i][k]}"
                    )


# ===========================================================================
# TestCachedTopologySourceInvariant
#
# AST-based structural checks on state.py and operators.py.
# These guard against the regression silently returning: if someone removes
# the None-guards or stops writing to the cache, a test fails immediately.
# ===========================================================================

class TestCachedTopologySourceInvariant:

    @staticmethod
    def _load(path):
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    @staticmethod
    def _get_func_node(tree, func_name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return node
        return None

    # --- parameter declarations ---

    def test_apply_disp_smoothing_accepts_vi_to_pos_kwarg(self):
        """_apply_disp_smoothing must declare vi_to_pos as a parameter."""
        source = self._load('elastic_fit/state.py')
        tree = ast.parse(source)
        func = self._get_func_node(tree, '_apply_disp_smoothing')
        assert func is not None, "_apply_disp_smoothing not found in state.py"
        arg_names = [a.arg for a in func.args.args + func.args.kwonlyargs]
        assert 'vi_to_pos' in arg_names, (
            f"_apply_disp_smoothing missing 'vi_to_pos' parameter. Got: {arg_names}"
        )

    def test_apply_disp_smoothing_accepts_src_rows_kwarg(self):
        """_apply_disp_smoothing must declare src_rows as a parameter."""
        source = self._load('elastic_fit/state.py')
        tree = ast.parse(source)
        func = self._get_func_node(tree, '_apply_disp_smoothing')
        assert func is not None
        arg_names = [a.arg for a in func.args.args + func.args.kwonlyargs]
        assert 'src_rows' in arg_names, (
            f"_apply_disp_smoothing missing 'src_rows' parameter. Got: {arg_names}"
        )

    def test_apply_disp_smoothing_accepts_dst_rows_kwarg(self):
        """_apply_disp_smoothing must declare dst_rows as a parameter."""
        source = self._load('elastic_fit/state.py')
        tree = ast.parse(source)
        func = self._get_func_node(tree, '_apply_disp_smoothing')
        assert func is not None
        arg_names = [a.arg for a in func.args.args + func.args.kwonlyargs]
        assert 'dst_rows' in arg_names, (
            f"_apply_disp_smoothing missing 'dst_rows' parameter. Got: {arg_names}"
        )

    # --- unconditional-build guards ---

    def test_vi_to_pos_build_is_conditional(self):
        """vi_to_pos must only be built inside a None-guard, not unconditionally.

        An unconditional assignment at the function top level means the cache
        is never used and the regression has returned.  This walks the immediate
        function body (not nested blocks) for bare assignments to vi_to_pos.
        """
        source = self._load('elastic_fit/state.py')
        tree = ast.parse(source)
        func = self._get_func_node(tree, '_apply_disp_smoothing')
        assert func is not None

        unconditional = [
            stmt.lineno for stmt in func.body
            if isinstance(stmt, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == 'vi_to_pos'
                for t in stmt.targets
            )
        ]
        assert not unconditional, (
            f"vi_to_pos assigned unconditionally in _apply_disp_smoothing "
            f"at line(s) {unconditional}. Must be inside 'if vi_to_pos is None:'."
        )

    def test_src_dst_rows_build_is_conditional(self):
        """src_rows / dst_rows must only be built inside a conditional guard."""
        source = self._load('elastic_fit/state.py')
        tree = ast.parse(source)
        func = self._get_func_node(tree, '_apply_disp_smoothing')
        assert func is not None

        unconditional = [
            (t.id, stmt.lineno)
            for stmt in func.body
            if isinstance(stmt, ast.Assign)
            for t in stmt.targets
            if isinstance(t, ast.Name) and t.id in ('src_rows', 'dst_rows')
        ]
        assert not unconditional, (
            f"src_rows/dst_rows assigned unconditionally in _apply_disp_smoothing: "
            f"{unconditional}. Must be inside 'if src_rows is None or dst_rows is None:'."
        )

    # --- cache read in _smooth_displacements ---

    def test_smooth_displacements_reads_vi_to_pos_from_cache(self):
        """_smooth_displacements must read smooth_vi_to_pos from _efit_cache."""
        source = self._load('elastic_fit/state.py')
        assert 'smooth_vi_to_pos' in source, (
            "_smooth_displacements does not reference 'smooth_vi_to_pos'. "
            "The vi_to_pos topology cache is not being consumed."
        )

    def test_smooth_displacements_reads_src_rows_from_cache(self):
        """_smooth_displacements must read smooth_src_rows from _efit_cache."""
        source = self._load('elastic_fit/state.py')
        assert 'smooth_src_rows' in source, (
            "_smooth_displacements does not reference 'smooth_src_rows'. "
            "The src_rows topology cache is not being consumed."
        )

    def test_smooth_displacements_reads_dst_rows_from_cache(self):
        """_smooth_displacements must read smooth_dst_rows from _efit_cache."""
        source = self._load('elastic_fit/state.py')
        assert 'smooth_dst_rows' in source, (
            "_smooth_displacements does not reference 'smooth_dst_rows'. "
            "The dst_rows topology cache is not being consumed."
        )

    # --- cache write in operators.py ---

    def test_operators_writes_smooth_vi_to_pos(self):
        """operators.py must write smooth_vi_to_pos into _efit_cache at fit time."""
        source = self._load('elastic_fit/operators.py')
        assert 'smooth_vi_to_pos' in source, (
            "operators.py does not write 'smooth_vi_to_pos' into _efit_cache. "
            "The topology cache will not be populated and preview will rebuild every tick."
        )

    def test_operators_writes_smooth_src_rows(self):
        """operators.py must write smooth_src_rows into _efit_cache at fit time."""
        source = self._load('elastic_fit/operators.py')
        assert 'smooth_src_rows' in source, (
            "operators.py does not write 'smooth_src_rows' into _efit_cache."
        )

    def test_operators_writes_smooth_dst_rows(self):
        """operators.py must write smooth_dst_rows into _efit_cache at fit time."""
        source = self._load('elastic_fit/operators.py')
        assert 'smooth_dst_rows' in source, (
            "operators.py does not write 'smooth_dst_rows' into _efit_cache."
        )
