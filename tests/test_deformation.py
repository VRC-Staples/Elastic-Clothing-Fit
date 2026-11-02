"""Small numerical contracts for the actual Blender-independent fit owner."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(scope='module')
def numeric():
    path = Path(__file__).resolve().parents[1] / 'elastic_fit/deformation.py'
    spec = importlib.util.spec_from_file_location('ecf_deformation_contracts', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def settings(**changes):
    values = dict(fit_amount=0.5, offset=0.0, disp_smooth_passes=0,
                  disp_smooth_threshold=1.0, disp_smooth_min=0.0, disp_smooth_max=1.0,
                  follow_strength=0.0, follow_neighbors=2, fit_mode='FULL',
                  offset_groups=[], exclusive_groups=[])
    values.update(changes)
    return SimpleNamespace(**values)


def test_sparse_fitted_rows_scatter_to_their_vertices_without_mutating_inputs(numeric):
    original = np.arange(27, dtype=np.float64).reshape(9, 3)
    displacement = np.array([[2., 0., 0.], [0., 4., 0.]])
    prepared = numeric.PreparedFit(original, displacement, [7, 2], np.empty((0, 2), dtype=np.int32),
                                   np.zeros((2, 3)))
    result = prepared.evaluate(settings())
    np.testing.assert_array_equal(result[7], [22., 22., 23.])
    np.testing.assert_array_equal(result[2], [6., 9., 8.])
    untouched = [0, 1, 3, 4, 5, 6, 8]
    np.testing.assert_array_equal(result[untouched], original[untouched])
    np.testing.assert_array_equal(original, np.arange(27).reshape(9, 3))
    np.testing.assert_array_equal(displacement, [[2., 0., 0.], [0., 4., 0.]])
    np.testing.assert_array_equal(prepared.evaluate(settings(fit_amount=0.0)), original)


def test_smoothing_keeps_isolated_vertices_and_does_not_borrow_another_session_topology(numeric):
    original = np.zeros((8, 3))
    displacement = np.array([[0., 0., 0.], [2., 0., 0.], [0., 8., 0.]])
    p = settings(fit_amount=1.0, disp_smooth_passes=1, disp_smooth_min=0.5, disp_smooth_max=0.5)
    connected = numeric.PreparedFit(original, displacement, [7, 2, 5],
                                    np.array([[7, 2]], dtype=np.int32), np.zeros((3, 3)))
    isolated = numeric.PreparedFit(original, displacement, [7, 2, 5],
                                   np.empty((0, 2), dtype=np.int32), np.zeros((3, 3)))
    result = connected.evaluate(p)
    np.testing.assert_array_equal(result[[7, 2, 5]], [[1., 0., 0.], [1., 0., 0.], [0., 8., 0.]])
    np.testing.assert_array_equal(isolated.evaluate(p)[[7, 2, 5]], displacement)
    np.testing.assert_array_equal(connected.evaluate(p), result)


def test_smoothing_counts_repeated_edges_but_ignores_self_edges_and_nonfitted_endpoints(numeric):
    original = np.zeros((8, 3))
    original[0] = [20., 30., 40.]
    displacement = np.array([[0., 0., 0.], [6., 0., 0.], [0., 12., 0.], [0., 0., 18.]])
    edges = np.array([[5, 7], [0, 2], [2, 7], [7, 2], [7, 7], [0, 3]], dtype=np.int32)
    original_edges = edges.copy()
    prepared = numeric.PreparedFit(original, displacement, [7, 2, 5, 1], edges, np.zeros((4, 3)))
    p = settings(fit_amount=1., disp_smooth_passes=1, disp_smooth_min=0.5, disp_smooth_max=0.5)
    result = prepared.evaluate(p)
    # Vertex 7 averages two x=6 neighbors and one y=12 neighbor, then blends halfway.
    np.testing.assert_array_equal(result[[7, 2, 5, 1]],
                                  [[2., 2., 0.], [3., 0., 0.], [0., 6., 0.], [0., 0., 18.]])
    np.testing.assert_array_equal(result[[0, 3, 4, 6]], original[[0, 3, 4, 6]])
    np.testing.assert_array_equal(edges, original_edges)


def test_smoothing_retains_small_terms_when_neighbor_displacements_cancel(numeric):
    original = np.zeros((8, 3))
    displacement = np.array([[1e16, 0., 0.], [-1e16, 0., 0.], [1., 0., 0.], [0., 0., 0.]])
    prepared = numeric.PreparedFit(
        original, displacement, [7, 2, 5, 1],
        np.array([[5, 1], [7, 1], [2, 1]], dtype=np.int32), np.zeros((4, 3)))
    p = settings(fit_amount=1., disp_smooth_passes=1, disp_smooth_min=1., disp_smooth_max=1.)
    result = prepared.evaluate(p)
    np.testing.assert_array_equal(result[1], [1. / 3., 0., 0.])
    np.testing.assert_array_equal(result[[7, 2, 5]], np.zeros((3, 3)))


def test_overlapping_offsets_accumulate_and_neutral_influence_changes_nothing(numeric):
    original = np.arange(27, dtype=np.float64).reshape(9, 3)
    groups = [SimpleNamespace(group_name='A', influence=100.),
              SimpleNamespace(group_name='B', influence=100.)]
    prepared = numeric.PreparedFit(original, np.zeros((2, 3)), [7, 2], np.empty((0, 2), dtype=np.int32),
                                   np.array([[1., 0., 0.], [0., 1., 0.]]), original_offset=0.25,
                                   offset_group_weights={'A': {7: 0.5}, 'B': {7: 0.25}})
    p = settings(offset=0.25, offset_groups=groups)
    np.testing.assert_array_equal(prepared.evaluate(p), original)
    groups[0].influence = 200.
    groups[1].influence = 300.
    result = prepared.evaluate(p)
    np.testing.assert_array_equal(result[7], [21.25, 22., 23.])
    np.testing.assert_array_equal(result[[0, 1, 2, 3, 4, 5, 6, 8]], original[[0, 1, 2, 3, 4, 5, 6, 8]])


@pytest.mark.parametrize('group_offset', [False, True])
def test_initial_fit_preserves_float32_mesh_boundaries(numeric, group_offset):
    # This displacement is below half the float32 spacing at x=32.
    epsilon = 3 * 2. ** -21
    original = np.array([[32., 1., 0.], [32., -1., 0.]])
    groups = [SimpleNamespace(group_name='A', influence=200.)] if group_offset else []
    prepared = numeric.PreparedFit(original, np.array([[epsilon, 0., 0.], [epsilon, 0., 0.]]),
                                   [0, 1], np.empty((0, 2), dtype=np.int32), np.array([[1., 0., 0.], [1., 0., 0.]]),
                                   original_offset=epsilon,
                                   offset_group_weights={'A': {0: 1., 1: 1.}} if group_offset else {})
    p = settings(fit_amount=1., offset=epsilon, offset_groups=groups)
    np.testing.assert_array_equal(prepared.evaluate(p, initial_fit=True), original)
    preview_x = 32. + epsilon * (2 if group_offset else 1)
    np.testing.assert_array_equal(prepared.evaluate(p)[:, 0], [preview_x, preview_x])


def test_replacing_offset_membership_discards_previous_scatter_targets(numeric):
    original = np.zeros((8, 3))
    prepared = numeric.PreparedFit(original, np.zeros((2, 3)), [7, 2], np.empty((0, 2), dtype=np.int32),
                                   np.array([[0., 1., 0.], [0., 1., 0.]]), original_offset=0.25,
                                   offset_group_weights={'A': {7: 0.5}})
    p = settings(offset=0.25, offset_groups=[SimpleNamespace(group_name='A', influence=200.)])
    np.testing.assert_array_equal(prepared.evaluate(p)[[7, 2]], [[0., 0.125, 0.], [0., 0., 0.]])
    prepared.set_offset_weights({'A': {2: 0.75}})
    np.testing.assert_array_equal(prepared.evaluate(p)[[7, 2]], [[0., 0., 0.], [0., 0.1875, 0.]])
    prepared.set_offset_weights({})
    np.testing.assert_array_equal(prepared.evaluate(p), original)


@pytest.mark.parametrize(('curve', 'middle'), [
    ('LINEAR', 0.5), ('SMOOTH', 0.5), ('SHARP', 0.25), ('ROOT', 0.7071067811865476),
])
def test_proximity_endpoints_and_midpoint_have_independent_curve_expectations(numeric, curve, middle):
    weights = numeric.compute_proximity_weights(np.array([0., 0.5, 1.]), 0., 1., curve)
    np.testing.assert_allclose(weights, [1., middle, 0.], rtol=0., atol=1e-15)


def test_proximity_weights_scale_fitted_displacement_not_the_original_coordinates(numeric):
    original = np.array([[1., 2., 3.], [4., 5., 6.], [7., 8., 9.]])
    prepared = numeric.PreparedFit(original, np.array([[0., 0., 4.], [0., 0., 4.]]),
                                   [2, 0], np.empty((0, 2), dtype=np.int32), np.zeros((2, 3)))
    result = prepared.evaluate(settings(), proximity_weights=np.array([0.5, 0.]))
    np.testing.assert_array_equal(result, [[1., 2., 3.], [4., 5., 6.], [7., 8., 10.]])


@pytest.fixture
def proximity_case(numeric, monkeypatch):
    package = ModuleType('ecf_proximity_contracts')
    monkeypatch.setitem(sys.modules, package.__name__, package)
    monkeypatch.setitem(sys.modules, package.__name__ + '.deformation', numeric)
    path = Path(__file__).resolve().parents[1] / 'elastic_fit/state.py'
    spec = importlib.util.spec_from_file_location(package.__name__ + '.state', path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    memberships = {0: [(10, 1.)], 7: [(10, 0.125)], 2: [(10, 0.9), (20, 0.01)],
                   8: [(20, 0.8)], 4: [(10, 0.)]}
    cloth = SimpleNamespace(
        vertex_groups={'A': SimpleNamespace(index=10), 'B': SimpleNamespace(index=20)},
        data=SimpleNamespace(vertices=[
            SimpleNamespace(index=vi, groups=[SimpleNamespace(group=g, weight=w) for g, w in groups])
            for vi, groups in memberships.items()]))
    groups = [SimpleNamespace(group_name='A', proximity_start=0., proximity_end=1., proximity_curve='SHARP'),
              SimpleNamespace(group_name='B', proximity_start=0., proximity_end=1., proximity_curve='LINEAR')]
    original = np.zeros((9, 3))
    original[0] = [12., 13., 14.]
    prepared = numeric.PreparedFit(
        original, np.array([[8., 0., 0.], [0., 8., 0.], [0., 0., 8.], [8., 8., 8.]]),
        [7, 2, 8, 4], np.empty((0, 2), dtype=np.int32), np.zeros((4, 3)),
        body_distances=np.array([0.25, 0.5, 0.75, 0.9]))
    p = settings(use_proximity_falloff=True, use_proximity_group_tuning=True, proximity_groups=groups,
                 proximity_start=0., proximity_end=1., proximity_curve='LINEAR')
    return adapter, cloth, p, prepared


@pytest.mark.parametrize('cached_membership', [False, True])
@pytest.mark.parametrize('reverse_groups', [False, True])
def test_proximity_groups_follow_sparse_rows_and_last_group_wins(
        proximity_case, cached_membership, reverse_groups):
    adapter, cloth, p, prepared = proximity_case
    if cached_membership:
        prepared.vg_membership = {10: {7: 0.125, 2: 0.9, 0: 1.}, 20: {2: 0.01, 8: 0.8}}
    if reverse_groups:
        p.proximity_groups.reverse()
    p.proximity_groups[:0] = [SimpleNamespace(group_name=' '), SimpleNamespace(group_name='Missing')]
    result = prepared.evaluate(p, adapter._get_proximity_weights(cloth, p, prepared))
    # Group membership is binary here. Its stored strength does not scale falloff.
    np.testing.assert_array_equal(result[[7, 2, 8, 4]],
                                  [[2.25, 0., 0.], [0., 1. if reverse_groups else 2., 0.],
                                   [0., 0., 1.], [4., 4., 4.]])
    np.testing.assert_array_equal(result[[0, 1, 3, 5, 6]], prepared.originals[[0, 1, 3, 5, 6]])


def test_proximity_cache_waits_for_invalidation_and_disabled_falloff_keeps_full_fit(proximity_case):
    adapter, cloth, p, prepared = proximity_case
    weights = adapter._get_proximity_weights(cloth, p, prepared)
    np.testing.assert_array_equal(prepared.evaluate(p, weights)[7], [2.25, 0., 0.])
    p.proximity_groups.pop(0)
    cached = adapter._get_proximity_weights(cloth, p, prepared)
    np.testing.assert_array_equal(prepared.evaluate(p, cached)[7], [2.25, 0., 0.])
    prepared.proximity_key = None
    refreshed = adapter._get_proximity_weights(cloth, p, prepared)
    np.testing.assert_array_equal(prepared.evaluate(p, refreshed)[7], [4., 0., 0.])
    p.use_proximity_falloff = False
    disabled = adapter._get_proximity_weights(cloth, p, prepared)
    assert disabled is None
    np.testing.assert_array_equal(prepared.evaluate(p, disabled)[[7, 2, 8, 4]],
                                  [[4., 0., 0.], [0., 4., 0.], [0., 0., 4.], [4., 4., 4.]])
    p.use_proximity_falloff = True
    retained = adapter._get_proximity_weights(cloth, p, prepared)
    np.testing.assert_array_equal(prepared.evaluate(p, retained)[8], [0., 0., 1.])


@pytest.mark.parametrize(('start', 'end', 'expected'), [
    (0.5, 0.5, [1., 1., 0., 0.]), (1., 0.5, [1., 1., 1., 0.]),
])
def test_proximity_start_endpoint_takes_precedence_for_empty_or_reversed_intervals(numeric, start, end, expected):
    result = numeric.compute_proximity_weights(np.array([0., 0.5, 1., 2.]), start, end, 'LINEAR')
    np.testing.assert_array_equal(result, expected)


def test_preparation_rejects_displacement_rows_that_do_not_match_fitted_vertices(numeric):
    with pytest.raises(ValueError, match='fitted'):
        numeric.PreparedFit(np.zeros((8, 3)), np.zeros((1, 3)), [7, 2],
                            np.empty((0, 2), dtype=np.int32), np.zeros((2, 3)))
