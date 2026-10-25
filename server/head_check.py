"""Head-position warning. Quality only: the motion verdict leaves out nose, neck, eyes and ears (compare.py
205, 212), so a bowed head passes it (2026-10-24 40 s Space run: hunched hold, PASS).

This applies the verdict's own per-joint sustained-error rule to the nose, on the poses the check already
estimated: same global time shift and framing alignment as the report, nearest reference position within
the lag tolerance, and the first and last tolerance window not judged.

The verdict's own cut (PCK distance 0.1 torso, 6 frames) cannot be reused: on the faceless mannequin the
nose estimate wanders 0.12-0.19 torso in normal runs, and that cut warned on 40 of 52 stored runs, including
PASS runs. The hunched 40 s hold stayed 0.51 torso away for 930 frames. FACTOR and MIN_SECONDS were set after
seeing those stored runs (largest PASS-run excursion 0.19), so they are uncalibrated and only warn."""
import json
from pathlib import Path

import numpy as np

from motionguard_core.compare import shifted, spans

METHOD = 'head-sustained-error-v1'
NOSE = 0
FACTOR = 3.0       # times the verdict's PCK distance
MIN_SECONDS = 1.0


def check(reference_pose, generated_pose, report, thresholds):
    r = np.asarray(reference_pose['points'], float); cr = np.asarray(reference_pose['scores'], float)
    g = np.asarray(generated_pose['points'], float); cg = np.asarray(generated_pose['scores'], float)
    n = len(r)
    if n == 0 or len(g) != n:
        return {'status': 'unavailable', 'method': METHOD, 'reason': 'pose arrays missing or of different length'}
    metrics = report.get('metrics', {})
    shift = int((metrics.get('time_shift') or {}).get('frames') or 0)
    framing = metrics.get('M8_framing') or {}
    g, cg = shifted(g, cg, shift)
    aligned = (g - np.asarray(framing.get('translation_px', [0, 0]), float)) / float(framing.get('scale', 1.0))
    torso = np.linalg.norm(r[:, [2, 5]].mean(1) - r[:, [8, 11]].mean(1), axis=1)
    ok = (cr[:, [2, 5, 8, 11]] >= thresholds['min_estimator_score']).all(1) & (torso > 1e-6)
    if not ok.any():
        return {'status': 'unavailable', 'method': METHOD, 'reason': 'reference torso not observed'}
    torso[~ok] = np.median(torso[ok])
    score = thresholds['min_estimator_score']
    valid = (cr[:, NOSE] >= score) & (cg[:, NOSE] >= score)
    tolerance = round(24 * thresholds['max_abs_lag_seconds'])
    error = np.full(n, np.inf)
    for k in range(-tolerance, tolerance + 1):
        lo, hi = max(0, -k), min(n, n - k)
        d = np.linalg.norm(aligned[lo:hi, NOSE] - r[lo + k:hi + k, NOSE], axis=1) / torso[lo + k:hi + k]
        d[cr[lo + k:hi + k, NOSE] < score] = np.inf
        error[lo:hi] = np.minimum(error[lo:hi], d)
    bad = (error > FACTOR * thresholds['pck_normalized_distance']) & valid
    bad[:tolerance] = False; bad[n - tolerance:] = False
    minimum = max(int(thresholds['min_evidence_frames']), round(24 * MIN_SECONDS))
    intervals = [{'frames': [int(a), int(b)], 't_start_s': a / 24, 't_end_s': (b + 1) / 24,
                  'mean_error_torso': round(float(error[a:b + 1].mean()), 3)} for a, b in spans(bad, minimum)]
    judged = int((valid[tolerance:n - tolerance]).sum())
    if judged < minimum:
        return {'status': 'unavailable', 'method': METHOD, 'reason': 'nose not observed in enough frames',
                'judged_frames': judged, 'affects_verdict': False}
    return {'status': 'warning' if intervals else 'clear', 'method': METHOD, 'intervals': intervals,
            'judged_frames': judged, 'affects_verdict': False,
            'scope': 'nose position against the reference; quality warning only, motion verdict unchanged'}


def check_folder(guard, thresholds_path):
    guard = Path(guard)
    read = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
    return check(read(guard / 'reference-pose.json'), read(guard / 'generated-pose.json'),
                 read(guard / 'report.json'), read(thresholds_path))
