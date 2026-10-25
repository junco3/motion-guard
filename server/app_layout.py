"""One Layout execution per explicit job using the existing budget/watchdog."""
import hashlib
import secrets
import uuid
from pathlib import Path
from app import ROOT, LEDGER, read, save, selected_gt
from layout_graph import build, validate
from stage_audit_graph import digest


def prepare_execution(folder):
    config_path = ROOT/'config/layout-runtime.json'
    config = read(config_path)
    from layout_claim import completed_claim
    if config.get('enabled') is not True or not completed_claim(ROOT, config, read(LEDGER)):
        raise ValueError('Layout unavailable or previous execution/settlement incomplete')
    if (folder/'attempt.json').exists() or (folder/'execution-plan.json').exists():
        raise ValueError('Existing execution must not be prepared again')
    template = ROOT/'workflows/T1/layout-i2v.api.json'
    code = ROOT/'comfy_nodes/stage_audit.py'
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if sha(template) != config['template_sha256'] or sha(code) != config['stage_audit_code_sha256']:
        raise ValueError('Layout release inputs changed')
    gt = selected_gt(folder)
    request = read(folder/'input.json')
    if request.get('generator_mode') != 'layout': raise ValueError('Layout input required')
    execution = str(uuid.uuid4()); seed = secrets.randbits(32)
    workflow = build(execution, str(folder/'character.png'), str(folder/'reference.mp4'),
                     str(folder/'reference.mp4'), gt.read_text(encoding='utf-8'), request['prompt'], seed)
    validate(workflow)
    save(folder/'workflow.api.json', workflow)
    from motionguard_core.reference_io import validate_timeline
    timeline = validate_timeline(read(gt))
    if timeline['frames'] > 97: raise ValueError('Layout comparison limited to 97 frames')
    plan = {'purpose':'User-requested guarded generation','generator_mode':'layout',
            'execution_id':execution,'gt_file':gt.name,'approved_release_id':config['release_id'],
            'seed':seed,'gpu_class':'h100-sxm','max_credits_reservation':280,'deadline_seconds':600,
            'no_automatic_retry':True,'expected_final_size':[1920,1088],
            'expected_frames':timeline['frames'],'expected_fps':24,
            'stage_audit':{'graph_sha256':digest(workflow),'code_sha256':sha(code)},
            'input_hashes':{name:sha(folder/name) for name in ('character.png','reference.mp4',gt.name,'workflow.api.json')}}
    save(folder/'execution-plan.json',plan)
    from run_platform_once import prepared_inputs
    prepared_inputs(folder)
    # Server holds its generation lock here. Preserve the completed job claim;
    # restarting or resubmitting the same folder can never allocate another run.
    if config.get('claimed_run'):
        config.setdefault('claim_history', []).append({k:config[k] for k in
            ('release_id','claimed_run','claimed_execution_id','claimed_plan_sha256')})
    config['claimed_run'] = folder.name
    config['claimed_execution_id'] = execution
    config['claimed_plan_sha256'] = sha(folder/'execution-plan.json')
    save(config_path, config)
    return config['release_id']


def validate_inputs(folder, plan, workflow, gt_name):
    validate(workflow)
    if workflow['mg_bind']['inputs']['run_id'] != plan['execution_id']:
        raise ValueError('Layout execution identity mismatch')
    if digest(workflow) != plan['stage_audit']['graph_sha256']:
        raise ValueError('Layout audit mismatch')
    if workflow['mg_inspect']['inputs']['gt_json'] != (folder/gt_name).read_text(encoding='utf-8'):
        raise ValueError('Layout GT changed')
    for node, field, name in (('9009','image','character.png'),('5001','file','reference.mp4'),('mg_inspect','reference_video','reference.mp4')):
        if Path(workflow[node]['inputs'][field]).resolve() != folder/name:
            raise ValueError('Layout asset path mismatch')
    from comfy_cli.command.deploy_workflow import scan_workflow_inputs
    assets = scan_workflow_inputs(workflow, asset_roots=(folder,)).assets
    if {a.local_path.resolve() for a in assets} != {folder/'character.png',folder/'reference.mp4'}:
        raise ValueError('Unexpected Layout assets')
    from timeline_contract import decoded_video
    from motionguard_core.reference_io import validate_timeline, project_world
    import numpy as np
    gt = read(folder/gt_name); timeline = validate_timeline(gt)
    if plan['expected_final_size'] != [1920,1088] or plan['expected_frames'] != timeline['frames'] or plan['expected_fps'] != 24:
        raise ValueError('Layout timeline plan mismatch')
    if decoded_video(folder/'reference.mp4',(544,960),reject_black=True) != {'frames':timeline['frames'],'fps':24}:
        raise ValueError('Layout video mismatch')
    if (gt['meta']['width'],gt['meta']['height']) != (960,544): raise ValueError('Layout GT size mismatch')
    for frame in gt['frames']:
        camera = frame['camera']
        if (camera['width'],camera['height']) != (960,544) or abs(camera['aspect']-960/544)>1e-8:
            raise ValueError('Layout projection mismatch')
        for joint in frame['joints']:
            if joint.get('in_frame') and joint.get('pixel') is not None:
                if np.linalg.norm(project_world(joint['world'],camera)-joint['pixel']) >= 1:
                    raise ValueError('Layout GT reprojection exceeds one pixel')
    return folder,workflow


def generate(folder):
    from run_guarded_platform import run
    return run(prepare_execution(folder),folder)
