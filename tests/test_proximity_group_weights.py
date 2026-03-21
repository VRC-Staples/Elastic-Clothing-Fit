# tests/test_proximity_group_weights.py
#
# Unit tests for _compute_proximity_group_weights in elastic_fit/state.py.
#
# state.py imports bpy at module level so it cannot be imported in a plain
# Python context.  The two functions under test are extracted here with numpy
# replaced by equivalent pure-Python logic so the tests run without numpy or
# bpy in the test environment.

import math
import pytest


# ---------------------------------------------------------------------------
# Extracted logic (mirrors elastic_fit/state.py exactly)
# ---------------------------------------------------------------------------

def _proximity_curve_linear(t):
    return 1.0 - t


def _proximity_curve_smooth(t):
    s = 1.0 - t
    return s * s * (3.0 - 2.0 * s)


def _proximity_curve_sharp(t):
    return (1.0 - t) ** 2


def _proximity_curve_root(t):
    return math.sqrt(max(0.0, 1.0 - t))


PROXIMITY_CURVES = {
    'LINEAR': _proximity_curve_linear,
    'SMOOTH': _proximity_curve_smooth,
    'SHARP':  _proximity_curve_sharp,
    'ROOT':   _proximity_curve_root,
}


def _compute_proximity_weights(distances, fitted_indices, start, end, curve_key):
    curve_fn = PROXIMITY_CURVES.get(curve_key, _proximity_curve_smooth)
    span = max(end - start, 0.0001)
    result = {}
    for vi in fitted_indices:
        d = distances.get(vi, 0.0)
        if d <= start:
            result[vi] = 1.0
        elif d >= end:
            result[vi] = 0.0
        else:
            t = (d - start) / span
            t = max(0.0, min(1.0, t))
            result[vi] = curve_fn(t)
    return result


def _compute_proximity_group_weights(cloth, proximity_groups, distances, fitted_indices):
    result = {vi: 1.0 for vi in fitted_indices}

    if not proximity_groups:
        return result

    fitted_set = set(fitted_indices)

    for pg in proximity_groups:
        pg_name = pg.group_name.strip() if pg.group_name else ""
        if not pg_name:
            continue
        vg = cloth.vertex_groups.get(pg_name)
        if vg is None:
            continue
        vg_idx = vg.index

        group_fitted = []
        for v in cloth.data.vertices:
            if v.index not in fitted_set:
                continue
            for g in v.groups:
                if g.group == vg_idx and g.weight > 0.0:
                    group_fitted.append(v.index)
                    break

        if not group_fitted:
            continue

        group_weights = _compute_proximity_weights(
            distances, group_fitted,
            pg.proximity_start, pg.proximity_end, pg.proximity_curve)
        result.update(group_weights)

    return result


# ---------------------------------------------------------------------------
# Minimal stub helpers that mimic enough of the Blender API for tests
# ---------------------------------------------------------------------------

class _VGroup:
    """Stub for bpy vertex group."""
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


class _ProxGroup:
    """Stub for EFitProximityGroup property group."""
    def __init__(self, group_name, proximity_start=0.0, proximity_end=0.1,
                 proximity_curve='SMOOTH'):
        self.group_name = group_name
        self.proximity_start = proximity_start
        self.proximity_end = proximity_end
        self.proximity_curve = proximity_curve


def _make_cloth(n_vertices, group_assignments):
    """Build a _Cloth with n_vertices and group_assignments.

    group_assignments: {group_name: [(vi, weight), ...]}
    Returns (cloth, vgroup_name→index mapping).
    """
    vgroups = {}
    for i, name in enumerate(group_assignments):
        vgroups[name] = i  # assign sequential indices

    # Build per-vertex group refs
    vertex_groups_by_vi = {}
    for gname, members in group_assignments.items():
        gidx = vgroups[gname]
        for vi, w in members:
            vertex_groups_by_vi.setdefault(vi, []).append(_VGroupRef(gidx, w))

    vertices = []
    for vi in range(n_vertices):
        refs = vertex_groups_by_vi.get(vi, [])
        vertices.append(_Vertex(vi, refs))

    vgroup_pairs = list(vgroups.items())  # (name, index)
    cloth = _Cloth(vgroup_pairs, vertices)
    return cloth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeProximityGroupWeights:

    # --- empty / no-group cases ---

    def test_empty_proximity_groups_returns_all_ones(self):
        cloth = _make_cloth(4, {})
        fitted = [0, 1, 2, 3]
        distances = {vi: 0.05 for vi in fitted}
        result = _compute_proximity_group_weights(cloth, [], distances, fitted)
        assert set(result.keys()) == set(fitted)
        assert all(v == pytest.approx(1.0) for v in result.values())

    def test_all_fitted_indices_present_in_result(self):
        """Result must cover every fitted index, even if none is in any group."""
        cloth = _make_cloth(5, {})
        fitted = [0, 1, 2, 3, 4]
        distances = {vi: 0.0 for vi in fitted}
        result = _compute_proximity_group_weights(cloth, [], distances, fitted)
        assert set(result.keys()) == set(fitted)

    def test_group_name_empty_string_treated_as_no_group(self):
        cloth = _make_cloth(3, {})
        fitted = [0, 1, 2]
        distances = {vi: 0.5 for vi in fitted}
        pg = _ProxGroup(group_name="", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert all(v == pytest.approx(1.0) for v in result.values())

    def test_group_name_whitespace_only_treated_as_no_group(self):
        cloth = _make_cloth(3, {})
        fitted = [0, 1, 2]
        distances = {vi: 0.5 for vi in fitted}
        pg = _ProxGroup(group_name="   ")
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert all(v == pytest.approx(1.0) for v in result.values())

    def test_nonexistent_vertex_group_skipped(self):
        """A proximity group referencing a VG that doesn't exist on the cloth is skipped."""
        cloth = _make_cloth(3, {})
        fitted = [0, 1, 2]
        distances = {vi: 0.5 for vi in fitted}
        pg = _ProxGroup(group_name="missing_group", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert all(v == pytest.approx(1.0) for v in result.values())

    # --- basic single-group weighting ---

    def test_grouped_vertices_get_falloff_weight(self):
        """Vertices in the group get < 1.0 when beyond start distance."""
        # vi=0 in group "A", vi=1 not in group
        cloth = _make_cloth(2, {"A": [(0, 1.0)]})
        fitted = [0, 1]
        # vi=0 at distance 0.05 (between start=0 and end=0.1) → should be < 1.0
        distances = {0: 0.05, 1: 0.0}
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1,
                        proximity_curve='LINEAR')
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert result[1] == pytest.approx(1.0), "ungrouped vertex must stay 1.0"
        assert result[0] < 1.0, "grouped vertex beyond start must be < 1.0"
        assert result[0] > 0.0, "grouped vertex before end must be > 0.0"

    def test_ungrouped_vertices_always_get_weight_1(self):
        cloth = _make_cloth(3, {"A": [(0, 1.0)]})
        fitted = [0, 1, 2]
        # vi=0 far beyond end; vi=1,2 not in group
        distances = {0: 1.0, 1: 1.0, 2: 1.0}
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert result[1] == pytest.approx(1.0)
        assert result[2] == pytest.approx(1.0)
        assert result[0] == pytest.approx(0.0)  # beyond end → 0.0

    def test_vertex_at_zero_distance_gets_weight_1(self):
        cloth = _make_cloth(2, {"A": [(0, 1.0)]})
        fitted = [0, 1]
        distances = {0: 0.0, 1: 0.0}
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert result[0] == pytest.approx(1.0)

    def test_vertex_at_end_distance_gets_weight_0(self):
        cloth = _make_cloth(2, {"A": [(0, 1.0)]})
        fitted = [0, 1]
        distances = {0: 0.1, 1: 0.0}
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert result[0] == pytest.approx(0.0)

    # --- multi-group / last-wins ---

    def test_last_group_wins_for_overlapping_vertex(self):
        """When vi belongs to two groups, the last group in the list wins."""
        # vi=0 in both "A" and "B"
        cloth = _make_cloth(1, {"A": [(0, 1.0)], "B": [(0, 1.0)]})
        fitted = [0]
        distances = {0: 0.05}

        pg_a = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1,
                          proximity_curve='LINEAR')
        pg_b = _ProxGroup(group_name="B", proximity_start=0.0, proximity_end=1.0,
                          proximity_curve='LINEAR')  # larger end → lower attenuation

        # A processed first, then B overwrites
        result = _compute_proximity_group_weights(cloth, [pg_a, pg_b], distances, fitted)
        # With B's end=1.0, t = 0.05/1.0 = 0.05; LINEAR weight = 1 - 0.05 = 0.95
        expected = pytest.approx(0.95, abs=1e-6)
        assert result[0] == expected

    def test_two_groups_non_overlapping_vertices(self):
        """Non-overlapping groups each apply their own falloff correctly."""
        cloth = _make_cloth(2, {"A": [(0, 1.0)], "B": [(1, 1.0)]})
        fitted = [0, 1]
        distances = {0: 0.0, 1: 0.5}

        pg_a = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1)
        pg_b = _ProxGroup(group_name="B", proximity_start=0.0, proximity_end=1.0,
                          proximity_curve='LINEAR')

        result = _compute_proximity_group_weights(cloth, [pg_a, pg_b], distances, fitted)
        assert result[0] == pytest.approx(1.0)   # at start → full weight
        # vi=1: t = 0.5 / 1.0 = 0.5; LINEAR = 0.5
        assert result[1] == pytest.approx(0.5, abs=1e-6)

    # --- no fitted members in group ---

    def test_group_with_no_fitted_members_is_skipped(self):
        """A group containing only non-fitted vertices has no effect."""
        cloth = _make_cloth(4, {"A": [(2, 1.0), (3, 1.0)]})  # vertices 2,3 in group
        fitted = [0, 1]  # group members not in fitted set
        distances = {0: 0.5, 1: 0.5}
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx(1.0)

    # --- zero-weight group membership excluded ---

    def test_zero_weight_membership_not_counted(self):
        """Vertices with g.weight == 0 in a group are treated as ungrouped."""
        cloth = _make_cloth(2, {})
        # Manually construct cloth with zero-weight membership
        vg = _VGroup("A", 0)
        cloth._vgroups = {"A": vg}
        cloth.data.vertices[0].groups = [_VGroupRef(0, 0.0)]  # weight 0 — excluded
        cloth.data.vertices[1].groups = []

        fitted = [0, 1]
        distances = {0: 0.5, 1: 0.5}
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx(1.0)

    # --- curve variants smoke test ---

    @pytest.mark.parametrize("curve", ['LINEAR', 'SMOOTH', 'SHARP', 'ROOT'])
    def test_curve_variants_produce_valid_weights(self, curve):
        """Each curve key produces weights in [0, 1] for mid-range distances."""
        cloth = _make_cloth(1, {"A": [(0, 1.0)]})
        fitted = [0]
        distances = {0: 0.05}  # halfway through start=0, end=0.1
        pg = _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.1,
                        proximity_curve=curve)
        result = _compute_proximity_group_weights(cloth, [pg], distances, fitted)
        assert 0.0 <= result[0] <= 1.0

    # --- result covers all fitted_indices ---

    def test_result_always_covers_all_fitted_indices(self):
        """Even with multiple groups, every fitted index is in the result."""
        cloth = _make_cloth(6, {"A": [(0, 1.0), (1, 1.0)], "B": [(2, 1.0)]})
        fitted = list(range(6))
        distances = {vi: float(vi) * 0.02 for vi in fitted}
        pgs = [
            _ProxGroup(group_name="A", proximity_start=0.0, proximity_end=0.05),
            _ProxGroup(group_name="B", proximity_start=0.0, proximity_end=0.1),
        ]
        result = _compute_proximity_group_weights(cloth, pgs, distances, fitted)
        assert set(result.keys()) == set(fitted)
