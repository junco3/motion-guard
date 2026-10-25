import numpy as np
import pytest
from test_compare import sample
from motionguard_core.framing_diagnostic import measure


def test_constant_framing_does_not_become_growth_or_drift():
    r, _, _ = sample(); a = np.asarray(r['points']); g = a * 1.2 + [30, 50]
    out = measure(a, g, np.ones((97, 18), bool))
    assert out['baseline_frames'] == list(range(6))
    assert max(abs(x['relative_to_baseline']) for x in out['frames']) < 1e-12
    assert max(x['hip_residual_distance_px'] for x in out['frames']) < 1e-10
    assert out['automatic_failure'] is False


def test_late_growth_remains_visible():
    r, _, _ = sample(); a = np.asarray(r['points']); scale = np.ones(97); scale[50:] = 1.4
    out = measure(a, a * scale[:, None, None], np.ones((97, 18), bool))
    assert abs(out['frames'][96]['relative_to_baseline'] - .4) < 1e-12


def test_missing_torso_never_invented():
    r, _, _ = sample(); a = np.asarray(r['points']); valid = np.zeros((97, 18), bool)
    assert measure(a, a, valid)['status'] == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('mode', ['length', 'joints', 'valid', 'zero_fps', 'nan_fps'])
def test_invalid_inputs_rejected(mode):
    r, _, _ = sample(); a = np.asarray(r['points']); g = a.copy(); valid = np.ones((97, 18), bool); fps = 24
    if mode == 'length': g = g[:-1]
    elif mode == 'joints': a = a[:, :10]
    elif mode == 'valid': valid = valid[:-1]
    elif mode == 'zero_fps': fps = 0
    elif mode == 'nan_fps': fps = float('nan')
    with pytest.raises(ValueError, match='Invalid framing'): measure(a, g, valid, fps)
