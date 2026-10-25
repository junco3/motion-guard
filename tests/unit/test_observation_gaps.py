import numpy as np
from motionguard_core.compare import observation_gaps


def fixtures():
    valid = np.ones((97, 18), dtype=bool)
    return valid, valid.copy(), valid.copy(), np.zeros((97, 18)), np.ones((97, 18)), np.ones((97, 18))


def inspect(values):
    return observation_gaps(*values, {'reference_gt_max_normalized_error': .15, 'min_estimator_score': .5}, 24)


def test_gap_retains_joint_frame_duration_and_exclusion_reason():
    valid, available, visible, error, rs, gs = fixtures()
    valid[30:36, 10] = False
    visible[30:33, 10] = False
    gs[33:36, 10] = .1
    result = inspect((valid, available, visible, error, rs, gs))
    assert not result['affects_verdict']
    assert result['intervals'] == [{
        'type': 'OBSERVATION_GAP', 'joints': [10], 'frames': [30, 35],
        't_start_s': 30/24, 't_end_s': 36/24,
        'excluded_reason_counts': {'visibility_evidence': 3, 'generated_score': 3}}]


def test_brief_gaps_and_nonterminal_joints_are_not_claimed_as_terminal_intervals():
    values = fixtures()
    values[0][:5, 4] = False
    values[0][:, 2] = False
    assert inspect(values)['intervals'] == []


def test_final_frame_gap_is_included_and_normal_has_none():
    values = fixtures()
    assert inspect(values)['intervals'] == []
    values[0][-6:, 13] = False
    values[3][-6:, 13] = .3
    row = inspect(values)['intervals'][0]
    assert row['frames'] == [91, 96]
    assert row['t_end_s'] == 97/24
    assert row['excluded_reason_counts'] == {'reference_gt_error': 6}
