# tests/test_pipeline_vectorization.py
#
# AST-based regression tests for the fit-time pipeline vectorization (S03).
#
# Root cause the tests guard against: _efit_apply_smoothing was originally a
# per-vertex Python loop that constructed N mathutils.Vector objects from
# all_originals, added displacement*fit*pw scalars, then wrote co_buf entries
# one-by-one.  The S03-T01 vectorization replaced this with a bulk numpy
# broadcast and COO-style scatter into co_buf.  Reverting any of these changes
# would silently re-introduce O(N) Vector allocations on the pipeline path.
#
# All tests are Blender-free — they inspect source code structure using AST
# parsing and source-text assertions only.
#
# Test classes:
#
#   TestSmoothingVectorization
#     Verifies _efit_apply_smoothing in pipeline.py calls _smooth_displacements
#     with return_array=True, contains no mathutils.Vector(all_originals...)
#     construction, and uses fi_arr array indexing for the vectorized write.
#
# Follows the AST-inspection pattern established in test_ndarray_contract.py.

import ast
import pathlib
import re
import textwrap
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(relative_path: str) -> str:
    """Load a project source file relative to the repository root."""
    root = pathlib.Path(__file__).parent.parent
    return (root / relative_path).read_text(encoding="utf-8")


def _parse(relative_path: str) -> ast.Module:
    """Parse a project source file and return its AST."""
    return ast.parse(_load(relative_path))


def _get_func_node(tree: ast.Module, func_name: str):
    """Return the first FunctionDef node whose name matches func_name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    return None


def _get_func_source(source: str, func_name: str) -> str:
    """Extract the source text of a function from full file source.

    Uses AST to find the function's line range, then slices the source text.
    """
    tree = ast.parse(source)
    func = _get_func_node(tree, func_name)
    if func is None:
        return ""
    lines = source.splitlines(keepends=True)
    start = func.lineno - 1  # 0-indexed
    end = func.end_lineno     # exclusive (end_lineno is 1-indexed inclusive)
    return "".join(lines[start:end])


# ===========================================================================
# TestSmoothingVectorization
#
# Validates that _efit_apply_smoothing in pipeline.py uses the vectorized
# numpy path instead of per-vertex mathutils.Vector construction.
# ===========================================================================

class TestSmoothingVectorization:

    @staticmethod
    def _func():
        tree = _parse("elastic_fit/pipeline.py")
        func = _get_func_node(tree, "_efit_apply_smoothing")
        assert func is not None, (
            "_efit_apply_smoothing not found in elastic_fit/pipeline.py"
        )
        return func

    @staticmethod
    def _func_source() -> str:
        src = _load("elastic_fit/pipeline.py")
        body = _get_func_source(src, "_efit_apply_smoothing")
        assert body, "_efit_apply_smoothing source not extractable"
        return body

    def test_smoothing_uses_return_array_true(self):
        """_efit_apply_smoothing must call _smooth_displacements with return_array=True.

        Without return_array=True the call returns a {vi: Vector} dict, which
        forces per-vertex Vector construction in the write loop and defeats the
        vectorized co_buf scatter.
        """
        func = self._func()
        found = False
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            # Match calls to _smooth_displacements or state._smooth_displacements
            callee = node.func
            is_smooth = False
            if isinstance(callee, ast.Attribute) and callee.attr == "_smooth_displacements":
                is_smooth = True
            elif isinstance(callee, ast.Name) and callee.id == "_smooth_displacements":
                is_smooth = True
            if not is_smooth:
                continue
            # Check for return_array=True keyword argument.
            for kw in node.keywords:
                if kw.arg == "return_array":
                    if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        found = True
                        break
            if found:
                break
        assert found, (
            "_efit_apply_smoothing does not call _smooth_displacements with "
            "return_array=True.  The vectorized ndarray path is not being used."
        )

    def test_smoothing_no_vector_alloriginals_construction(self):
        """_efit_apply_smoothing must NOT contain mathutils.Vector(all_originals...).

        The per-vertex Vector construction was the performance bottleneck: it
        allocated N mathutils.Vector objects just to add displacement and write
        co_buf entries.  After vectorization the function uses numpy array
        broadcasting instead.
        """
        body = self._func_source()
        assert "mathutils.Vector(all_originals" not in body, (
            "_efit_apply_smoothing still contains 'mathutils.Vector(all_originals...)'. "
            "The per-vertex Vector construction has not been replaced by vectorized "
            "numpy broadcasting."
        )

    def test_smoothing_uses_fi_arr_or_fitted_array(self):
        """_efit_apply_smoothing must use fi_arr (or equivalent) array indexing.

        The vectorized write scatters fitted positions into co_buf using
        ``base_arr = fi_arr * 3`` followed by indexed assignment.  The presence
        of 'fi_arr' confirms the vectorized write pattern is in place.
        """
        body = self._func_source()
        assert "fi_arr" in body, (
            "_efit_apply_smoothing does not contain 'fi_arr'.  The vectorized "
            "COO-style co_buf write pattern is missing — the function may still "
            "use per-vertex scalar writes."
        )

    def test_smoothing_uses_base_arr_scatter(self):
        """_efit_apply_smoothing must use base_arr for COO-style co_buf scatter.

        The pattern ``base_arr = fi_arr * 3`` followed by
        ``co_buf[base_arr] = ...`` is the vectorized scatter that replaces
        per-vertex ``co_buf[base] = result.x`` writes.
        """
        body = self._func_source()
        assert "base_arr" in body, (
            "_efit_apply_smoothing does not contain 'base_arr'.  The COO-style "
            "co_buf scatter pattern is missing."
        )
        # Also verify the multiply-by-3 pattern
        assert "fi_arr * 3" in body or "fi_arr*3" in body, (
            "_efit_apply_smoothing does not contain 'fi_arr * 3'.  The base offset "
            "computation for the COO-style scatter is missing."
        )


# ===========================================================================
# TestOffsetTuningVectorization  (added in T02)
#
# Validates that _efit_apply_offset_tuning uses np.add.at scatter instead of
# per-vertex scalar co_buf writes.
# ===========================================================================

class TestOffsetTuningVectorization:

    @staticmethod
    def _func_source() -> str:
        src = _load("elastic_fit/pipeline.py")
        body = _get_func_source(src, "_efit_apply_offset_tuning")
        assert body, "_efit_apply_offset_tuning source not extractable"
        return body

    def test_offset_tuning_uses_np_add_at(self):
        """_efit_apply_offset_tuning must use np.add.at for vectorized co_buf scatter.

        The per-vertex inner loop wrote co_buf entries one-by-one with scalar
        arithmetic.  The vectorized replacement collects vis/ws/poses arrays per
        group and scatters deltas with np.add.at in a single pass.
        """
        body = self._func_source()
        assert "np.add.at" in body, (
            "_efit_apply_offset_tuning does not contain 'np.add.at'.  "
            "The vectorized scatter has not replaced the per-vertex scalar writes."
        )

    def test_offset_tuning_no_per_vertex_scalar_loop(self):
        """_efit_apply_offset_tuning must not contain 'for vi, w in og_weights.items()'.

        The old inner loop iterated og_weights key-value pairs and wrote co_buf
        entries one element at a time.  The vectorized path uses array collection
        and np.add.at instead.
        """
        body = self._func_source()
        assert "for vi, w in og_weights.items()" not in body, (
            "_efit_apply_offset_tuning still contains the old per-vertex "
            "'for vi, w in og_weights.items()' loop.  The vectorized scatter "
            "has not been applied."
        )


# ===========================================================================
# TestPreOffsetPositionsNdarray  (added in T02)
#
# Validates that pre_offset_positions is an ndarray (not a dict) in operators.py
# and that preserve-follow accesses it by positional index (idx) not vertex index (ni).
# ===========================================================================

class TestPreOffsetPositionsNdarray:

    def test_operators_no_pre_offset_dict_comprehension(self):
        """operators.py must not assign pre_offset_positions as a dict comprehension.

        The dict pattern ``{vi: _pos_arr[i] for i, vi in enumerate(fitted_indices)}``
        created a {vertex_index: ndarray_row} dict that required keyed lookup in
        _efit_apply_preserve_follow.  The ndarray migration stores _pos_arr directly
        so row i is fitted_indices[i] -- positional indexing with no dict overhead.
        """
        src = _load("elastic_fit/operators.py")
        assert "pre_offset_positions = {" not in src, (
            "elastic_fit/operators.py still contains 'pre_offset_positions = {'.  "
            "The dict comprehension has not been replaced by the _pos_arr ndarray."
        )

    def test_preserve_follow_uses_positional_indexing(self):
        """_efit_apply_preserve_follow must use pre-computed fitted_disp, not per-vertex dict lookup.

        After the ndarray migration, pre_offset_positions is a positional (N_fitted, 3)
        ndarray.  The optimization pre-computes fitted_disp = pre_offset_positions - all_originals[fi_arr]
        once (vectorized), then indexes fitted_disp[idx] in the inner loop.  The old
        per-vertex dict lookup pre_offset_positions[ni] must be gone.
        """
        src = _load("elastic_fit/pipeline.py")
        body = _get_func_source(src, "_efit_apply_preserve_follow")
        assert body, "_efit_apply_preserve_follow source not extractable"
        assert "fitted_disp" in body, (
            "_efit_apply_preserve_follow does not contain 'fitted_disp'.  "
            "The pre-computed displacement array pattern is missing."
        )
        assert "pre_offset_positions[ni]" not in body, (
            "_efit_apply_preserve_follow still contains 'pre_offset_positions[ni]'.  "
            "The old vertex-index dict lookup has not been replaced."
        )
