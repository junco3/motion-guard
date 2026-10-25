"""Owned stopped deployments retain staged models; never adopt an unknown endpoint."""
import hashlib
from datetime import datetime
from pathlib import Path


def pin_path(root):
    return root/'data/platform-deployment.json'


def account_digest(credential):
    return hashlib.sha256(credential.encode()).hexdigest()


def identify_lost_create(rows, attempt):
    matches=[r for r in rows if r.get('releaseId')==attempt['release_id']
             and r.get('idempotencyKey')==attempt['idempotency_key'] and not r.get('deletedAt')]
    if len(matches)!=1:return None
    return matches[0]['id']


def remember(root, folder, record, attempt, build, credential, save):
    if not record.get('id') or record.get('releaseId') != attempt['release_id']:
        raise ValueError('Created deployment identity mismatch')
    pin = {'version': 1, 'deployment_id': record['id'], 'release_id': attempt['release_id'],
           'build_id': build, 'compute': attempt['compute'], 'account_sha256': account_digest(credential),
           'origin_run': folder.name, 'creation_key': attempt['idempotency_key']}
    save(pin_path(root), pin)
    return pin


def select(root, rows, release, build, compute, credential, read):
    path = pin_path(root)
    if not path.exists():
        if any(not r.get('deletedAt') for r in rows):
            raise ValueError('Unowned deployment exists')
        return None
    pin = read(path)
    import re
    if not re.fullmatch(r't3-[a-f0-9]{32}', pin.get('origin_run', '')):
        raise ValueError('Invalid deployment origin')
    origin = root/'data/gen'/pin['origin_run']
    attempt = read(origin/'attempt.json'); created = read(origin/'deployment-created.json')
    expected = (release, build, compute, account_digest(credential))
    if (pin.get('release_id'), pin.get('build_id'), pin.get('compute'), pin.get('account_sha256')) != expected:
        raise ValueError('Stored deployment does not match account/release/compute')
    if (attempt.get('idempotency_key') != pin.get('creation_key')
            or attempt.get('release_id') != release or attempt.get('compute') != compute
            or created.get('id') != pin.get('deployment_id')
            or (created.get('releaseId') is not None and created['releaseId'] != release)):
        raise ValueError('Deployment ownership evidence changed')
    live = [r for r in rows if not r.get('deletedAt')]
    if len(live) != 1 or live[0].get('id') != pin['deployment_id']:
        raise ValueError('Stored deployment missing or another deployment exists')
    row = live[0]
    if row.get('releaseId') != release or row.get('status') != 'stopped' or any((row.get('computeConfig') or {}).get(k)!=v for k,v in compute.items()):
        raise ValueError('Owned deployment is not stopped with expected compute')
    return pin


def stopped_evidence_valid(snapshot, events, attempt):
    if (snapshot.get('deletedAt') or snapshot.get('status') != 'stopped'
            or snapshot.get('releaseId') != attempt.get('release_id')
            or events.get('deploymentId') != snapshot.get('id')):
        return False
    if attempt.get('deployment_id') and snapshot.get('id') != attempt['deployment_id']:
        return False
    def stamp(value):
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:raise ValueError('Timezone required')
        return date.timestamp()
    try:
        stopped = [stamp(e['at']) for e in events.get('events', [])
                   if e.get('status') == 'stopped' and e.get('releaseId') == attempt['release_id']]
        fresh = [t for t in stopped if t >= max(attempt['started_at'],attempt.get('stop_not_before',0))]
        if not fresh:return False
        serving = snapshot.get('serving') or {}; workers = serving.get('workers') or {}
        if any(type(v) is int and v > 0 for v in workers.values()):
            if stamp(serving['sampledAt']) >= max(fresh):return False
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    return True


def confirm_stopped(client, snapshot, folder, attempt, save):
    if snapshot.get('status') != 'stopped' or snapshot.get('deletedAt'):return False
    events = client.get_deployment_events(snapshot['id'])
    if not stopped_evidence_valid(snapshot, events, attempt):return False
    save(folder/'control-plane-stop.json', {'snapshot': snapshot, 'events': events,
         'models_retained_by_stop_contract': True, 'model_reuse_observed': False})
    return True
