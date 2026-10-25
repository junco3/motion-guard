"""Local display supplement; never replaces a remote verdict or signed report."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from run_paths import run_file
from motionguard_core.observation_candidate import compare_candidate
import motionguard_core.compare as compare_module
import motionguard_core.observation_candidate as policy_module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def code_pins():
    return {name: sha(path) for name, path in
            [('observation_display.py', __file__), ('compare.py', compare_module.__file__),
             ('observation_candidate.py', policy_module.__file__)]}


def build(directory):
    directory = Path(directory)
    report = json.loads((directory/'report.json').read_text(encoding='utf-8'))
    gt = run_file(directory.parent, report['sources']['gt']['path'])
    paths = {'report': directory/'report.json', 'gt': gt,
             'reference_pose': directory/'reference-pose.json',
             'generated_pose': directory/'generated-pose.json'}
    pins = {key: sha(path) for key, path in paths.items()}
    result = {'schema': 'local-observation-display-1', 'pins': pins,
              'code_sha256': sha(__file__), 'code_pins': code_pins(), 'remote_report_modified': False,
              'status': 'unavailable'}
    if pins['gt'] != report['sources']['gt']['sha256']:
        raise ValueError('Observation supplement GT changed')
    r = json.loads(paths['reference_pose'].read_text(encoding='utf-8'))
    g = json.loads(paths['generated_pose'].read_text(encoding='utf-8'))
    if any(pose['video_sha256'] != report['sources'][role]['sha256']
           for pose, role in ((r, 'reference'), (g, 'generated'))):
        raise ValueError('Observation supplement pose source changed')
    current = compare_candidate(r, g, json.loads(gt.read_text(encoding='utf-8')))
    keys = ('verdict', 'failures', 'uncertain_reasons', 'thresholds_sha256')
    if any(current.get(key) != report.get(key) for key in keys):
        result['reason'] = 'Recomputed decisions differ; original verdict preserved'
    elif current.get('observation_gaps', {}).get('status') == 'available':
        result.update(status='available', observation_gaps=current['observation_gaps'])
    else:
        result['reason'] = 'Detailed observations unavailable'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='observation-gaps-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory/'observation-gaps.json')
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return result


def validate(directory):
    directory = Path(directory)
    result = json.loads((directory/'observation-gaps.json').read_text(encoding='utf-8'))
    report = json.loads((directory/'report.json').read_text(encoding='utf-8'))
    paths = {'report': directory/'report.json', 'gt': run_file(directory.parent, report['sources']['gt']['path']),
             'reference_pose': directory/'reference-pose.json',
             'generated_pose': directory/'generated-pose.json'}
    if (result.get('schema') != 'local-observation-display-1'
            or result.get('code_pins') != code_pins()
            or result.get('pins') != {k: sha(p) for k, p in paths.items()}):
        raise ValueError('Observation supplement source changed')
    return result
