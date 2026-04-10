# tests/test_ndarray_contract.py
#
# Regression tests for the ndarray migration contract introduced in S02.
#
# Root cause the tests guard against: cloth_displacements and cloth_body_normals
# were previously {vi: Vector} dicts.  Reverting them to dicts would break the
# vectorized adjusted_displacements broadcast in preview.py, re-introduce
# .to_tuple() overhead on the hot path, and crash the offset-group delta loop
# that now uses positional ndarray indexing.
#
# All tests are Blender-free — they inspect source code structure using AST
# parsing and source-text assertions only.  No numpy import is required in the
# test runner environment (the tests verify text/AST, not runtime types).
#
# Test classes:
#
#   TestTransferDisplacementsNdarray
#     Verifies pipeline._efit_transfer_displacements allocates ndarrays with
#     np.zeros() instead of {} dict literals for both displacement arrays.
#
#   TestSmoothDisplacementsNdarrayFastpath
#     Verifies state._smooth_displacements has an isinstance(…, np.ndarray)
#     guard that gates the ndarray fast-path.
#
#   TestPreviewHotPathNoDictPatterns
#     Source-text checks on preview.py: no adjusted_displacements={} dict,
#     no cloth_body_normals[vi] dict-keyed access, no .to_tuple() call.
#
#   TestProfilingInstrumentationPreserved
#     Counts perf_counter and _dev_mode occurrences in preview.py to ensure
#     the S01 profiling instrumentation has not been accidentally removed.
#
# Follows the AST-inspection pattern established in test_disp_smoothing_cache.py.

import ast
import pathlib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(relative_path: str) -> str:
    """Load a project source file relative to the repository root.

    The repository root is two directories above this test file
    (tests/ -> project root).
    """
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


def _source_contains_call(func_node: ast.FunctionDef, attr_name: str) -> bool:
    """Return True if any call to `something.attr_name(…)` appears under func_node."""
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr_name
        ):
            return True
    return False


def _source_contains_name_or_attr(func_node: ast.FunctionDef, name: str) -> bool:
    """Return True if any Name or Attribute node with id/attr == name appears."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


# ===========================================================================
# TestTransferDisplacementsNdarray
#
# Validates that _efit_transfer_displacements in pipeline.py no longer
# initialises cloth_displacements and cloth_body_normals as {} dicts,
# and instead allocates both as ndarrays via np.zeros or np.empty.
# ===========================================================================

class TestTransferDisplacementsNdarray:

    @staticmethod
    def _func():
        tree = _parse("elastic_fit/pipeline.py")
        func = _get_func_node(tree, "_efit_transfer_displacements")
        assert func is not None, (
            "_efit_transfer_displacements not found in elastic_fit/pipeline.py"
        )
        return func

    def test_cloth_displacements_not_initialized_as_dict(self):
        """cloth_displacements must NOT be assigned an empty dict literal.

        An assignment like ``cloth_displacements = {}`` would mean the ndarray
        migration has been reverted and the vectorized broadcast will fail at
        runtime.
        """
        source = _load("elastic_fit/pipeline.py")
        assert "cloth_displacements = {}" not in source, (
            "elastic_fit/pipeline.py still contains 'cloth_displacements = {}'. "
            "The ndarray migration (S02-T01) appears to have been reverted."
        )

    def test_cloth_body_normals_not_initialized_as_dict(self):
        """cloth_body_normals must NOT be assigned an empty dict literal."""
        source = _load("elastic_fit/pipeline.py")
        assert "cloth_body_normals = {}" not in source, (
            "elastic_fit/pipeline.py still contains 'cloth_body_normals = {}'. "
            "The ndarray migration (S02-T01) appears to have been reverted."
        )

    def test_cloth_displacements_allocated_with_np_zeros(self):
        """cloth_displacements must be allocated with np.zeros inside
        _efit_transfer_displacements.

        Confirms the ndarray is pre-allocated as a (N_fitted, 3) float64 block
        rather than being constructed via a dict comprehension or per-item dict
        insertion.
        """
        func = self._func()
        # Walk the function body looking for assignments whose value is a call
        # to np.zeros or np.empty that targets 'cloth_displacements'.
        found = False
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "cloth_displacements"
                    for t in node.targets
                )
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr in ("zeros", "empty")
            ):
                found = True
                break
        assert found, (
            "_efit_transfer_displacements does not assign cloth_displacements via "
            "np.zeros() or np.empty().  The ndarray allocation is missing."
        )

    def test_cloth_body_normals_allocated_with_np_zeros(self):
        """cloth_body_normals must be allocated with np.zeros inside
        _efit_transfer_displacements."""
        func = self._func()
        found = False
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "cloth_body_normals"
                    for t in node.targets
                )
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr in ("zeros", "empty")
            ):
                found = True
                break
        assert found, (
            "_efit_transfer_displacements does not assign cloth_body_normals via "
            "np.zeros() or np.empty().  The ndarray allocation is missing."
        )


# ===========================================================================
# TestSmoothDisplacementsNdarrayFastpath
#
# Validates that state._smooth_displacements has the isinstance guard that
# enables the ndarray fast-path, bypassing the .to_tuple() generator.
# ===========================================================================

class TestSmoothDisplacementsNdarrayFastpath:

    @staticmethod
    def _func():
        tree = _parse("elastic_fit/state.py")
        func = _get_func_node(tree, "_smooth_displacements")
        assert func is not None, (
            "_smooth_displacements not found in elastic_fit/state.py"
        )
        return func

    def test_isinstance_ndarray_guard_exists(self):
        """_smooth_displacements must contain an isinstance(…, np.ndarray) check.

        This guard is the entry point for the fast-path that skips the
        .to_tuple() generator.  Without it, every preview tick runs the slow
        dict-based code path even when the input is already an ndarray.
        """
        func = self._func()
        found = False
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "isinstance"
                and len(node.args) >= 2
            ):
                # Second arg must reference ndarray (as an attribute: np.ndarray)
                second_arg = node.args[1]
                if (
                    isinstance(second_arg, ast.Attribute)
                    and second_arg.attr == "ndarray"
                ):
                    found = True
                    break
        assert found, (
            "_smooth_displacements does not contain an isinstance(…, np.ndarray) check. "
            "The ndarray fast-path gate is missing from elastic_fit/state.py."
        )

    def test_smooth_displacements_does_not_require_to_tuple_on_ndarray_path(self):
        """Verify .to_tuple() is not the first thing called in _smooth_displacements.

        The function must have the isinstance guard before any .to_tuple() call.
        This is verified by confirming that the isinstance node's line number is
        less than (or there is no) to_tuple call node.
        """
        func = self._func()

        isinstance_lineno = None
        to_tuple_linenos = []

        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "isinstance"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Attribute)
                and node.args[1].attr == "ndarray"
            ):
                if isinstance_lineno is None:
                    isinstance_lineno = node.lineno

            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to_tuple"
            ):
                to_tuple_linenos.append(node.lineno)

        assert isinstance_lineno is not None, (
            "isinstance(…, np.ndarray) guard not found in _smooth_displacements"
        )

        for lineno in to_tuple_linenos:
            assert lineno > isinstance_lineno, (
                f".to_tuple() appears at line {lineno} before the isinstance check "
                f"at line {isinstance_lineno}. The fast-path guard must come first."
            )


# ===========================================================================
# TestPreviewHotPathNoDictPatterns
#
# Source-text regression checks on preview.py to prevent re-introduction of
# the dict-based patterns that the S02 migration removed.
# ===========================================================================

class TestPreviewHotPathNoDictPatterns:

    @staticmethod
    def _src() -> str:
        return _load("elastic_fit/preview.py")

    def test_no_adjusted_displacements_dict_literal(self):
        """adjusted_displacements must NOT be initialised as an empty dict.

        The for-loop that built a {vi: Vector} dict was replaced by the numpy
        broadcast ``cloth_displacements + cloth_body_normals * offset_delta``.
        Re-introducing the dict literal would silently fall back to the slow
        path and break downstream ndarray consumers.
        """
        assert "adjusted_displacements = {}" not in self._src(), (
            "elastic_fit/preview.py contains 'adjusted_displacements = {}'. "
            "The vectorized numpy broadcast (S02-T01) appears to have been reverted."
        )

    def test_no_cloth_body_normals_vi_subscript(self):
        """cloth_body_normals[vi] must NOT appear in preview.py.

        After migration cloth_body_normals is an ndarray addressed by positional
        row index (not vertex index).  A [vi] subscript would either raise an
        IndexError for large vertex indices or silently return the wrong row.
        """
        assert "cloth_body_normals[vi]" not in self._src(), (
            "elastic_fit/preview.py contains 'cloth_body_normals[vi]' dict-keyed "
            "access.  This must use positional indexing (cloth_body_normals[pos, ...]) "
            "after the S02-T01 ndarray migration."
        )

    def test_no_cloth_displacements_vi_subscript(self):
        """cloth_displacements[vi] must NOT appear in preview.py.

        Same rationale as cloth_body_normals: the array is now positionally
        indexed, not vertex-index keyed.
        """
        assert "cloth_displacements[vi]" not in self._src(), (
            "elastic_fit/preview.py contains 'cloth_displacements[vi]' dict-keyed "
            "access.  Use positional indexing after the S02-T01 ndarray migration."
        )

    def test_no_to_tuple_in_preview(self):
        """preview.py must NOT call .to_tuple() anywhere.

        .to_tuple() was required when displacements were mathutils.Vector objects.
        After the ndarray migration the hot path passes ndarrays directly to
        _smooth_displacements, which has its own isinstance fast-path.  Any
        .to_tuple() in preview.py indicates a reversion or an unconverted legacy
        code path feeding the preview loop.
        """
        assert ".to_tuple()" not in self._src(), (
            "elastic_fit/preview.py contains '.to_tuple()'.  "
            "This Vector→tuple conversion should not appear after the S02-T01 ndarray "
            "migration — preview.py must pass ndarrays directly to _smooth_displacements."
        )


# ===========================================================================
# TestProfilingInstrumentationPreserved
#
# Non-regression guard: the S01 profiling instrumentation (perf_counter calls
# and _dev_mode-gated print blocks) must still be present in preview.py after
# the S02 hot-path changes.
# ===========================================================================

class TestProfilingInstrumentationPreserved:

    MIN_PERF_COUNTER = 16
    MIN_DEV_MODE_GUARDS = 9

    @staticmethod
    def _src() -> str:
        return _load("elastic_fit/preview.py")

    def test_perf_counter_count(self):
        """preview.py must contain at least {min} perf_counter references.

        Each timing section boundary uses time.perf_counter().  Dropping below
        {min} means a timing block was accidentally deleted during hot-path edits.
        """.format(min=TestProfilingInstrumentationPreserved.MIN_PERF_COUNTER)
        src = self._src()
        count = src.count("perf_counter")
        assert count >= self.MIN_PERF_COUNTER, (
            f"elastic_fit/preview.py has only {count} 'perf_counter' references; "
            f"expected >= {self.MIN_PERF_COUNTER}.  S01 profiling instrumentation "
            f"may have been partially removed."
        )

    def test_dev_mode_guard_count(self):
        """preview.py must contain at least {min} 'if _dev_mode:' guards.

        Each developer-mode diagnostic block is wrapped in 'if _dev_mode:'.
        Dropping below {min} means a guard was accidentally deleted.
        """.format(min=TestProfilingInstrumentationPreserved.MIN_DEV_MODE_GUARDS)
        src = self._src()
        count = src.count("if _dev_mode:")
        assert count >= self.MIN_DEV_MODE_GUARDS, (
            f"elastic_fit/preview.py has only {count} 'if _dev_mode:' guards; "
            f"expected >= {self.MIN_DEV_MODE_GUARDS}.  S01 diagnostic blocks "
            f"may have been partially removed."
        )
