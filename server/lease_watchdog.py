"""Restore only the existing bounded cleanup supervisor; never provision work."""
import re
import time
import uuid
from app import ROOT, read, save, key
from storage_lease import accounting_lock, account_digest, launch


def tick():
    path = ROOT/'data/platform-storage-lease.json'
    if not path.exists(): return
    lease = read(path)
    if lease.get('status') == 'deleted': return
    lid = lease['id']
    if not re.fullmatch('[0-9a-f]{32}', lid): raise ValueError('Invalid lease identity')
    heartbeat = ROOT/'data'/f'lease-{lid}.heartbeat.json'
    if heartbeat.exists() and 0 <= time.time()-read(heartbeat).get('at', 0) <= 20: return
    record = ROOT/'data'/f'lease-{lid}.restarts.json'
    previous = read(record) if record.exists() else {'attempts': []}
    if len(previous['attempts']) >= 3: return
    account = account_digest(key())
    with accounting_lock():
        current = read(path)
        if current.get('id') != lid or current.get('status') == 'deleted': return
        if current.get('account_sha256') != account: raise ValueError('Lease account mismatch')
        previous = read(record) if record.exists() else {'attempts': []}
        if len(previous['attempts']) >= 3: return
        attempt_id = uuid.uuid4().hex
        previous['attempts'].append({'id': attempt_id, 'at': time.time(), 'status': 'starting'})
        save(record, previous)
    try:
        launch(current)
        result = {'status': 'heartbeat_verified'}
    except Exception as error:
        result = {'status': 'failed', 'error_type': type(error).__name__}
    with accounting_lock():
        latest = read(record)
        for attempt in latest['attempts']:
            if attempt.get('id') == attempt_id:
                attempt.update(result)
                break
        save(record, latest)


def monitor():
    while True:
        try: tick()
        except Exception as error:
            try: save(ROOT/'data/lease-monitor-error.json', {'at':time.time(), 'type':type(error).__name__})
            except OSError: pass
        time.sleep(10)
