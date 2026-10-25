"""Lossless PNG report carrier for standard Comfy image outputs."""
import hashlib
import json
import math
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, PngImagePlugin

KEY = 'motion_guard_report'
MAX_BYTES = 16_000_000  # 30-40 s observations exceed 4 MB (2026-10-24 Space run)


def timeline(payload):
    """Old carriers have a fixed timeline; new carriers must declare theirs."""
    if payload.get('schema') == 'motion-guard-artifact-1':
        return {'frames': 97, 'fps': 24}
    context = payload.get('stage_context')
    if not isinstance(context, dict) or 'timeline' not in context:
        raise ValueError('Missing report timeline')
    value = context['timeline']
    if value is None and payload.get('report', {}).get('verdict') == 'ERROR':
        return None
    if (not isinstance(value, dict) or type(value.get('frames')) is not int
            or not 9 <= value["frames"] <= 961 or (value['frames'] - 1) % 8
            or type(value.get('fps')) is not int or value['fps'] != 24):
        raise ValueError('Invalid report timeline')
    return {'frames': value['frames'], 'fps': value['fps']}


def digest(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def digest_encoding(report, expected):
    if digest(report) == expected:
        return 'json-string-keys'
    # Version 1 writers hashed the comparator's integer joint keys before JSON
    # converted them to strings. Reconstruct only those two known maps.
    legacy = json.loads(json.dumps(report, allow_nan=False))
    candidates = [legacy, legacy.get('observation_policy', {}).get('strict_report', {})]
    changed = False
    for candidate in candidates:
        timing = candidate.get('metrics', {}).get('M4_timing', {})
        mapping = timing.get('per_joint')
        if not isinstance(mapping, dict) or not mapping:
            continue
        if not all(isinstance(k, str) and k in {str(i) for i in range(18)} for k in mapping):
            return None
        timing['per_joint'] = {int(k): value for k, value in mapping.items()}
        changed = True
    return 'legacy-integer-joint-keys' if changed and digest(legacy) == expected else None


def validate(payload, run_id):
    uuid.UUID(run_id)
    if not isinstance(payload, dict) or payload.get('schema') not in ('motion-guard-artifact-1', 'motion-guard-artifact-2') or payload.get('run_id') != run_id:
        raise ValueError('Report artifact identity mismatch')
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Nonfinite report artifact')
        if isinstance(value, dict):
            for x in value.values(): finite(x)
        elif isinstance(value, list):
            for x in value: finite(x)
    finite(payload)
    r = payload.get('report')
    if not isinstance(r, dict) or r.get('schema_version') not in ('mg-report-2', 'mg-report-3') or r.get('verdict') not in ('PASS', 'FAIL', 'UNCERTAIN', 'ERROR') or not isinstance(r.get('failures'), list):
        raise ValueError('Invalid report artifact structure')
    if r['verdict'] == 'PASS' and (r['failures'] or r.get('uncertain_reasons') != []):
        raise ValueError('Contradictory PASS report')
    if r['verdict'] == 'FAIL' and not r['failures']:
        raise ValueError('FAIL report has no failure evidence')
    axis = timeline(payload)
    if axis is None and r['failures']:
        raise ValueError('Failure intervals require a timeline')
    n, fps = (axis['frames'], axis['fps']) if axis else (0, 24)
    observations = payload.get('observations')
    if observations is not None:
        if axis is None or not isinstance(observations, dict) or set(observations) != {'r', 'g'}:
            raise ValueError('Invalid observation timeline')
        for pose in observations.values():
            if (not isinstance(pose, dict) or type(pose.get('frames')) is not int
                    or pose['frames'] != n or pose.get('fps') != fps
                    or any(not isinstance(pose.get(key), list) or len(pose[key]) != n
                           for key in ('points', 'scores', 'people'))):
                raise ValueError('Observation count differs from report timeline')
    for failure in r['failures']:
        if not isinstance(failure, dict) or not isinstance(failure.get('type'), str) or not isinstance(failure.get('evidence'), dict):
            raise ValueError('Invalid failure record')
        frames = failure.get('frames')
        start, end = failure.get('t_start_s'), failure.get('t_end_s')
        if (not isinstance(frames, list) or len(frames) != 2 or any(type(i) is not int for i in frames)
                or not 0 <= frames[0] <= frames[1] < n or type(start) not in (float, int)
                or type(end) not in (float, int) or not 0 <= start <= end <= n / fps
                or abs(start - frames[0] / fps) > 1e-6 or abs(end - (frames[1] + 1) / fps) > 1e-6):
            raise ValueError('Invalid failure interval')
    if digest_encoding(r, payload.get('report_sha256')) is None:
        raise ValueError('Report artifact digest mismatch')
    return payload


def write(path, report, context, run_id, observations=None):
    report = json.loads(json.dumps(report, allow_nan=False))
    payload = {'schema': 'motion-guard-artifact-2', 'run_id': run_id,
               'report': report, 'stage_context': context, 'observations': observations,
               'report_sha256': digest(report)}
    validate(payload, run_id)
    axis = timeline(payload)
    duration = axis['frames'] / axis['fps'] if axis else None
    text = json.dumps(payload, separators=(',', ':'), allow_nan=False)
    if len(text.encode()) > MAX_BYTES:
        raise ValueError('Report artifact exceeds size limit')
    image = Image.new('RGB', (768, 128), '#111827')
    draw = ImageDraw.Draw(image)
    draw.text((16, 12), 'MOTION GUARD / ' + report['verdict'], fill='white')
    span = f'0 - {duration:.2f} seconds' if duration else 'Invalid input timeline'
    draw.text((16, 32), 'Machine intervals; not human-confirmed labels. ' + span, fill='#cbd5e1')
    draw.rectangle((16, 62, 752, 90), fill='#475569')
    for failure in report['failures']:
        start, end = failure.get('t_start_s'), failure.get('t_end_s')
        if duration and isinstance(start, (float, int)) and isinstance(end, (float, int)) and 0 <= start <= end <= duration:
            draw.rectangle((16 + int(start / duration * 736), 62, 16 + int(end / duration * 736), 90), fill='#ef4444')
    draw.text((16, 104), 'Original PNG carries the full report; thumbnails are not report data.', fill='#cbd5e1')
    meta = PngImagePlugin.PngInfo(); meta.add_text(KEY, text)
    image.save(path, pnginfo=meta)
    return payload


def read(path, run_id):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES + 100_000:
        raise ValueError('Oversized report artifact')
    with Image.open(path) as image:
        if image.format != 'PNG' or image.size != (768, 128):
            raise ValueError('Unexpected report carrier')
        raw = image.info.get(KEY)
    if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
        raise ValueError('Report metadata missing or oversized')
    return validate(json.loads(raw), run_id)
