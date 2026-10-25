import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import observation_display as display


def fixture(tmp_path):
    gt = tmp_path/'joints.json'
    gt.write_text('{}')
    report = {'verdict': 'PASS', 'failures': [], 'uncertain_reasons': [],
              'thresholds_sha256': 'threshold',
              'sources': {'gt': {'path': str(gt), 'sha256': display.sha(gt)},
                          'reference': {'sha256': 'r'}, 'generated': {'sha256': 'g'}}}
    (tmp_path/'report.json').write_text(json.dumps(report))
    for name, digest in [('reference', 'r'), ('generated', 'g')]:
        (tmp_path/f'{name}-pose.json').write_text(json.dumps({'video_sha256': digest}))
    return report


def test_supplement_preserves_original_and_binds_inputs(tmp_path):
    report = fixture(tmp_path);before = (tmp_path/'report.json').read_bytes()
    computed = {**report, 'observation_gaps': {'status': 'available', 'intervals': []}}
    with patch.object(display, 'compare_candidate', return_value=computed):
        assert display.build(tmp_path)['status'] == 'available'
    assert (tmp_path/'report.json').read_bytes() == before
    assert display.validate(tmp_path)['pins']['report'] == display.sha(tmp_path/'report.json')
    (tmp_path/'generated-pose.json').write_text('{}')
    with pytest.raises(ValueError, match='source changed'):
        display.validate(tmp_path)


def test_changed_decision_does_not_add_observations(tmp_path):
    report = fixture(tmp_path)
    with patch.object(display, 'compare_candidate', return_value={**report, 'verdict': 'FAIL'}):
        result = display.build(tmp_path)
    assert result['status'] == 'unavailable'
    assert 'observation_gaps' not in result


def test_pose_from_different_video_is_rejected(tmp_path):
    fixture(tmp_path)
    (tmp_path/'reference-pose.json').write_text('{"video_sha256":"another-video"}')
    with pytest.raises(ValueError, match='pose source changed'):
        display.build(tmp_path)
