"""App adapter for the verified guarded runtime; never falls back to Cloud generation."""
import hashlib
import secrets
import uuid
from app import ROOT, read, save, selected_gt


def prepare_execution(folder):
    from run_platform_once import prepared_inputs
    from platform_preflight import execution_profile
    config = read(ROOT/'config/guarded-runtime.json')
    if (folder/'attempt.json').exists() or (folder/'execution-plan.json').exists():
        raise ValueError('Existing execution must not be prepared again')
    gpu, reservation = execution_profile(config)
    if config.get('enabled') is not True:
        raise ValueError('Guarded runtime has not passed integration verification')
    template = ROOT/'workflows/T5/guarded-ltx-local-template.api.json'
    if hashlib.sha256(template.read_bytes()).hexdigest() != config['template_sha256']:
        raise ValueError('Guarded template changed')
    workflow = read(template)
    execution = str(uuid.uuid4()); seed = secrets.randbits(32)
    for node in ('5516/4832', '5517/4967'):
        workflow[node]['inputs']['noise_seed'] = seed
    workflow['5014/2483']['inputs']['text'] = read(folder/'input.json')['prompt']
    workflow['2004']['inputs']['image'] = str(folder/'character.png')
    workflow['5001']['inputs']['file'] = str(folder/'pose.mp4')
    workflow['mg_bind']['inputs']['run_id'] = execution
    workflow['mg_inspect']['inputs']['reference_video'] = str(folder/'reference.mp4')
    gt = selected_gt(folder)
    from motionguard_core.reference_io import validate_timeline
    timeline = validate_timeline(read(gt))
    if timeline['frames'] > config.get('max_frames',97):
        raise ValueError('Configured remote release does not support this timeline yet')
    seconds = 600
    if gpu == 'h100-sxm':
        from platform_preflight import guarded_limits
        seconds, reservation = guarded_limits(timeline['frames'])
    import json
    from gt_compact import compact
    gt.write_bytes(json.dumps(compact(read(gt)), separators=(',', ':')).encode('utf-8'))
    workflow['mg_inspect']['inputs']['gt_json'] = gt.read_text(encoding='utf-8')
    if len(json.dumps(workflow).encode('utf-8')) > 9_500_000:
        raise ValueError('Reference data too large for one job (provider limit 10 MB)')
    audit_pin = None
    if config.get('stage_audit_code_sha256'):
        from stage_audit_graph import upgrade, digest
        code_sha = hashlib.sha256((ROOT/'comfy_nodes/stage_audit.py').read_bytes()).hexdigest()
        if code_sha != config['stage_audit_code_sha256']:
            raise ValueError('Stage audit implementation changed')
        workflow = upgrade(workflow)
        audit_pin = {'graph_sha256': digest(workflow), 'code_sha256': code_sha}
    save(folder/'workflow.api.json', workflow)
    plan = {'purpose': 'User-requested guarded generation', 'execution_id': execution, 'gt_file': gt.name,
            'approved_release_id': config['release_id'], 'seed': seed,
            'gpu_class': gpu, 'max_credits_reservation': reservation, 'deadline_seconds': seconds, 'no_automatic_retry': True,
            'expected_final_size': [1536, 1024], 'expected_frames':timeline['frames'], 'expected_fps':timeline['fps'],
            'input_hashes': {name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
                             for name in ('character.png', 'pose.mp4', 'reference.mp4', gt.name, 'workflow.api.json')}}
    if audit_pin is not None:
        plan['stage_audit'] = audit_pin
    save(folder/'execution-plan.json', plan)
    prepared_inputs(folder)
    return config['release_id']


def generate(folder):
    from run_guarded_platform import run
    return run(prepare_execution(folder), folder)


def resume(folder):
    """Restart resumes cleanup/accounting/retrieval only, with no generation call."""
    from run_platform_once import recover, prepared_directory
    from run_guarded_platform import settle, finish_or_explain
    folder = prepared_directory(folder)
    if not (folder/'finished.json').exists():
        if recover(folder) is False:
            raise ValueError('Deployment identity unresolved; reservation retained')
        save(folder/'finished.json', {'recovered_cleanup': True})
    settle(folder)
    state = read(folder/'state.json')
    if state.get('downstream_status') not in ('complete', 'held') or not (folder/'downstream-result.json').exists():
        finish_or_explain(folder)


def needs_recovery(folder, state, ledger):
    if not (folder/'attempt.json').exists():
        return False
    if not (folder/'finished.json').exists() or folder.name in ledger.get('unresolved_jobs', []):
        return True
    return state.get('status') not in ('succeeded', 'failed', 'canceled', 'expired')
