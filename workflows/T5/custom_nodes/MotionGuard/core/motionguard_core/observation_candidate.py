"""Opt-in calibration candidate. Does not replace the production compare policy."""
from copy import deepcopy
import math
from .compare import compare, display_evidence

POLICY = 'owned-first-hit-v1'
SIDE_REASONS = {'side_unjudgeable', 'side_attribution_confounded'}
METHODS = {'blender-evaluated-first-hit-local-skin-v1',
           'first-hit-local-parent-self-child-with-self-child-radius-v2'}


def eligible(joint):
    e = joint.get('surface_evidence', {})
    if not (joint.get('available') and joint.get('in_frame')):
        return False
    if joint.get('visibility') != 'uncertain':
        return False
    if e.get('method') not in METHODS or e.get('opaque') is not True:
        return False
    if e.get('rejection_reason') not in (None, 'surface_not_local_to_joint'):
        return False
    values = [e.get(k) for k in ('owned_weight', 'nearest_owned_surface_distance', 'hit_joint_distance')]
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values):
        return False
    owned, near, distance = values
    return owned >= .7 and near > 1e-8 and distance > near * 1.5


def compare_candidate(reference, generated, gt, thresholds=None):
    strict = compare(reference, generated, gt, thresholds)
    if gt.get('meta', {}).get('motion_observation_policy') != POLICY:
        return strict
    if strict['verdict'] == 'ERROR' or 'M2_side' not in strict['metrics']:
        return strict
    motion_gt = deepcopy(gt)
    added = []
    for index, frame in enumerate(motion_gt['frames']):
        for j, joint in enumerate(frame['joints']):
            e = joint.get('surface_evidence', {})
            rendered = (e.get('first_hit_render_surface') is True or
                        (e.get('method') == 'blender-evaluated-first-hit-local-skin-v1' and
                         gt.get('meta', {}).get('visibility_method') == 'blender-rendered-first-hit-local-skin-v2' and
                         'Icosphere' in gt.get('meta', {}).get('excluded_nonrendered', [])))
            if rendered and eligible(joint):
                joint['visibility'] = 'surface_local_skin'
                added.append({'frame': index, 'joint': j})
    motion = compare(reference, generated, motion_gt, thresholds)
    if motion['verdict'] == 'ERROR' or 'M2_side' not in motion['metrics']:
        return motion
    # Restore complete strict side findings AFTER its own alignment and confound
    # attribution. Motion timing/missing findings never rewrite side attribution.
    motion['failures'] = [f for f in motion['failures'] if f['type'] != 'WRONG_SIDE'] + [
        deepcopy(f) for f in strict['failures'] if f['type'] == 'WRONG_SIDE']
    motion['flags'] = [f for f in motion['flags'] if f['type'] != 'SIDE_ATTRIBUTION_UNCERTAIN'] + [
        deepcopy(f) for f in strict['flags'] if f['type'] == 'SIDE_ATTRIBUTION_UNCERTAIN']
    motion['uncertain_reasons'] = list(dict.fromkeys(
        [r for r in motion['uncertain_reasons'] if r not in SIDE_REASONS] +
        [r for r in strict['uncertain_reasons'] if r in SIDE_REASONS]))
    motion['metrics']['M2_side'] = deepcopy(strict['metrics']['M2_side'])
    motion['coverage']['side_judgeable_frames'] = strict['coverage']['side_judgeable_frames']
    motion['verdict'] = 'FAIL' if motion['failures'] else 'UNCERTAIN' if motion['uncertain_reasons'] else 'PASS'
    if 'framing_diagnostic' in motion:
        motion['framing_diagnostic']['observation_policy'] = POLICY
    motion['observation_policy'] = {
        'status': 'CALIBRATION_CANDIDATE_NOT_PRODUCTION', 'method': POLICY,
        'motion_scope': 'M1/M3/M4/M5/M6; owned surface proxy, not proven joint visibility',
        'side_scope': 'M2 strict alignment, denominator and attribution preserved',
        'added_joint_frames': added, 'strict_report': strict,
        'thresholds_unchanged': strict['thresholds_sha256'] == motion['thresholds_sha256'],
        'decision_boundary_changed': True}
    motion['observation_gaps']['policy_scope'] = 'motion metrics only; M2 side uses separate strict observations'
    return display_evidence(motion, motion['display_policy']['minimum_frames'])
