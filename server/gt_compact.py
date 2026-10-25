"""Wire-size reduction for the reference GT sent with a guarded job (provider limit 10 MB).
Drops fields no reader uses and rounds joint, hand and camera floats to 1e-5 (frame times stay exact);
the compact file becomes the run's GT."""
from motionguard_core.observation_candidate import eligible
KEEP_EVIDENCE = ('method', 'opaque', 'rejection_reason', 'owned_weight', 'nearest_owned_surface_distance',
                 'hit_joint_distance', 'first_hit_render_surface')
DROP_JOINT = ('legacy_visibility', 'surface_gap')
DROP_FRAME = ('torso_pixels', 'render_encoding')


def _round(v):
    if isinstance(v, float):
        return round(v, 5)
    if isinstance(v, list):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def compact(gt):
    for frame in gt['frames']:
        for k in DROP_FRAME:
            frame.pop(k, None)
        for joint in frame.get('joints', []):
            for k in DROP_JOINT:
                joint.pop(k, None)
            evidence = joint.pop('surface_evidence', None)
            # observation_candidate.eligible reads evidence only for 'uncertain' joints
            if isinstance(evidence, dict) and joint.get('visibility') == 'uncertain':
                joint['surface_evidence'] = {k: evidence[k] for k in KEEP_EVIDENCE if k in evidence}
        for k in ('joints', 'hands', 'camera', 'torso_world'):
            if k in frame:
                frame[k] = _round(frame[k])
        # compare reads hand pixel/available/in_frame/visibility only; evidence is read for body joints alone
        for hand in frame.get('hands', []):
            hand.pop('surface_evidence', None)
            hand.pop('name', None)  # hands are matched by index
        for joint in frame.get('joints', []):
            joint.pop('camera', None)  # reprojection uses world + frame camera
        for point in frame.get('joints', []) + frame.get('hands', []):
            if isinstance(point.get('pixel'), list):
                point['pixel'] = [round(v, 3) if isinstance(v, float) else v for v in point['pixel']]
        # evidence without which eligible() is already False changes nothing (40 s exceeded 10 MB, 2026-10-24)
        for joint in frame.get('joints', []):
            if 'surface_evidence' in joint and not eligible(joint):
                del joint['surface_evidence']
    return gt
