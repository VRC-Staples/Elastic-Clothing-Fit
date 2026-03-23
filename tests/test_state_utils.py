# tests/test_state_utils.py
#
# Unit tests for pure-Python-extractable utilities in elastic_fit/state.py.
#
# state.py imports bpy and numpy at module level so it cannot be imported in a
# plain Python context.  Functions under test are extracted here with bpy stubs
# replacing the Blender API exactly as in test_proximity_group_weights.py.
#
# Covered:
#   _calc_subdivisions         -- no bpy/numpy dependency, tested directly
#   _compute_offset_group_weights -- bpy-dependent; uses the same stubs as the
#                                    proximity test file

import math
import pytest


# ---------------------------------------------------------------------------
# Extracted logic — _calc_subdivisions (mirrors elastic_fit/state.py exactly)
# ---------------------------------------------------------------------------

def _calc_subdivisions(current_tris, target_tris):
    """Return the number of subdivision levels needed to reach target_tris.

    Each subdivision level multiplies the triangle count by roughly 4.
    Returns at least 1 if the mesh needs to grow, 0 if it is already large enough.
    """
    if current_tris <= 0:
        return 1
    ratio = target_tris / current_tris
    if ratio <= 1:
        return 0
    levels = math.log(ratio) / math.log(4)
    return max(1, round(levels))


# ---------------------------------------------------------------------------
# Minimal bpy stubs (mirrored from test_proximity_group_weights.py)
# ---------------------------------------------------------------------------

class _VGroup:
    def __init__(self, name, index):
        self.name = name
        self.index = index


class _VGroupRef:
    def __init__(self, group_index, weight):
        self.group = group_index
        self.weight = weight


class _Vertex:
    def __init__(self, index, group_refs):
        self.index = index
        self.groups = group_refs


class _MeshData:
    def __init__(self, vertices):
        self.vertices = vertices


class _Cloth:
    def __init__(self, vgroups, vertices):
        self._vgroups = {name: _VGroup(name, idx) for name, idx in vgroups}
        self.data = _MeshData(vertices)

    @property
    def vertex_groups(self):
        return self

    def get(self, name):
        return self._vgroups.get(name)


class _OffsetGroup:
    """Stub for EFitOffsetGroup property group."""
    def __init__(self, group_name):
        self.group_name = group_name


def _make_cloth(n_vertices, group_assignments):
    """Build a _Cloth with n_vertices and group_assignments.

    group_assignments: {group_name: [(vi, weight), ...]}
    """
    vgroups = {name: i for i, name in enumerate(group_assignments)}
    vertex_groups_by_vi = {}
    for gname, members in group_assignments.items():
        gidx = vgroups[gname]
        for vi, w in members:
            vertex_groups_by_vi.setdefault(vi, []).append(_VGroupRef(gidx, w))
    vertices = []
    for vi in range(n_vertices):
        refs = vertex_groups_by_vi.get(vi, [])
        vertices.append(_Vertex(vi, refs))
    vgroup_pairs = list(vgroups.items())
    return _Cloth(vgroup_pairs, vertices)


# ---------------------------------------------------------------------------
# Extracted logic — _compute_offset_group_weights
# (mirrors elastic_fit/state.py exactly)
# ---------------------------------------------------------------------------

def _compute_offset_group_weights(cloth, offset_groups, fitted_indices, vg_membership=None):
    """Return per-vertex weights for each offset group entry.

    Returns {group_name: {vi: weight}} for all groups with non-zero membership
    in fitted_indices.
    """
    fitted_set = set(fitted_indices)
    offset_group_weights = {}
    for og in offset_groups:
        og_name = og.group_name.strip() if og.group_name else ""
        if not og_name:
            continue
        vg = cloth.vertex_groups.get(og_name)
        if vg is None:
            continue
        vg_idx = vg.index
        if vg_membership is not None and vg_idx in vg_membership:
            weights = {}
            for vi in vg_membership[vg_idx]:
                if vi in fitted_set:
                    v = cloth.data.vertices[vi]
                    for g in v.groups:
                        if g.group == vg_idx and g.weight > 0.0:
                            weights[v.index] = g.weight
                            break
        else:
            weights = {}
            for v in cloth.data.vertices:
                if v.index not in fitted_set:
                    continue
                for g in v.groups:
                    if g.group == vg_idx and g.weight > 0.0:
                        weights[v.index] = g.weight
                        break
        if weights:
            offset_group_weights[og_name] = weights
    return offset_group_weights


# ===========================================================================
# Tests: _calc_subdivisions
# ===========================================================================

class TestCalcSubdivisions:

    # --- guard: current_tris <= 0 always returns 1 ---

    def test_zero_current_tris_returns_1(self):
        assert _calc_subdivisions(0, 1000) == 1

    def test_negative_current_tris_returns_1(self):
        assert _calc_subdivisions(-100, 500) == 1

    # --- already large enough ---

    def test_equal_tris_returns_0(self):
        """Current == target: no subdivision needed."""
        assert _calc_subdivisions(1000, 1000) == 0

    def test_current_larger_than_target_returns_0(self):
        """Current already exceeds target."""
        assert _calc_subdivisions(5000, 1000) == 0

    def test_ratio_just_above_1_returns_1(self):
        """Any ratio > 1 returns at least 1 due to max(1, round(levels)).

        log(1.01)/log(4) ≈ 0.007 → round → 0, but max(1, 0) clamps to 1.
        The function guarantees a minimum of 1 subdivision whenever growth is needed.
        """
        assert _calc_subdivisions(1000, 1010) == 1

    # --- level computation ---

    def test_4x_ratio_returns_1(self):
        """4× triangle ratio requires exactly 1 subdivision level."""
        assert _calc_subdivisions(100, 400) == 1

    def test_16x_ratio_returns_2(self):
        """16× triangle ratio requires exactly 2 subdivision levels."""
        assert _calc_subdivisions(100, 1600) == 2

    def test_64x_ratio_returns_3(self):
        """64× triangle ratio requires exactly 3 subdivision levels."""
        assert _calc_subdivisions(100, 6400) == 3

    def test_ratio_between_1_and_4_returns_1(self):
        """Any ratio >1 and <4 rounds to 1 (minimum growth case)."""
        # ratio=2: log(2)/log(4) = 0.5 → round → 0 → max(1, 0) = 1
        assert _calc_subdivisions(100, 200) == 1

    def test_ratio_between_4_and_16_rounds_to_nearest(self):
        """Ratio=8 → log(8)/log(4) = 1.5 → round → 2."""
        assert _calc_subdivisions(100, 800) == 2

    def test_large_current_tris_exact_factor(self):
        """Works correctly for large triangle counts."""
        assert _calc_subdivisions(10_000, 160_000) == 2  # 16× ratio

    def test_minimum_result_is_1_when_growth_needed(self):
        """Result is always at least 1 whenever current < target."""
        # Very small ratio still needs at least 1 level
        result = _calc_subdivisions(99, 100)
        assert result >= 1

    # --- rounding boundary ---

    def test_exact_power_of_4_rounds_correctly(self):
        """Powers of 4 should produce exact integer levels."""
        assert _calc_subdivisions(1, 4) == 1
        assert _calc_subdivisions(1, 16) == 2
        assert _calc_subdivisions(1, 64) == 3
        assert _calc_subdivisions(1, 256) == 4

    def test_single_triangle_target_1_returns_0(self):
        """1 current tri, target 1: ratio=1.0 → returns 0."""
        assert _calc_subdivisions(1, 1) == 0


# ===========================================================================
# Tests: _compute_offset_group_weights
# ===========================================================================

class TestComputeOffsetGroupWeights:

    # --- empty / no-group cases ---

    def test_empty_offset_groups_returns_empty_dict(self):
        cloth = _make_cloth(3, {})
        result = _compute_offset_group_weights(cloth, [], [0, 1, 2])
        assert result == {}

    def test_group_name_empty_string_skipped(self):
        cloth = _make_cloth(3, {})
        og = _OffsetGroup(group_name="")
        result = _compute_offset_group_weights(cloth, [og], [0, 1, 2])
        assert result == {}

    def test_group_name_whitespace_only_skipped(self):
        cloth = _make_cloth(3, {})
        og = _OffsetGroup(group_name="   ")
        result = _compute_offset_group_weights(cloth, [og], [0, 1, 2])
        assert result == {}

    def test_nonexistent_vertex_group_skipped(self):
        cloth = _make_cloth(3, {})
        og = _OffsetGroup(group_name="missing")
        result = _compute_offset_group_weights(cloth, [og], [0, 1, 2])
        assert result == {}

    def test_group_with_no_fitted_members_not_in_result(self):
        """A group whose members are all outside fitted_indices is omitted."""
        cloth = _make_cloth(4, {"A": [(2, 0.8), (3, 0.5)]})
        fitted = [0, 1]  # group members not fitted
        og = _OffsetGroup(group_name="A")
        result = _compute_offset_group_weights(cloth, [og], fitted)
        assert result == {}

    # --- basic weight extraction ---

    def test_single_group_returns_correct_weights(self):
        """Weights are extracted from group membership exactly."""
        cloth = _make_cloth(3, {"A": [(0, 0.75), (1, 0.5)]})
        fitted = [0, 1, 2]
        og = _OffsetGroup(group_name="A")
        result = _compute_offset_group_weights(cloth, [og], fitted)
        assert "A" in result
        assert result["A"][0] == pytest.approx(0.75)
        assert result["A"][1] == pytest.approx(0.5)
        assert 2 not in result["A"]  # vi=2 not in group

    def test_only_fitted_indices_returned(self):
        """Non-fitted vertices in the group are excluded from the result."""
        cloth = _make_cloth(4, {"A": [(0, 1.0), (3, 0.9)]})
        fitted = [0, 1, 2]  # vi=3 not fitted
        og = _OffsetGroup(group_name="A")
        result = _compute_offset_group_weights(cloth, [og], fitted)
        assert 3 not in result.get("A", {})
        assert 0 in result["A"]

    def test_zero_weight_membership_excluded(self):
        """Vertices with weight == 0 are treated as not in the group."""
        cloth = _make_cloth(2, {})
        vg = _VGroup("A", 0)
        cloth._vgroups = {"A": vg}
        cloth.data.vertices[0].groups = [_VGroupRef(0, 0.0)]  # zero weight
        cloth.data.vertices[1].groups = []
        fitted = [0, 1]
        og = _OffsetGroup(group_name="A")
        result = _compute_offset_group_weights(cloth, [og], fitted)
        assert result == {}  # no non-zero members

    # --- multiple groups ---

    def test_two_groups_returned_as_separate_keys(self):
        """Each group appears as a separate key in the result dict."""
        cloth = _make_cloth(3, {"A": [(0, 0.8)], "B": [(1, 0.6)]})
        fitted = [0, 1, 2]
        ogs = [_OffsetGroup("A"), _OffsetGroup("B")]
        result = _compute_offset_group_weights(cloth, ogs, fitted)
        assert "A" in result
        assert "B" in result
        assert result["A"][0] == pytest.approx(0.8)
        assert result["B"][1] == pytest.approx(0.6)

    def test_same_vertex_in_two_groups_appears_in_both(self):
        """A vertex that belongs to two groups is recorded under each."""
        cloth = _make_cloth(2, {"A": [(0, 0.9)], "B": [(0, 0.4)]})
        fitted = [0, 1]
        ogs = [_OffsetGroup("A"), _OffsetGroup("B")]
        result = _compute_offset_group_weights(cloth, ogs, fitted)
        assert result["A"][0] == pytest.approx(0.9)
        assert result["B"][0] == pytest.approx(0.4)

    # --- vg_membership fast path ---

    def test_fast_path_matches_fallback(self):
        """vg_membership fast path produces identical result to vertex iteration."""
        cloth = _make_cloth(4, {"A": [(0, 0.7), (1, 0.3)]})
        fitted = [0, 1, 2, 3]
        og = _OffsetGroup(group_name="A")

        # Build membership the same way pipeline.py does
        fitted_set = set(fitted)
        vg_mem = {}
        for v in cloth.data.vertices:
            if v.index not in fitted_set:
                continue
            for g in v.groups:
                if g.weight > 0.0:
                    vg_mem.setdefault(g.group, set()).add(v.index)

        result_fallback = _compute_offset_group_weights(cloth, [og], fitted, vg_membership=None)
        result_fast = _compute_offset_group_weights(cloth, [og], fitted, vg_membership=vg_mem)

        assert set(result_fallback.keys()) == set(result_fast.keys())
        for gname in result_fallback:
            assert result_fallback[gname] == pytest.approx(result_fast[gname])

    def test_fast_path_excludes_non_fitted(self):
        """vg_membership may include non-fitted verts; fast path must filter them."""
        cloth = _make_cloth(4, {"A": [(0, 1.0), (3, 0.5)]})
        fitted = [0, 1, 2]  # vi=3 not fitted
        og = _OffsetGroup(group_name="A")

        # Build membership including vi=3 (as if built from all vertices)
        vg_mem = {0: {0, 3}}  # vg_idx=0 has members 0 and 3
        result = _compute_offset_group_weights(cloth, [og], fitted, vg_membership=vg_mem)
        assert 3 not in result.get("A", {})
        assert 0 in result["A"]

    def test_fast_path_missing_vg_idx_falls_back_to_iteration(self):
        """If vg_idx not in vg_membership, vertex-iteration fallback is used."""
        cloth = _make_cloth(2, {"A": [(0, 0.6)]})
        fitted = [0, 1]
        og = _OffsetGroup(group_name="A")
        # Empty membership — forces fallback iteration
        result = _compute_offset_group_weights(cloth, [og], fitted, vg_membership={})
        assert "A" in result
        assert result["A"][0] == pytest.approx(0.6)

    # --- group_name stripping ---

    def test_group_name_with_leading_trailing_whitespace_resolved(self):
        """Group names are stripped before lookup — '  A  ' resolves to group 'A'."""
        cloth = _make_cloth(2, {"A": [(0, 0.5)]})
        fitted = [0, 1]
        og = _OffsetGroup(group_name="  A  ")
        result = _compute_offset_group_weights(cloth, [og], fitted)
        assert "A" in result
        assert result["A"][0] == pytest.approx(0.5)
