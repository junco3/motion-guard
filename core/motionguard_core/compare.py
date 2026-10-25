"""Fixed-frame motion checks. Provisional thresholds, never a quality guarantee."""
import hashlib
import json
from pathlib import Path
import numpy as np

BODY = np.arange(2, 14)
PAIRS = [(2, 5), (3, 6), (4, 7), (8, 11), (9, 12), (10, 13)]
TERMINALS = [4, 7, 10, 13]
DEFAULT = Path(__file__).resolve().parents[2] / 'config/thresholds.yaml'


def spans(mask, minimum=1):
    result = []; start = None
    for i, value in enumerate(list(mask) + [False]):
        if value and start is None: start = i
        if not value and start is not None:
            if i - start >= minimum: result.append([start, i - 1])
            start = None
    return result


def display_evidence(report, minimum):
    """Filter presentation only; raw failures remain the decision evidence."""
    raw = report['failures']
    report['display_failures'] = [f for f in raw
                                  if f['frames'][1] - f['frames'][0] + 1 >= minimum]
    report['display_policy'] = {'minimum_frames': int(minimum),
        'suppressed_short_intervals': len(raw) - len(report['display_failures']),
        'raw_failure_count': len(raw), 'affects_verdict': False}
    return report


def similarity(r, g):
    """One clip-wide positive scale/translation, robust residual trimming, no rotation."""
    keep = np.ones(len(r), dtype=bool)
    if len(r) < 6: return 1., np.zeros(2)
    scale = 1.; translation = np.zeros(2)
    for _ in range(3):
        a, b = r[keep], g[keep]; ac, bc = np.median(a, axis=0), np.median(b, axis=0)
        denominator = np.sum((a - ac) ** 2)
        if denominator < 1e-6: break
        scale = float(np.sum((a - ac) * (b - bc)) / denominator)
        if not np.isfinite(scale) or scale <= 1e-6: return 1., np.zeros(2)
        translation = bc - scale * ac
        residual = np.linalg.norm(g - (scale * r + translation), axis=1)
        keep = residual <= max(float(np.quantile(residual, .8)), 1e-6)
    return scale, translation


def observation_gaps(valid, available, visible, ref_error, reference_scores,
                     generated_scores, thresholds, fps):
    """Display-only terminal coverage, not additional failures or coordinates."""
    rows = []
    for joint in TERMINALS:
        for start, end in spans(~valid[:, joint], 6):
            counts = {}
            for i in range(start, end + 1):
                reason = ('unavailable' if not available[i, joint] else
                          'visibility_evidence' if not visible[i, joint] else
                          'reference_gt_error' if ref_error[i, joint] > thresholds['reference_gt_max_normalized_error'] else
                          'reference_score' if reference_scores[i, joint] < thresholds['min_estimator_score'] else
                          'generated_score')
                counts[reason] = counts.get(reason, 0) + 1
            rows.append({'type': 'OBSERVATION_GAP', 'joints': [joint],
                         'frames': [start, end], 't_start_s': start / fps,
                         't_end_s': (end + 1) / fps, 'excluded_reason_counts': counts})
    return {'status': 'available', 'scope': 'wrists_and_ankles',
            'policy_scope': 'strict comparison observations',
            'minimum_display_frames': 6, 'affects_verdict': False, 'intervals': rows}


def lag_measure(a, b, valid, fps, max_seconds=.5, generated_valid=None):
    """Measure lag without moving frames. Periodic/tied maxima remain ambiguous."""
    values = []
    for lag in range(-round(fps * max_seconds), round(fps * max_seconds) + 1):
        n = len(a) - abs(lag)
        if n < 6: continue
        ia = np.arange(max(0, -lag), max(0, -lag) + n)
        ib = ia + lag; mask = valid[ia] & (valid if generated_valid is None else generated_valid)[ib]
        x, y = a[ia][mask], b[ib][mask]
        if len(x) < 6 or np.std(x) < 1e-8 or np.std(y) < 1e-8: continue
        values.append((lag, float(np.corrcoef(x, y)[0, 1])))
    if not values: return None, 'inactive_or_constant_speed', []
    values.sort(key=lambda x: x[1], reverse=True)
    best = values[0]
    tied = [x for x in values if abs(x[0] - best[0]) > 1 and x[1] > best[1] - .02]
    reason = 'periodic_or_ambiguous_lag' if tied else None
    return best[0] / fps, reason, values


# Fingers come from the whole-body hand estimate, judged against 3D finger ground truth visibility.
# Hand index 0 = wrist; fingertips 4/8/12/16/20; whole-body ids = 91 + index (left), 112 + index (right).
FINGER_TIPS = {4: 'thumb', 8: 'index', 12: 'middle', 16: 'ring', 20: 'little'}
# Distances are in palm sizes (wrist to the four finger bases). Measured sustained runs above 0.6:
# rendered same-motion variants <=2 frames, a real person's repeated squat 1 frame, wrong motions
# 24-111 frames (above 0.4 the real repetition already ran 12 frames). Bending one finger moves
# its tip about one palm size. Palms under 5 px are not judged.
FINGER_DISTANCE = .6
MIN_PALM_PX = 5.

def finger_check(reference, generated, shift, n, fps, t, evidence, tolerance, gt):
    """Per-finger shape (wrist-relative, palm-size normalized) with the same time tolerance as joints.
    Only fingertips the 3D ground truth shows as visible are judged, and only where the reference
    estimate agrees with that ground truth: tips hidden in a fist are guesses and are not judged."""
    if 'hands' not in reference or 'hands' not in generated or reference.get('hand_settings') != generated.get('hand_settings'):
        return [], {'status': 'not_measured', 'reason': 'hand estimate missing in reference or generated poses'}
    if not all('hands' in f for f in gt['frames']):
        return [], {'status': 'not_measured', 'reason': 'no 3D finger ground truth for this reference'}
    gt_xy = np.array([[h['pixel'] if h.get('available') and h.get('pixel') else [np.nan, np.nan] for h in f['hands']] for f in gt['frames']], float)
    gt_visible = np.array([[bool(h.get('available') and h.get('in_frame')) and h.get('visibility') in ('surface_near', 'surface_local_skin') for h in f['hands']] for f in gt['frames']])
    rh, rs = np.asarray(reference['hands'], float), np.asarray(reference['hand_scores'], float)
    gh, gs = shifted(np.asarray(generated['hands'], float), np.asarray(generated['hand_scores'], float), shift)
    if rh.shape != (n, 42, 2) or gh.shape != rh.shape: raise ValueError('hand_shape_mismatch')
    found, judged = [], {}
    for side, off in (('left', 0), ('right', 21)):
        idx = list(range(off, off + 21))
        def shape(h, sc):
            # Palm size (wrist to the four finger bases) does not change when a finger bends.
            size = np.linalg.norm(h[:, [off + 5, off + 9, off + 13, off + 17]] - h[:, [off]], axis=2).mean(1)
            ok = (sc[:, idx] >= t['min_estimator_score']).all(1) & (size >= MIN_PALM_PX)
            return (h[:, idx] - h[:, [off]]) / np.maximum(size, 1)[:, None, None], ok
        sr, okr = shape(rh, rs); sg, okg = shape(gh, gs)
        palm = np.maximum(np.linalg.norm(rh[:, [off + 5, off + 9, off + 13, off + 17]] - rh[:, [off]], axis=2).mean(1), 1)
        for tip, name in FINGER_TIPS.items():
            # The reference estimate must see this tip where the 3D truth says it is visible.
            agree = gt_visible[:, off + tip] & (np.linalg.norm(rh[:, off + tip] - gt_xy[:, off + tip], axis=1) / palm <= FINGER_DISTANCE)
            okr_tip = okr & agree
            err = np.full(n, np.inf)
            for k in range(-tolerance, tolerance + 1):
                lo, hi = max(0, -k), min(n, n - k)
                d = np.linalg.norm(sg[lo:hi, tip] - sr[lo + k:hi + k, tip], axis=1)
                d[~okr_tip[lo + k:hi + k]] = np.inf
                err[lo:hi] = np.minimum(err[lo:hi], d)
            usable = okg & okr_tip; usable[:tolerance] = False; usable[n - tolerance:] = False
            bad = usable & (err > FINGER_DISTANCE)
            judged[f'{side}_{name}'] = int(usable.sum())
            for start, end in spans(bad, evidence):
                found.append({'joint': 91 + off + tip, 'frames': [start, end], 'value': float(err[start:end + 1].mean())})
    status = 'measured' if max(judged.values(), default=0) >= evidence else 'insufficient_hand_evidence'
    return found, {'status': status, 'distance_palm_sizes': FINGER_DISTANCE, 'min_palm_px': MIN_PALM_PX,
                   'judged_frames': judged, 'reference': 'hand estimate on the reference render, judged only where 3D finger ground truth is visible and agrees'}

def shift_search(r, g, cg, reference_valid, L, t, fps):
    """One clip-wide integer shift within the allowed lag; ties keep the smaller shift."""
    best = (-2., 0)
    for k in sorted(range(-round(fps * t['max_abs_lag_seconds']), round(fps * t['max_abs_lag_seconds']) + 1), key=abs):
        gs, cs = shifted(g, cg, k)
        mask = reference_valid & (cs >= t['min_estimator_score'])
        if mask.sum() < 6: continue
        scale, translation = similarity(r[mask], gs[mask])
        error = np.linalg.norm((gs - translation) / scale - r, axis=2) / L
        score = -float(np.minimum(error[mask], 1.).mean())  # capped mean error; PCK saturates on static joints
        if score > best[0] + 1e-9: best = (score, k)
    return best[1]

def shifted(g, cg, k):
    """generated[i + k] is compared with reference[i]; frames outside the clip become unobserved."""
    n = len(g); gs, cs = np.repeat(g[:1] * 0, n, axis=0), np.zeros_like(cg)
    lo, hi = max(0, -k), min(n, n - k)
    gs[lo:hi], cs[lo:hi] = g[lo + k:hi + k], cg[lo + k:hi + k]
    return gs, cs

def compare(reference, generated, gt, thresholds=None):
    t = thresholds or json.loads(DEFAULT.read_text(encoding='utf-8'))
    out = {'schema_version': 'mg-report-3', 'verdict': 'ERROR', 'failures': [],
           'flags': [], 'uncertain_reasons': [], 'metrics': {}, 'coverage': {},
           'thresholds_sha256': hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest(),
           'threshold_status': t['threshold_status'], 'alignment': 'fixed frame i-to-i; no DTW',
           'limitations': ['motion-only; not appearance/quality certification',
                           'foot ground-contact not certified by 2D ankles alone',
                           'M7 secondary estimator not implemented'],
           # Not measured at all, so never part of the verdict (nose, neck, eyes, ears are excluded below).
           'not_evaluated': ['head and neck direction', 'torso bend']}
    try:
        r, g = np.asarray(reference['points'], float), np.asarray(generated['points'], float)
        cr, cg = np.asarray(reference['scores'], float), np.asarray(generated['scores'], float)
        fps = float(reference['fps']); n = len(r)
        if n != len(g) or n != len(gt['frames']) or n < 9 or (n - 1) % 8:
            raise ValueError('frame_count_mismatch_or_invalid_8n1')
        if fps != 24 or float(generated['fps']) != fps: raise ValueError('fps_mismatch')
        if r.shape != (n, 18, 2) or g.shape != r.shape or cr.shape != (n, 18) or cg.shape != cr.shape:
            raise ValueError('joint_shape_mismatch')
        if not all(np.isfinite(v).all() for v in [r, g, cr, cg]): raise ValueError('nonfinite_pose')
        if not reference.get('settings') or reference.get('settings') != generated.get('settings'): raise ValueError('estimator_settings_mismatch')
        xy = np.zeros_like(r); visible = np.zeros((n, 18), bool); available = visible.copy()
        for i, f in enumerate(gt['frames']):
            if len(f['joints']) != 18: raise ValueError('gt_joint_count')
            if not np.isfinite(f['time_s']) or f['frame'] != i or abs(f['time_s'] - i / fps) > 1e-6: raise ValueError('gt_timeline_mismatch')
            def finite_tree(v):
                if isinstance(v,dict): return all(finite_tree(x) for x in v.values())
                if isinstance(v,list): return all(finite_tree(x) for x in v)
                return bool(np.isfinite(v)) if isinstance(v,(float,int)) else True
            if not f.get('camera') or not finite_tree(f['camera']): raise ValueError('invalid_gt_camera')
            for j, joint in enumerate(f['joints']):
                if joint.get('available'):
                    xy[i, j] = joint['pixel']; available[i, j] = True
                    visible[i, j] = joint.get('in_frame', False) and joint['visibility'] in ('surface_near','surface_local_skin')
        if not np.isfinite(xy).all(): raise ValueError('nonfinite_gt')
        torso = np.linalg.norm(xy[:, [2, 5]].mean(1) - xy[:, [8, 11]].mean(1), axis=1)
        torso_ok = available[:, [2, 5, 8, 11]].all(1) & (torso > 1e-6)
        if not torso_ok.any():
            out['verdict'] = 'UNCERTAIN'; out['uncertain_reasons'] = ['degenerate_torso']; return out
        torso[~torso_ok] = np.median(torso[torso_ok]); L = torso[:, None]
        ref_error = np.linalg.norm(r - xy, axis=2) / L
        reference_valid = visible & (ref_error <= t['reference_gt_max_normalized_error']) & (cr >= t['min_estimator_score'])
        reference_valid[:, [0, 1, 14, 15, 16, 17]] = False
        shift = shift_search(r, g, cg, reference_valid, L, t, fps)
        g, cg = shifted(g, cg, shift)
        in_clip = np.zeros(n, bool); in_clip[max(0, -shift):min(n, n - shift)] = True
        out['alignment'] = f'one global time shift of {shift} frames ({shift / fps:+.3f}s, searched within +/-{t["max_abs_lag_seconds"]}s), then fixed frame i-to-i; no DTW'
        out['metrics']['time_shift'] = {'frames': shift, 'seconds': shift / fps, 'search_seconds': t['max_abs_lag_seconds']}
        valid = reference_valid & (cg >= t['min_estimator_score'])
        valid[:, [0, 1, 14, 15, 16, 17]] = False
        out['observation_gaps'] = observation_gaps(valid, available, visible, ref_error, cr, cg, t, fps)
        # Diagnostic only: original image coordinates, before global alignment.
        try:
            from .framing_diagnostic import measure
            framing = measure(r, g, valid, fps)
            framing.update(coordinates='original pixel coordinates after the global time shift, before spatial alignment',
                           reference_size=reference.get('size'), generated_size=generated.get('size'),
                           observation_policy='strict')
            out['framing_diagnostic'] = framing
        except (ValueError, TypeError) as exc:
            out['framing_diagnostic'] = {'status': 'ERROR', 'automatic_failure': False, 'error': str(exc)}
        scale, translation = similarity(r[valid], g[valid]); aligned = (g - translation) / scale
        out['metrics']['M8_framing'] = {'scale': scale, 'translation_px': translation.tolist(), 'automatic_failure': False}
        out['coverage'] = {'total_frames': n, 'body_joint_frames': n * 12, 'valid_joint_frames': int(valid.sum()),
                           'valid_fraction': float(valid.sum() / (n * 12)),
                           'reference_gt_valid_joint_frames': int((visible[:, BODY] & (ref_error[:, BODY] <= t['reference_gt_max_normalized_error'])).sum()),
                           'excluded_reference_gt_joint_frames': int((available[:, BODY] & (ref_error[:, BODY] > t['reference_gt_max_normalized_error'])).sum())}
        delta_r, delta_g = np.diff(r, axis=0) / L[1:, :, None], np.diff(aligned, axis=0) / L[1:, :, None]
        delta_gt = np.diff(xy, axis=0) / L[1:, :, None]
        vr, vg = np.linalg.norm(delta_r, axis=2), np.linalg.norm(delta_g, axis=2)
        vgtruth = np.linalg.norm(delta_gt, axis=2)
        active_joint = (vgtruth > t['min_pose_motion_pixels_per_frame_normalized']) & available[1:] & available[:-1]
        active_joint[:, [0, 1, 14, 15, 16, 17]] = False
        active = active_joint.any(1)
        velocity_valid = valid[1:] & valid[:-1]
        active_valid = velocity_valid & active_joint
        coverage = float(active_valid.sum() / max(int(active_joint.sum()), 1))
        out['coverage'].update(active_frames=int(active.sum()), active_joint_frames=int(active_joint.sum()), active_valid_joint_fraction=coverage)
        reasons = out['uncertain_reasons']; evidence = t['min_evidence_frames']
        if active.sum() < evidence: reasons.append('insufficient_active_frames')
        if coverage < t['min_active_valid_fraction']: reasons.append('insufficient_active_coverage')
        def failure(kind, ranges, metric, value, threshold):
            for start, end in ranges:
                out['failures'].append({'type': kind, 'frames': [int(start), int(end)], 't_start_s': start / fps,
                    't_end_s': (end + 1) / fps, 'evidence': {'metric_name': metric, 'metric_value': value,
                    'threshold': threshold, 'frames_used': end - start + 1}})
        error = np.linalg.norm(aligned - r, axis=2) / L
        pck = np.divide(((error <= t['pck_normalized_distance']) & valid).sum(1), valid.sum(1), out=np.zeros(n), where=valid.sum(1) > 0)
        usable = np.r_[False, active] & (valid[:, BODY].mean(1) >= t['min_active_valid_fraction'])
        mean_pck = float(pck[usable].mean()) if usable.any() else None
        out['metrics']['M1_pck'] = {'mean': mean_pck, 'threshold': t['min_active_mean_pck'], 'frames_used': int(usable.sum()), 'per_frame': [float(v) if valid[i].any() else None for i, v in enumerate(pck)]}
        if usable.sum() < evidence: reasons.append('M1_insufficient_evidence')
        if usable.sum() >= evidence and mean_pck < t['min_active_mean_pck']:
            failure('WRONG_POSE', spans(usable & (pck < t['min_active_mean_pck'])), 'M1_pck', mean_pck, t['min_active_mean_pck'])
            for item in out['failures']:
                start, end = item['frames']; sl = slice(start, end + 1)
                counts = valid[sl].sum(0)
                misses = ((error[sl] > t['pck_normalized_distance']) & valid[sl]).sum(0)
                rates = np.divide(misses, counts, out=np.zeros(18), where=counts > 0)
                candidates = sorted((int(j) for j in BODY if counts[j] >= evidence and rates[j] >= .5),
                                    key=lambda j: (-rates[j], j))
                item['joints'] = candidates[:2]
                item['evidence'].update(metric_value=float(pck[sl].mean()), scope='interval_mean',
                    whole_clip_mean=mean_pck, attribution_minimum_observations=int(evidence),
                    joint_observations={str(j): int(counts[j]) for j in BODY},
                    joint_miss_rates={str(j): float(rates[j]) if counts[j] else None for j in BODY})
                if not item['joints']:
                    item['evidence']['attribution_reason'] = 'insufficient_observations_or_no_joint_miss_rate_at_least_half'
        # A clip-wide mean can hide one body part that stays wrong. When the whole-clip
        # check did not already fail, each joint keeps its own sustained-error evidence.
        # A person who follows correctly still runs a little early or late inside the clip, so each
        # joint is compared with the nearest reference position within the allowed lag (+/-0.25 s).
        tolerance = round(fps * t['max_abs_lag_seconds'])
        local_error = np.full((n, 18), np.inf)
        for k in range(-tolerance, tolerance + 1):
            lo, hi = max(0, -k), min(n, n - k)
            d = np.linalg.norm(aligned[lo:hi] - r[lo + k:hi + k], axis=2) / L[lo:hi]
            d[~reference_valid[lo + k:hi + k]] = np.inf
            local_error[lo:hi] = np.minimum(local_error[lo:hi], d)
        joint_frames = int(evidence)
        joint_bad = (local_error > t['pck_normalized_distance']) & valid
        # The first/last 0.25 s have only one side of that tolerance, so they are not judged here.
        joint_bad[:tolerance] = False; joint_bad[n - tolerance:] = False
        joint_runs = {int(j): max((b - a + 1 for a, b in spans(joint_bad[:, j])), default=0) for j in BODY}
        joint_check = not any(f['type'] == 'WRONG_POSE' for f in out['failures'])
        if joint_check and n - 2 * tolerance < joint_frames: reasons.append('joint_check_clip_too_short')
        if joint_check:
            for j in BODY:
                for start, end in spans(joint_bad[:, j], joint_frames):
                    failure('WRONG_POSE', [[start, end]], 'M1_joint_error', float(local_error[start:end + 1, j].mean()), t['pck_normalized_distance'])
                    out['failures'][-1].update(joints=[int(j)], scope='single observable joint only')
        out['metrics']['M1_joint_error'] = {'threshold': t['pck_normalized_distance'], 'minimum_frames': joint_frames,
            'longest_run_frames': joint_runs, 'applied': joint_check, 'time_tolerance_frames': tolerance,
            'scope': 'added only when the whole-clip pose check did not already fail'}
        fingers, out['metrics']['M9_fingers'] = finger_check(reference, generated, shift, n, fps, t, int(evidence), tolerance, gt)
        for f in fingers:
            failure('WRONG_POSE', [f['frames']], 'M9_finger_shape', f['value'], FINGER_DISTANCE)
            out['failures'][-1].update(joints=[f['joint']], scope='single finger; visible in 3D ground truth')
        side_used = np.zeros(n, bool)
        side_values = []
        for a, b in PAIRS:
            separation = np.linalg.norm(xy[:, a] - xy[:, b], axis=1) / torso
            mask = valid[:, a] & valid[:, b] & (separation > 2 * t['reference_gt_max_normalized_error'])
            normal = (error[:, a] + error[:, b]) / 2
            swapped = (np.linalg.norm(aligned[:, a] - r[:, b], axis=1) + np.linalg.norm(aligned[:, b] - r[:, a], axis=1)) / (2 * torso)
            ratio = swapped / np.maximum(normal, t['swap_denominator_epsilon'])
            bad = mask & (normal >= t['swap_denominator_epsilon']) & (ratio < t['wrong_side_swap_ratio']) & ((normal - swapped) > t['pck_normalized_distance'])
            side_used |= mask
            ranges = spans(bad, evidence)
            if ranges:
                before=len(out['failures'])
                failure('WRONG_SIDE', ranges, 'M2_swap_ratio', float(ratio[bad].mean()), t['wrong_side_swap_ratio'])
                for entry in out['failures'][before:]:entry['joints']=[a,b]
            side_values.append({'pair': [a, b], 'frames_judgeable': int(mask.sum()), 'bad_ranges': ranges})
        out['metrics']['M2_side'] = side_values; out['coverage']['side_judgeable_frames'] = int(side_used.sum())
        if side_used.sum() < evidence: reasons.append('side_unjudgeable')
        norm_product = vr * vg
        moving = velocity_valid & (vr > t['min_pose_motion_pixels_per_frame_normalized']) & (vg > t['min_pose_motion_pixels_per_frame_normalized'])
        cosine = np.divide((delta_r * delta_g).sum(2), norm_product, out=np.zeros_like(vr), where=norm_product > 1e-12)
        terminal_valid = moving[:, TERMINALS]
        weights = np.where(terminal_valid, vr[:, TERMINALS], 0)
        terminal_cos = np.divide((cosine[:, TERMINALS] * weights).sum(1), weights.sum(1), out=np.zeros(n-1), where=weights.sum(1) > 0)
        terminal_bad = (weights.sum(1) > 0) & (terminal_cos < t['wrong_direction_terminal_cosine'])
        out['metrics']['M3_terminal'] = {'frames_used': int((weights.sum(1)>0).sum()), 'cosine_mean': float(terminal_cos[weights.sum(1)>0].mean()) if weights.any() else None}
        terminal_used=weights.sum(1)>0
        if terminal_used.sum()>=evidence and terminal_cos[terminal_used].mean()<t['wrong_direction_terminal_cosine']:
            failure('WRONG_DIRECTION', [[a+1,b+1] for a,b in spans(terminal_bad)], 'M3_terminal', float(terminal_cos[terminal_used].mean()), t['wrong_direction_terminal_cosine'])
        # Zero generated speed is handled by M5, never converted into a direction error.
        # Root uses original screen coordinates, not framing-corrected trajectories.
        fixed_camera = all(f.get('camera') == gt['frames'][0].get('camera') for f in gt['frames'])
        rr = np.diff(r[:, [8,11]].mean(1),axis=0); gr = np.diff(g[:, [8,11]].mean(1),axis=0)
        nr, ng = np.linalg.norm(rr,axis=1),np.linalg.norm(gr,axis=1)
        root_mask = velocity_valid[:,[8,11]].all(1) & (nr/torso[1:]>.02) & (ng/torso[1:]>.02)
        root_cos=np.divide((rr*gr).sum(1),nr*ng,out=np.zeros(n-1),where=nr*ng>1e-9)
        root_bad=root_mask & (root_cos<t['wrong_direction_root_cosine'])
        out['metrics']['M3_root']={'camera_fixed':fixed_camera,'frames_used':int(root_mask.sum()),'negative_fraction':float(root_bad.sum()/max(root_mask.sum(),1))}
        root_translation=gt.get('meta',{}).get('root_translation_ground_truth') is True
        out['metrics']['M3_root']['gt_locomotion_confirmed']=root_translation
        if root_translation and fixed_camera and root_mask.sum()>=evidence and root_bad.sum()/root_mask.sum()>=t['min_moving_frames_fraction']:
            failure('WRONG_DIRECTION',[[a+1,b+1] for a,b in spans(root_bad)],'M3_root',float(root_cos[root_bad].mean()),0.)
        # A separately versioned .25s displacement observation for slow travel.
        # .02 torso lengths per window is not the old .02/frame speed cutoff.
        root_windows=[]; root_frames=set()
        if root_translation and fixed_camera:
            rp=r[:,[8,11]].mean(1);gp=g[:,[8,11]].mean(1)
            for start in range(n-evidence):
                end=start+evidence
                if not valid[start:end+1][:,[8,11]].all():continue
                dr=(rp[end]-rp[start])/torso[end];dg=(gp[end]-gp[start])/torso[end]
                lr,lg=np.linalg.norm(dr),np.linalg.norm(dg)
                if min(lr,lg)<=t['min_pose_motion_pixels_per_frame_normalized']:continue
                c=float(np.dot(dr,dg)/(lr*lg));root_windows.append({'start':start,'end':end,'cosine':c});root_frames.update(range(start,end+1))
            bad_windows=[w for w in root_windows if w['cosine']<t['wrong_direction_root_cosine']]
            if len(root_frames)>=evidence+1 and root_windows and len(bad_windows)/len(root_windows)>=t['min_moving_frames_fraction']:
                mask=np.zeros(n,bool)
                for w in bad_windows:mask[w['start']:w['end']+1]=True
                failure('WRONG_DIRECTION',spans(mask),'M3_root_window',float(np.mean([w['cosine'] for w in bad_windows])),t['wrong_direction_root_cosine'])
        out['metrics']['M3_root_window']={'method':'raw-screen-displacement-6frame-v1','window_frames':evidence,'window_seconds':evidence/fps,'minimum_displacement_torso_lengths':t['min_pose_motion_pixels_per_frame_normalized'],'windows':root_windows,'distinct_observed_frames':len(root_frames),'overlapping_windows_are_not_independent':True}
        if not fixed_camera: reasons.append('global_direction_camera_uncompensated')
        # Energy is local-window evidence; missing samples do not become zero-motion evidence.
        selected=np.flatnonzero(reference_valid.mean(0)>=t.get('stable_reference_joint_fraction',.6))
        er=vr[:,selected].sum(1);eg=vg[:,selected].sum(1)
        speed_valid=velocity_valid[:,selected].all(1) if len(selected) else np.zeros(n-1,bool)
        subset_active=active_joint[:,selected].any(1) if len(selected) else np.zeros(n-1,bool)
        out['metrics']['temporal_subset']={'method':t.get('metric_method_version','fixed-visible-subset-v2'),
            'selected_joints':selected.tolist(),'excluded_joints':[int(j) for j in BODY if j not in selected],
            'selection':'reference/GT visibility and reference score only; generated score used only after selection',
            'reference_coverage_per_joint':reference_valid.mean(0).tolist(),'paired_frames':int(speed_valid.sum()),
            'active_paired_frames':int((speed_valid&subset_active).sum()),'scope':'selected joints only; global uncertainty retained'}
        lag, lag_reason, correlation=lag_measure(er,eg,speed_valid,fps,t['max_search_lag_seconds'])
        if lag is not None: lag+=shift/fps  # total lag includes the applied global shift
        out['metrics']['M4_timing']={'lag_s':lag,'unjudgeable_reason':lag_reason,'correlations':correlation,'frames_used':int(speed_valid.sum())}
        if lag_reason: reasons.append(lag_reason)
        elif lag is not None and abs(lag)>t['max_abs_lag_seconds'] and (subset_active&speed_valid).sum()>=evidence:
            failure('TIMING_MISMATCH',spans(np.r_[False,subset_active & speed_valid]),'M4_lag_s',lag,t['max_abs_lag_seconds'])
        # Motion amount = displacement across one evidence window (0.25 s), not per-frame speed:
        # estimator jitter does not accumulate, and slow real movement still counts. Each window
        # uses the selected joints visible at both ends instead of requiring all of them at once.
        motion_floor=t['min_pose_motion_pixels_per_frame_normalized']
        def displacement(a,s,e,cols):return np.linalg.norm(a[e,cols]-a[s,cols],axis=1)/L[e,0]
        # A window counts only when the ground-truth movement is clearly larger than this clip's
        # estimator noise (3x the median reference-vs-GT error); otherwise jitter decides the ratio.
        noise=float(np.median(ref_error[reference_valid])) if reference_valid.any() else 0.
        gate=max(motion_floor,3*noise)
        windows=[]
        for start in range(n-evidence):
            end=start+evidence;cols=[j for j in selected if valid[start,j] and valid[end,j]]
            if not cols or len(cols)*2<len(selected):continue
            if displacement(xy,start,end,cols).mean()<=gate:continue
            # Generated movement may come a little earlier or later: best window within +/-0.25 s.
            ratio=0.
            for k in range(-tolerance,tolerance+1):
                a,b=start+k,end+k
                if a<0 or b>=n:continue
                use=[j for j in cols if cg[a,j]>=t['min_estimator_score'] and cg[b,j]>=t['min_estimator_score']]
                if len(use)*2<len(cols):continue
                dr=displacement(r,start,end,use);dg=np.linalg.norm(aligned[b,use]-aligned[a,use],axis=1)/L[end,0]
                ratio=max(ratio,float(dg.sum()/max(dr.sum(),1e-9)))
            windows.append({'start':start,'end':end,'ratio':ratio,'joints_used':len(cols)})
        out['metrics']['M5_energy']={'method':'window-displacement-v3','noise_torso':noise,'gate_torso':gate,'windows':windows,'minimum':min((w['ratio'] for w in windows),default=None)}
        if not windows: reasons.append('M5_insufficient_evidence')
        low=np.zeros(n,bool)
        for w in windows:
            if w['ratio']<t['min_motion_energy_ratio']:low[w['start']:w['end']+1]=True
        failure('MISSING_MOTION',spans(low,evidence),'M5_energy',out['metrics']['M5_energy']['minimum'],t['min_motion_energy_ratio'])
        for item in out['failures']:
            if item['type'] in ('TIMING_MISMATCH','MISSING_MOTION'):
                item['joints']=selected.tolist();item['scope']='selected observable joints only'
        # Each predeclared body joint retains its own evidence when another
        # joint is intermittently hidden. Never choose groups using G outcome.
        joint_windows=[]; missing_by_joint={}; timing_by_joint={}
        gen_ok=cg>=t['min_estimator_score'];gen_vel=gen_ok[1:]&gen_ok[:-1]
        for j in BODY:
            observed=velocity_valid[:,j]; bad=np.zeros(n,bool)
            for start in range(n-evidence):
                sl=slice(start,start+evidence)
                if observed[sl].all() and active_joint[sl,j].all() and vr[sl,j].sum()>1e-6:
                    # Same +/-0.25 s tolerance as the aggregate window: best generated window nearby.
                    ratio=max((float(vg[start+k:start+k+evidence,j].sum()) for k in range(-tolerance,tolerance+1)
                               if 0<=start+k and start+k+evidence<=n-1 and gen_vel[start+k:start+k+evidence,j].all()),default=0.)/float(vr[sl,j].sum())
                    joint_windows.append({'joint':int(j),'start':start+1,'end':start+evidence,'ratio':ratio})
                    if ratio<t['min_motion_energy_ratio']:bad[start+1:start+evidence+1]=True
            missing_by_joint[int(j)]=bad
            before=len(out['failures'])
            failure('MISSING_MOTION',spans(bad,evidence),'M5_joint_energy',
                    min((w['ratio'] for w in joint_windows if w['joint']==j),default=None),t['min_motion_energy_ratio'])
            for entry in out['failures'][before:]:entry.update(joints=[int(j)],scope='single observable joint only')
            # Frozen/jitter-only samples cannot support a timing attribution.
            timing_mask=observed & (vr[:,j]>motion_floor)
            generated_timing_mask=observed & (vg[:,j]>motion_floor)
            jl,jreason,jcorr=lag_measure(vr[:,j],vg[:,j],timing_mask,fps,t['max_search_lag_seconds'],generated_timing_mask)
            if jl is not None: jl+=shift/fps
            timing_by_joint[int(j)]={'lag_s':jl,'unjudgeable_reason':jreason,'frames_used':int(timing_mask.sum()),'correlations':jcorr}
        out['metrics']['M5_energy']['joint_windows']=joint_windows
        out['metrics']['M4_timing']['per_joint']=timing_by_joint
        # Preserve raw findings but withhold causal names confounded by a
        # measured phase shift or by missing motion on that same body part.
        kept=[]
        for entry in out['failures']:
            a,b=entry['frames']; joints=entry.get('joints',[])
            if entry['type']=='TIMING_MISMATCH':
                supported=[j for j in joints if timing_by_joint[j]['unjudgeable_reason'] is None
                           and timing_by_joint[j]['lag_s'] is not None
                           and abs(timing_by_joint[j]['lag_s'])>t['max_abs_lag_seconds']
                           and abs(timing_by_joint[j]['lag_s']-lag)<=1/fps]
                if not supported:
                    out['flags'].append({**entry,'type':'TIMING_ATTRIBUTION_UNCERTAIN','reason':'aggregate lag lacks active non-frozen per-joint support'})
                    reasons.append('timing_attribution_unjudgeable');continue
                entry['supporting_joints']=supported
            if entry['type']=='WRONG_SIDE':
                # Pair identity is fixed when evidence is created, even when
                # independent body parts have identical failure time ranges.
                involved=set(entry['joints'])
                missing=any(missing_by_joint[j][a:b+1].any() for j in involved)
                phase=any(timing_by_joint[j]['unjudgeable_reason'] is None and timing_by_joint[j]['lag_s'] is not None and abs(timing_by_joint[j]['lag_s'])>t['max_abs_lag_seconds'] for j in involved)
                if missing or phase:
                    out['flags'].append({**entry,'type':'SIDE_ATTRIBUTION_UNCERTAIN','joints':sorted(involved),'reason':'swap evidence overlaps missing motion or measured clip phase shift'})
                    reasons.append('side_attribution_confounded');continue
            kept.append(entry)
        out['failures']=kept
        reasons[:]=list(dict.fromkeys(reasons))
        drops=visible[:,BODY] & (cr[:,BODY]>=.5) & (cg[:,BODY]<.5) & in_clip[:,None]
        if drops.any():out['flags'].append({'type':'STRUCTURE_SUSPECT','frames':np.flatnonzero(drops.any(1)).tolist(),'reason':'generated estimator score dropped; not an anatomical diagnosis'})
        out['metrics']['M6_structure']={'review_only':True,'low_score_joint_frames':int(drops.sum())}
        bones=[]
        for a,b in [(2,3),(3,4),(5,6),(6,7),(8,9),(9,10),(11,12),(12,13)]:
            mask=valid[:,a]&valid[:,b];length=np.linalg.norm(aligned[:,a]-aligned[:,b],axis=1)/torso
            if mask.sum()>=evidence and np.median(length[mask])>1e-6:
                spread=float((np.quantile(length[mask],.95)-np.quantile(length[mask],.05))/np.median(length[mask]))
                bones.append({'joints':[a,b],'relative_spread':spread,'frames_used':int(mask.sum())})
                if spread>.5:out['flags'].append({'type':'STRUCTURE_SUSPECT','joints':[a,b],'reason':'large 2D bone-length spread; perspective/pose may explain it; review only'})
        out['metrics']['M6_structure']['bone_length_spread']=bones
        out['metrics']['M7_disagreement']={'status':'NOT_IMPLEMENTED_OPTIONAL'}
        out['frame_evidence']={'valid_body_count':valid[:,BODY].sum(1).tolist(),'valid_body_mask':valid[:,BODY].tolist(),'body_joint_ids':BODY.tolist(),'reference_gt_error':ref_error[:,BODY].tolist(),'active_frames':np.flatnonzero(np.r_[False,active]).tolist()}
        out['verdict']='FAIL' if out['failures'] else 'UNCERTAIN' if reasons else 'PASS'
        display_evidence(out, evidence)
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        out['error']=str(exc)
    return out
