"""Restore the actual remote Guard result; never rerun pose inference."""
import copy
import hashlib
import json
import shutil
import subprocess
import uuid
import os
import tempfile
import re
from pathlib import Path
import cv2
import numpy as np
from motionguard_core.report_artifact import read as read_artifact, timeline as artifact_timeline
from motionguard_core.report import render


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, indent=2, allow_nan=False); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def mapped_gt_name(folder,submitted_sources):
    path=Path(submitted_sources['gt']['path'])
    if path.resolve().parent!=Path(folder).resolve() or path.name not in ('joints.json','joints.skin-v2.json','joints.observed.json'):
        raise ValueError('Submitted GT outside run or unsupported name')
    return path.name

def verified_wire_gt(folder, original, remote_hash, run_id):
    plan=json.loads((folder/'execution-plan.json').read_text(encoding='utf-8'))
    workflow_path=folder/'workflow.api.json'
    if plan.get('execution_id')!=run_id or sha(workflow_path)!=plan['input_hashes']['workflow.api.json']:
        raise ValueError('Submitted workflow identity changed')
    workflow=json.loads(workflow_path.read_text(encoding='utf-8'))
    wire=workflow['mg_inspect']['inputs']['gt_json'].encode('utf-8')
    if wire!=(folder/original).read_text(encoding='utf-8').encode('utf-8') or hashlib.sha256(wire).hexdigest()!=remote_hash:
        raise ValueError('Remote GT differs from submitted wire content')
    target=folder/'joints.wire.json'
    if target.exists():
        if target.read_bytes()!=wire:raise ValueError('Existing wire GT changed')
    else:
        with target.open('xb') as stream:stream.write(wire)
    return target.name

def preserve_draft(folder, outputs, run_id, submitted_sources):
    """Preserve a decoded same-job draft independently of Guard success."""
    folder=Path(folder).resolve()
    uuid.UUID(run_id)
    reference=folder/'reference.mp4'
    if sha(reference)!=submitted_sources['reference']['sha256']:
        raise ValueError('Draft reference changed')
    rows=[o for o in outputs if o.get('node_id')=='mg_inspect'
          and o.get('name')=='generated.mp4' and o.get('type')=='video']
    if not rows:
        rows=[o for o in outputs if o.get('node_id')=='diag_save' and o.get('type')=='video']
    if not rows:return False
    if len(rows)!=1:raise ValueError('Ambiguous recovered draft')
    source=Path(rows[0]['path']).resolve()
    if source.parent!=folder/'outputs' or not source.is_file():
        raise ValueError('Draft outside current job')
    cap=cv2.VideoCapture(str(source));frames=0
    fps=cap.get(cv2.CAP_PROP_FPS)
    size=(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    while cap.read()[0]:frames+=1
    cap.release()
    refcap=cv2.VideoCapture(str(reference));expected=int(refcap.get(cv2.CAP_PROP_FRAME_COUNT));ref_fps=refcap.get(cv2.CAP_PROP_FPS);ref_size=(int(refcap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(refcap.get(cv2.CAP_PROP_FRAME_HEIGHT)));refcap.release()
    if frames!=expected or not 9<=expected<=961 or (expected-1)%8 or fps!=24 or ref_fps!=24 or size!=ref_size or size not in ((768,512),(960,544)):
        raise ValueError('Recovered draft timeline invalid')
    shutil.copyfile(source,folder/'generated.mp4')
    save(folder/'draft-result.json',{'execution_id':run_id,
         'generated_sha256':sha(folder/'generated.mp4'),'reference_sha256':sha(reference),
         'frames':frames,'fps':fps,'size':list(size),'source_node':rows[0]['node_id'],'guard_independent':True})
    return True

def restore(folder, outputs, run_id, submitted_sources, publish_success=True):
    folder = Path(folder).resolve()
    uuid.UUID(run_id)
    gt_name=mapped_gt_name(folder,submitted_sources)
    # Source paths are locally recorded at submission, never supplied by the remote report.
    for role in ('reference', 'gt'):
        item = submitted_sources[role]
        if sha(item['path']) != item['sha256']:
            raise ValueError('Submitted source changed: ' + role)
    from motionguard_core.reference_io import validate_timeline
    timeline=validate_timeline(json.loads(Path(submitted_sources['gt']['path']).read_text(encoding='utf-8')))
    expected_frames=timeline['frames']
    gt=json.loads(Path(submitted_sources['gt']['path']).read_text(encoding='utf-8'))
    width,height=gt['meta'].get('width'),gt['meta'].get('height')
    if type(width) is not int or type(height) is not int or (width,height) not in ((768,512),(960,544)):
        raise ValueError('Unsupported GT image dimensions')
    candidates = [o for o in outputs if o.get('node_id') == 'mg_inspect']
    def output(name, expected_type):
        rows = [o for o in candidates if o.get('name') == name and o.get('type') == expected_type]
        if len(rows) != 1:
            raise ValueError('Expected exactly one Inspector artifact: ' + name)
        p = Path(rows[0]['path']).resolve()
        if p.parent != folder / 'outputs' or not p.is_file():
            raise ValueError('Downloaded artifact outside this run')
        return p
    carrier = output('guard-result.png', 'image')
    payload = read_artifact(carrier, run_id)
    if artifact_timeline(payload) != {'frames': expected_frames, 'fps': timeline['fps']}:
        raise ValueError('Remote report timeline differs from submitted GT')
    remote = payload['report']
    save(folder/'remote-guard-payload.json', payload)
    if remote['verdict'] == 'ERROR':
        raise ValueError('Remote Guard ERROR: ' + str(remote.get('error', 'unspecified'))[:500])
    generated = output('generated.mp4', 'video')
    sources = remote.get('sources', {})
    if set(sources) != {'reference', 'generated', 'gt'}:
        raise ValueError('Missing report sources')
    for role in ('reference', 'gt'):
        if sources[role]['sha256'] != submitted_sources[role]['sha256']:
            if role!='gt':raise ValueError('Remote source mismatch: ' + role)
            gt_name=verified_wire_gt(folder,gt_name,sources[role]['sha256'],run_id)
    if sha(generated) != sources['generated']['sha256']:
        raise ValueError('Remote generated video mismatch')
    context = payload.get('stage_context', {})
    if context.get('stage_id') != run_id or context.get('sources') != sources:
        raise ValueError('Remote stage context mismatch')
    observations = payload.get('observations', {})
    for label, role in (('r', 'reference'), ('g', 'generated')):
        p = observations[label]
        if (p['video_sha256'] != sources[role]['sha256'] or p['frames'] != expected_frames or p['fps'] != 24
                or p['size'] != [width, height] or p['settings'] != 'rtmpose-balanced-coco17-to-openpose18-v1'
                or p['estimator'] != 'rtmlib 0.0.16'):
            raise ValueError('Unexpected remote pose provenance')
        for name, shape in (('points', (expected_frames, 18, 2)), ('scores', (expected_frames, 18)), ('people', (expected_frames,))):
            a = np.asarray(p[name])
            if a.shape != shape or not np.isfinite(a).all():
                raise ValueError('Invalid remote pose arrays')
    cap = cv2.VideoCapture(str(generated))
    actual = (int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS),
              int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    if actual != (expected_frames, 24, width, height):
        raise ValueError('Downloaded video timeline mismatch')
    old = json.loads((folder/'state.json').read_text(encoding='utf-8')) if (folder/'state.json').exists() else {}
    directory = old.get('guard_directory', '')
    if old.get('guard_status') == 'complete' and re.fullmatch(r'guard-[a-f0-9]{32}', directory):
        mapped = json.loads((folder/directory/'report.json').read_text(encoding='utf-8'))
        expected = copy.deepcopy(remote)
        for role, name in (('reference', 'reference.mp4'), ('generated', 'generated.mp4'), ('gt', gt_name)):
            if sha(folder/name) != sources[role]['sha256']:
                raise ValueError('Restored source changed')
            expected['sources'][role]['path'] = str(folder/name)
        if mapped != expected or not (folder/directory/'overlay.mp4').is_file() or not (folder/'comparison.mp4').is_file():
            raise ValueError('Restored result incomplete or changed')
        return mapped
    guard = folder / ('guard-' + uuid.uuid4().hex)
    guard.mkdir()
    shutil.copyfile(generated, folder/'generated.mp4')
    mapped = copy.deepcopy(remote)
    for role, name in (('reference', 'reference.mp4'), ('generated', 'generated.mp4'), ('gt', gt_name)):
        local = folder/name
        if sha(local) != sources[role]['sha256']:
            raise ValueError('Local mapped source differs: ' + role)
        mapped['sources'][role]['path'] = str(local)
    save(guard/'report.json', mapped)
    save(guard/'reference-pose.json', observations['r'])
    save(guard/'generated-pose.json', observations['g'])
    # Kept for the record of what the remote stage did before the check (for example latent_repairs).
    save(guard/'stage-context.json', {k: v for k, v in context.items() if k != 'sources'})
    save(folder/'guard-inputs.json', mapped['sources'])
    render(folder/'reference.mp4', folder/'generated.mp4', guard)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder/'reference.mp4'), '-i', str(folder/'generated.mp4'),
                    '-filter_complex', 'hstack=inputs=2', '-an', '-c:v', 'libx264', '-crf', '19',
                    '-pix_fmt', 'yuv420p', str(folder/'comparison.mp4')], check=True, timeout=60,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    previous = json.loads((folder/'state.json').read_text(encoding='utf-8')) if (folder/'state.json').exists() else {}
    save(folder/'state.json', {**previous, 'run_id': folder.name, 'status': 'succeeded' if publish_success else 'restoring', 'source_type': 'platform_guarded',
                             'generated_now': True, 'guard_status': 'complete', 'guard_verdict': remote['verdict'],
                             'guard_directory': guard.name, 'remote_execution_id': run_id,
                             'remote_report_sha256': payload['report_sha256']})
    return mapped
