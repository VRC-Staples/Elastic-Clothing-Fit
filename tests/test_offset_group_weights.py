# tests/test_offset_group_weights.py
#
# Unit tests for _compute_offset_group_weights in elastic_fit/state.py.
#
# state.py imports bpy at module level so it cannot be imported in a plain
# Python context.  The logic under test is extracted here as a pure-Python
# function (no bpy, no mathutils) matching the implementation exactly.
#
# Key behaviours under test:
#   - Fast-path (vg_membership dict supplied): single dict comprehension, zero RNA reads
#   - Fallback path (vg_membership=None): walks cloth.data.vertices directly
#   - Fast-path and fallback produce identical weight values (parity tests)
#   - fitted_set filtering: vi outside fitted_set excluded even if in vg_membership
#   - Empty / missing group handled gracefully
#   - Sentinel (empty group_name) skipped
#   - Multiple offset groups each get their own result entry

import pytest


# ---------------------------------------------------------------------------
# Extracted pure-Python logic — mirrors elastic_fit/state.py exactly
# ---------------------------------------------------------------------------

def _compute_offset_group_weights(cloth, offset_groups, fitted_indices,
                                  vg_membership=None):
    """Extracted copy of state._compute_offset_group_weights for unit testing.

    Returns {group_name: {vi: weight}} for all offset groups with fitted members
    whose weight > 0.
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
            # Fast-path: weights stored at build time — zero RNA reads.
            weights = {vi: w for vi, w in vg_membership[vg_idx].items()
                       if vi in fitted_set}
        else:
            # Fallback: walk cloth.data.vertices (used when vg_membership=None).
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


# ---------------------------------------------------------------------------
# Minimal stub helpers that mimic enough of the Blender API for tests
# ---------------------------------------------------------------------------

class _VGroup:
    """Stub for a Blender vertex group."""
    def __init__(self, name, index):
        self.name = name
        self.index = index


class _VGroupRef:
    """Stub for a per-vertex group reference (v.groups entry)."""
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
    """Minimal cloth object stub."""
    def __init__(self, vgroups, vertices):
        # vgroups: list of (name, index) pairs
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
    Returns a _Cloth instance.
    """
    vgroups = {}
    for i, name in enumerate(group_assignments):
        vgroups[name] = i  # assign sequential indices

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
    cloth = _Cloth(vgroup_pairs, vertices)
    return cloth


def _build_vg_membership_weight_dict(cloth, fitted_indices):
    """Build {vg_idx: {vi: weight}} the same way pipeline.py does (post-T02 shape)."""
    fitted_set = set(fitted_indices)
    vg_membership = {}
    for v in cloth.data.vertices:
        if v.index not in fitted_set:
            continue
        for g in v.groups:
            if g.weight > 0.0:
                vg_membership.setdefault(g.group, {})[v.index] = g.weight
    return vg_membership


# ---------------------------------------------------------------------------
# Tests: fast-path / fallback parity
# ---------------------------------------------------------------------------

class TestOffsetGroupWeightsParity:
    """Prove fast-path (weight-dict vg_membership) == fallback (vg_membership=None)."""

    def test_parity_single_group(self):
        """Single offset group: fast-path produces same weights as fallback."""
        cloth = _make_cloth(4, {"A": [(0, 0.8), (1, 1.0), (2, 0.4)]})
        fitted = [0, 1, 2, 3]
        og = _OffsetGroup("A")

        result_fallback = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=None)
        vg_mem = _build_vg_membership_weight_dict(cloth, fitted)
        result_fast = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)

        assert set(result_fallback.keys()) == {"A"}
        assert set(result_fast.keys()) == {"A"}
        for vi in [0, 1, 2]:
            assert result_fast["A"][vi] == pytest.approx(result_fallback["A"][vi], abs=1e-9), \
                f"vi={vi}: fast={result_fast['A'][vi]}, fallback={result_fallback['A'][vi]}"
        assert 3 not in result_fast["A"], "vi=3 has no group membership"

    def test_parity_multiple_groups(self):
        """Two offset groups: fast-path matches fallback for both."""
        cloth = _make_cloth(5, {
            "ArmL": [(0, 1.0), (1, 0.5)],
            "ArmR": [(2, 0.7), (3, 0.9)],
        })
        fitted = [0, 1, 2, 3, 4]
        ogs = [_OffsetGroup("ArmL"), _OffsetGroup("ArmR")]

        result_fallback = _compute_offset_group_weights(
            cloth, ogs, fitted, vg_membership=None)
        vg_mem = _build_vg_membership_weight_dict(cloth, fitted)
        result_fast = _compute_offset_group_weights(
            cloth, ogs, fitted, vg_membership=vg_mem)

        for gname in ("ArmL", "ArmR"):
            assert gname in result_fallback
            assert gname in result_fast
            for vi in result_fallback[gname]:
                assert result_fast[gname][vi] == pytest.approx(
                    result_fallback[gname][vi], abs=1e-9), \
                    f"gname={gname}, vi={vi}"

    def test_parity_partial_weights(self):
        """Non-uniform weights are preserved exactly through the fast-path."""
        weights_in = [(0, 0.1), (1, 0.25), (2, 0.5), (3, 0.75), (4, 1.0)]
        cloth = _make_cloth(5, {"G": weights_in})
        fitted = list(range(5))
        og = _OffsetGroup("G")

        _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=None)
        vg_mem = _build_vg_membership_weight_dict(cloth, fitted)
        result_fast = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)

        for vi, expected_w in weights_in:
            assert result_fast["G"][vi] == pytest.approx(expected_w, abs=1e-9), \
                f"vi={vi}: expected {expected_w}, got {result_fast['G'][vi]}"


# ---------------------------------------------------------------------------
# Tests: fitted_set filtering
# ---------------------------------------------------------------------------

class TestOffsetGroupWeightsFittedSetFiltering:
    """Vertices outside fitted_set must be excluded even if present in vg_membership."""

    def test_non_fitted_vi_excluded_from_fast_path(self):
        """vg_membership built with more vertices than fitted — extras excluded."""
        cloth = _make_cloth(5, {"G": [(0, 1.0), (1, 0.5), (4, 0.8)]})
        fitted = [0, 1, 2, 3]   # vi=4 is NOT fitted
        og = _OffsetGroup("G")

        # Build membership including vi=4
        vg_mem = _build_vg_membership_weight_dict(cloth, list(range(5)))
        result = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)

        assert "G" in result
        assert 4 not in result["G"], "vi=4 is not fitted and must be excluded"
        assert 0 in result["G"]
        assert 1 in result["G"]

    def test_non_fitted_vi_excluded_from_fallback(self):
        """Fallback also excludes non-fitted vertices (regression guard)."""
        cloth = _make_cloth(5, {"G": [(0, 1.0), (4, 0.8)]})
        fitted = [0, 1, 2, 3]
        og = _OffsetGroup("G")

        result = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=None)

        assert "G" in result
        assert 4 not in result["G"]
        assert 0 in result["G"]

    def test_all_members_outside_fitted_returns_no_entry(self):
        """When all group members are non-fitted, the group is omitted from result."""
        cloth = _make_cloth(4, {"G": [(2, 1.0), (3, 1.0)]})
        fitted = [0, 1]   # group members 2, 3 not fitted

        og = _OffsetGroup("G")

        # Fast-path
        vg_mem = _build_vg_membership_weight_dict(cloth, list(range(4)))
        result_fast = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)
        assert "G" not in result_fast, "empty weight dict → group omitted"

        # Fallback
        result_fallback = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=None)
        assert "G" not in result_fallback


# ---------------------------------------------------------------------------
# Tests: empty / missing group handling
# ---------------------------------------------------------------------------

class TestOffsetGroupWeightsEdgeCases:

    def test_empty_group_name_skipped(self):
        """group_name='' is the sentinel for no group selected — must be skipped."""
        cloth = _make_cloth(2, {})
        og = _OffsetGroup("")
        result = _compute_offset_group_weights(cloth, [og], [0, 1])
        assert result == {}

    def test_whitespace_only_group_name_skipped(self):
        """Whitespace-only names are stripped to '' and skipped."""
        cloth = _make_cloth(2, {})
        og = _OffsetGroup("   ")
        result = _compute_offset_group_weights(cloth, [og], [0, 1])
        assert result == {}

    def test_group_name_not_in_cloth_vertex_groups_skipped(self):
        """A group_name that doesn't exist on the cloth is skipped."""
        cloth = _make_cloth(2, {})  # no vertex groups
        og = _OffsetGroup("DoesNotExist")
        result = _compute_offset_group_weights(cloth, [og], [0, 1])
        assert result == {}

    def test_empty_offset_groups_list_returns_empty(self):
        """No offset groups → empty result dict."""
        cloth = _make_cloth(3, {"A": [(0, 1.0)]})
        result = _compute_offset_group_weights(cloth, [], [0, 1, 2])
        assert result == {}

    def test_empty_vg_membership_for_group_triggers_fallback(self):
        """vg_membership dict present but missing this vg_idx → fallback path runs."""
        cloth = _make_cloth(3, {"A": [(0, 1.0), (1, 0.5)]})
        fitted = [0, 1, 2]
        og = _OffsetGroup("A")

        vg_mem = {}  # deliberately empty — vg_idx 0 not present
        result = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)

        # Fallback iterates vertices and finds A's members
        assert "A" in result
        assert result["A"][0] == pytest.approx(1.0)
        assert result["A"][1] == pytest.approx(0.5)
        assert 2 not in result["A"]

    def test_zero_weight_vertex_excluded(self):
        """Vertices with g.weight == 0.0 are excluded by both paths."""
        cloth = _make_cloth(3, {})
        vg = _VGroup("A", 0)
        cloth._vgroups = {"A": vg}
        # vi=0: weight 0 → excluded; vi=1: weight 0.6 → included
        cloth.data.vertices[0].groups = [_VGroupRef(0, 0.0)]
        cloth.data.vertices[1].groups = [_VGroupRef(0, 0.6)]
        cloth.data.vertices[2].groups = []

        fitted = [0, 1, 2]
        og = _OffsetGroup("A")

        # Fallback path
        result_fallback = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=None)
        assert 0 not in result_fallback.get("A", {})
        assert result_fallback["A"][1] == pytest.approx(0.6)

        # Fast-path: build membership manually with weight 0 excluded
        vg_mem = _build_vg_membership_weight_dict(cloth, fitted)
        result_fast = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)
        assert 0 not in result_fast.get("A", {})
        assert result_fast["A"][1] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Tests: multiple groups in sequence
# ---------------------------------------------------------------------------

class TestOffsetGroupWeightsMultipleGroups:

    def test_three_groups_each_get_own_entry(self):
        """Three distinct offset groups each produce a separate result key."""
        cloth = _make_cloth(6, {
            "Leg": [(0, 1.0), (1, 0.8)],
            "Arm": [(2, 0.9)],
            "Torso": [(3, 0.5), (4, 0.5), (5, 1.0)],
        })
        fitted = list(range(6))
        ogs = [_OffsetGroup("Leg"), _OffsetGroup("Arm"), _OffsetGroup("Torso")]

        vg_mem = _build_vg_membership_weight_dict(cloth, fitted)
        result = _compute_offset_group_weights(cloth, ogs, fitted, vg_membership=vg_mem)

        assert set(result.keys()) == {"Leg", "Arm", "Torso"}
        assert result["Leg"] == {0: pytest.approx(1.0), 1: pytest.approx(0.8)}
        assert result["Arm"] == {2: pytest.approx(0.9)}
        assert result["Torso"] == {
            3: pytest.approx(0.5), 4: pytest.approx(0.5), 5: pytest.approx(1.0)
        }

    def test_duplicate_group_name_last_entry_wins(self):
        """If the same group_name appears twice in offset_groups, last wins in result."""
        # This tests that the result dict uses group_name as key, so second write
        # overwrites first. The function doesn't de-duplicate — it's pass-by-pass.
        cloth = _make_cloth(3, {"G": [(0, 1.0), (1, 0.5)]})
        fitted = [0, 1, 2]
        # Two offset group entries for the same vertex group
        ogs = [_OffsetGroup("G"), _OffsetGroup("G")]

        result = _compute_offset_group_weights(
            cloth, ogs, fitted, vg_membership=None)

        # Result has one "G" entry (dict key), last write wins
        assert "G" in result
        assert len(result) == 1

    def test_mix_of_valid_and_empty_group_names(self):
        """Empty sentinel group_names are skipped; valid ones are processed."""
        cloth = _make_cloth(3, {"Valid": [(0, 1.0)]})
        fitted = [0, 1, 2]
        ogs = [
            _OffsetGroup(""),
            _OffsetGroup("Valid"),
            _OffsetGroup("   "),
        ]

        result = _compute_offset_group_weights(
            cloth, ogs, fitted, vg_membership=None)

        assert set(result.keys()) == {"Valid"}
        assert 0 in result["Valid"]


# ---------------------------------------------------------------------------
# Tests: fast-path has zero RNA reads
# ---------------------------------------------------------------------------

class TestOffsetGroupWeightsFastPathNoRNAReads:
    """Verify the fast-path dictionary comprehension does NOT access cloth.data.vertices."""

    def test_fast_path_does_not_touch_vertices(self):
        """When vg_membership is supplied, cloth.data.vertices must not be accessed."""

        class _PoisonedVertices:
            """Raises on any iteration — catches accidental vertex reads."""
            def __iter__(self):
                raise AssertionError(
                    "_compute_offset_group_weights fast-path accessed "
                    "cloth.data.vertices — zero RNA reads required")

            def __getitem__(self, idx):
                raise AssertionError(
                    f"_compute_offset_group_weights accessed vertex {idx} "
                    "— fast-path must use vg_membership dict only")

        cloth = _make_cloth(3, {"G": [(0, 0.8), (1, 1.0)]})
        # Swap out vertices for poisoned version
        cloth.data.vertices = _PoisonedVertices()

        fitted = [0, 1, 2]
        og = _OffsetGroup("G")
        vg_mem = {0: {0: 0.8, 1: 1.0}}  # vg_idx=0 → {vi: weight}

        # Must NOT raise
        result = _compute_offset_group_weights(
            cloth, [og], fitted, vg_membership=vg_mem)

        assert "G" in result
        assert result["G"][0] == pytest.approx(0.8)
        assert result["G"][1] == pytest.approx(1.0)
