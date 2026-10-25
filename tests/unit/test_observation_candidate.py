from copy import deepcopy
import pytest
from test_compare import sample
from motionguard_core.compare import compare
from motionguard_core.observation_candidate import compare_candidate, POLICY


def hidden_extremities():
    r, g, gt = sample()
    gt['meta']['motion_observation_policy'] = POLICY
    for frame in gt['frames']:
        for j in (4, 7, 10, 13):
            frame['joints'][j].update(visibility='uncertain', surface_evidence={
                'method': 'blender-evaluated-first-hit-local-skin-v1',
                'opaque': True, 'first_hit_render_surface': True, 'owned_weight': 1.,
                'nearest_owned_surface_distance': .02, 'hit_joint_distance': .05})
    return r, g, gt


def test_observed_motion_recovers_without_mutating_gt():
    r, g, gt = hidden_extremities(); before = deepcopy(gt)
    out = compare_candidate(r, g, gt)
    assert len(out['observation_policy']['added_joint_frames']) == 388
    assert out['verdict'] == 'PASS'
    assert gt == before
    assert out['observation_policy']['thresholds_unchanged']


@pytest.mark.parametrize('mode', ['unknown_opacity', 'transparent', 'occluded', 'outside', 'other_owner', 'nan', 'unsupported'])
def test_missing_or_conflicting_evidence_never_promoted(mode):
    r, g, gt = hidden_extremities()
    for frame in gt['frames']:
        for j in (4, 7, 10, 13):
            x = frame['joints'][j]; e = x['surface_evidence']
            if mode == 'unknown_opacity': e.pop('opaque')
            elif mode == 'transparent': e['opaque'] = False
            elif mode == 'occluded': x['visibility'] = 'occluded'
            elif mode == 'outside': x['in_frame'] = False
            elif mode == 'other_owner': e['owned_weight'] = .2
            elif mode == 'nan': e['hit_joint_distance'] = float('nan')
            elif mode == 'unsupported': e['method'] = 'unknown'
    assert not compare_candidate(r, g, gt)['observation_policy']['added_joint_frames']


@pytest.mark.parametrize('mode', ['clean', 'swap', 'freeze', 'delay'])
def test_strict_side_findings_and_attribution_identical(mode):
    r, g, gt = hidden_extremities()
    if mode == 'swap':
        for p in g['points']: p[3], p[6] = p[6], p[3]
    elif mode == 'freeze': g['points'] = [deepcopy(g['points'][0]) for _ in g['points']]
    elif mode == 'delay': g['points'] = [deepcopy(g['points'][0]) for _ in range(12)] + g['points'][:-12]
    strict = compare(r, g, gt); out = compare_candidate(r, g, gt)
    assert out['metrics']['M2_side'] == strict['metrics']['M2_side']
    assert out['coverage']['side_judgeable_frames'] == strict['coverage']['side_judgeable_frames']
    for field, kind in [('failures', 'WRONG_SIDE'), ('flags', 'SIDE_ATTRIBUTION_UNCERTAIN')]:
        assert [x for x in out[field] if x['type'] == kind] == [x for x in strict[field] if x['type'] == kind]


def test_opt_in_required():
    r, g, gt = hidden_extremities(); gt['meta'].pop('motion_observation_policy')
    assert compare_candidate(r, g, gt) == compare(r, g, gt)


def test_degenerate_torso_preserves_early_uncertain():
    r, g, gt = hidden_extremities()
    for f in gt['frames']:
        for j in (2, 5, 8, 11): f['joints'][j]['pixel'] = [0, 0]
    assert compare_candidate(r, g, gt) == compare(r, g, gt)


def test_legacy_blender_method_without_render_provenance_not_promoted():
    r, g, gt = hidden_extremities()
    for f in gt['frames']:
        for j in (4, 7, 10, 13): f['joints'][j]['surface_evidence'].pop('first_hit_render_surface')
    assert not compare_candidate(r, g, gt)['observation_policy']['added_joint_frames']
