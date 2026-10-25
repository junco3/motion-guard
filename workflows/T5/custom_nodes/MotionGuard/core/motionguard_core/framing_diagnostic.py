"""Screen-space framing observations; never an automatic failure classifier."""
import numpy as np


def measure(reference, generated, valid, fps=24):
    r, g = np.asarray(reference, float), np.asarray(generated, float)
    valid = np.asarray(valid, bool)
    if (r.ndim != 3 or r.shape[1:] != (18, 2) or g.shape != r.shape or
            valid.shape != r.shape[:2] or not isinstance(fps, (int, float)) or
            isinstance(fps, bool) or not np.isfinite(fps) or fps <= 0):
        raise ValueError('Invalid framing input shape or fps')
    torso_joints = [2, 5, 8, 11]
    rh, gh = r[:, [8, 11]].mean(1), g[:, [8, 11]].mean(1)
    rt = np.linalg.norm(r[:, [2, 5]].mean(1) - rh, axis=1)
    gt = np.linalg.norm(g[:, [2, 5]].mean(1) - gh, axis=1)
    usable = valid[:, torso_joints].all(1) & (rt > 1e-6) & (gt > 1e-6)
    usable &= np.isfinite(r[:, torso_joints]).all((1, 2)) & np.isfinite(g[:, torso_joints]).all((1, 2))
    baseline = np.flatnonzero(usable)[:6]
    out = {'status': 'INSUFFICIENT_EVIDENCE', 'automatic_failure': False,
           'units': 'screen pixels and projected reference torso lengths',
           'limitations': ['projected length varies with pose, rotation and phase; not physical body scale',
                           'scale change can also cause position residual; not independent causal diagnoses'],
           'baseline_frames': baseline.tolist(), 'frames': []}
    if len(baseline) < 6: return out
    scale = float(np.median(gt[baseline] / rt[baseline]))
    translation = np.median(gh[baseline] - scale * rh[baseline], axis=0)
    out.update(status='DIAGNOSTIC_ONLY', baseline_scale=scale, baseline_translation_px=translation.tolist())
    for i in range(len(r)):
        row = {'frame': i, 'time_s': i / fps, 'observed': bool(usable[i])}
        if usable[i]:
            ratio = float(gt[i] / rt[i]); residual = gh[i] - (scale * rh[i] + translation)
            row.update(projected_torso_ratio=ratio, relative_to_baseline=ratio / scale - 1,
                       hip_residual_xy_px=residual.tolist(), hip_residual_distance_px=float(np.linalg.norm(residual)),
                       normalization_denominator_px=float(rt[i]),
                       hip_residual_reference_torso_lengths=float(np.linalg.norm(residual) / rt[i]))
        out['frames'].append(row)
    return out
