import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'core')]
from head_check import check  # noqa: E402

T = json.loads((ROOT / 'config/thresholds.yaml').read_text(encoding='utf-8'))


def pose(n, nose_drop=0.0, frames=None):
    p = np.zeros((n, 18, 2))
    p[:, 2] = [90, 100]; p[:, 5] = [110, 100]; p[:, 8] = [92, 160]; p[:, 11] = [108, 160]  # torso 60 px
    p[:, 0] = [100, 80]
    if frames is not None:
        p[frames, 0, 1] += nose_drop * 60
    return {'points': p.tolist(), 'scores': np.full((n, 18), 0.9).tolist()}


REPORT = {'metrics': {'time_shift': {'frames': 0}, 'M8_framing': {'scale': 1.0, 'translation_px': [0, 0]}}}


def test_bowed_head_held_for_seconds_warns():
    result = check(pose(97), pose(97, 0.5, slice(30, 80)), REPORT, T)
    assert result['status'] == 'warning' and result['affects_verdict'] is False
    assert result['intervals'][0]['frames'] == [30, 79]


def test_small_or_brief_head_difference_is_clear():
    assert check(pose(97), pose(97, 0.2, slice(30, 80)), REPORT, T)['status'] == 'clear'
    assert check(pose(97), pose(97, 0.5, slice(30, 45)), REPORT, T)['status'] == 'clear'
