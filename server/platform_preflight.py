"""Local readiness and reservation preview. Never reserves or calls the provider."""
import hashlib
import json
import math
import time

def execution_profile(config):
    gpu = config.get('gpu_class', 'rtx-pro-6000-server')
    if gpu not in ('rtx-pro-6000-server', 'h100-sxm'):
        raise ValueError('Unsupported GPU policy')
    return gpu, 280 if gpu == 'h100-sxm' else 202

# H100 guarded generation: deadline and credit reservation grow with the timeline.
# Measured: 4s ends in 270-560s, 10s in 370-600s (two hit 600s). Reservation covers
# 1314.53 credits/hour for the whole deadline plus storage and margin.
H100_GUARDED_LIMITS = ((97, 600, 280), (241, 900, 420), (721, 1800, 840), (961, 2400, 1120))
H100_GUARDED_PROFILES = {(s, r) for _, s, r in H100_GUARDED_LIMITS}

def guarded_limits(frames):
    for most, seconds, reservation in H100_GUARDED_LIMITS:
        if frames <= most:
            return seconds, reservation
    raise ValueError('Timeline longer than the supported guarded limit')

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def pinned_storage_cost(root, release):
    pinned = read(root/'config/platform-storage-quote.json')
    path = (root/pinned['evidence']).resolve()
    if not path.is_relative_to((root/'data/gen').resolve()):
        raise ValueError('Storage evidence outside runs')
    if hashlib.sha256(path.read_bytes()).hexdigest() != pinned['sha256']:
        raise ValueError('Storage evidence changed')
    rows = [r for r in read(path).get('releases', [])
            if r.get('current') and r.get('releaseId') == release]
    price = pinned['storage_monthly_cents']
    rate = pinned['catalog_credits_per_gb_month']
    if (pinned['release_id'] != release or len(rows) != 1
            or rows[0].get('storageMonthlyCents') != price
            or pinned['credits_per_cent'] != 2.11
            or any(isinstance(x, bool) or not isinstance(x,(float,int))
                   or not math.isfinite(x) or x <= 0 for x in (price,rate))):
        raise ValueError('Storage release quote mismatch')
    return math.ceil(price * 2.11 / (28*24)), pinned

def storage_policy(root, release):
    """A bootstrap allowance is a local reservation, never a provider quote."""
    old = read(root/'config/platform-storage-quote.json')
    cost, pinned = pinned_storage_cost(root, old['release_id'])
    if old['release_id'] == release:
        return cost, pinned
    config = read(root/'config/guarded-runtime.json')
    layout_path = root/'config/layout-runtime.json'
    if config.get('release_id') != release and layout_path.exists():
        config = read(layout_path)
    allowance = config.get('bootstrap_storage_reservation_credits')
    code = root/'comfy_nodes/stage_audit.py'
    if (config.get('release_id') != release or type(allowance) is not int
            or allowance != 10 or not code.is_file()
            or hashlib.sha256(code.read_bytes()).hexdigest() != config.get('stage_audit_code_sha256')):
        raise ValueError('New release needs an explicit bootstrap storage allowance')
    return allowance, {'release_id':release, 'provisional':True,
                       'storage_monthly_cents':allowance*(28*24)/2.11,
                       'credits_per_cent':2.11,
                       'catalog_credits_per_gb_month':pinned['catalog_credits_per_gb_month']}

def preview(root, config, now=None):
    now = time.time() if now is None else now
    try:
        gpu, reservation = execution_profile(config)
        if not config.get('release_id') or not config.get('build_id'):
            raise ValueError('Build/release settings required')
        template = root/('workflows/T1/layout-i2v.api.json' if config.get('generator_mode')=='layout' else 'workflows/T5/guarded-ltx-local-template.api.json')
        if hashlib.sha256(template.read_bytes()).hexdigest() != config.get('template_sha256'):
            raise ValueError('Run workflow verification required')
        cost, _ = storage_policy(root, config['release_id'])
        lease_path = root/'data/platform-storage-lease.json'
        lease = read(lease_path) if lease_path.exists() else {}
        if lease and lease.get('status') != 'deleted':
            pin = read(root/'data/platform-deployment.json')
            if (not pin.get('deployment_id') or not pin.get('account_sha256')
                    or pin.get('account_sha256') != lease.get('account_sha256')
                    or pin.get('origin_run') != lease.get('origin_run')
                    or pin.get('release_id') != config['release_id']
                    or pin.get('build_id') != config['build_id']
                    or pin.get('compute') != {'gpuClass':gpu,'region':'anywhere','min':0,'max':1}):
                raise ValueError('Account, model, and GPU check required for the existing deployment')
            if lease['expires_at'] - now < 660:
                minutes=math.ceil(max(0,lease['expires_at']-now)/60)
                raise ValueError(f'Waiting for cleanup of existing retained environment · retention deadline in about {minutes} min · auto-refresh after cleanup')
            heartbeat = read(root/'data'/('lease-'+lease['id']+'.heartbeat.json'))
            if not 0 <= now-heartbeat.get('at',0) <= 20:
                raise ValueError('Existing retention supervisor status check required')
            cost = 0
        return {'ready':True,'required_reservation':reservation+cost,'storage_reservation':cost,
                'scope':'local snapshot; provider/account/catalog rechecked before submission'}
    except (OSError,ValueError,KeyError,TypeError) as error:
        return {'ready':False,'required_reservation':None,'reason':str(error)}
