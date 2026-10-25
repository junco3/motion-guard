"""Bounded, locally supervised model retention; not a provider spending cap."""
import math
import hashlib
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from app import ROOT, LEDGER, read, save, key, authorized_ceiling
from deployment_reuse import account_digest, pin_path
import portable_lock

LIFETIME = 1800
CLEANUP_MARGIN = 60


@contextmanager
def accounting_lock():
    with (LEDGER.parent/'guarded-accounting.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        portable_lock.lock(lock)
        try:yield
        finally:
            lock.seek(0);portable_lock.unlock(lock)


def lease_path():return ROOT/'data/platform-storage-lease.json'


def cancel_uncreated(lease, folder, before_submission=False):
    """Called only by the owner before any create/start call, never by inference."""
    if lease['origin_run']!=folder.name:
        raise ValueError('Cannot cancel a possibly started lease')
    if (folder/'attempt.json').exists():
        if not before_submission:
            raise ValueError('Cannot cancel a possibly started lease')
        attempt=read(folder/'attempt.json')
        if (attempt.get('storage_lease_id')!=lease['id'] or attempt.get('deployment_id')
                or attempt.get('reused_deployment')):
            raise ValueError('Cannot cancel a possibly started lease')
    with accounting_lock():
        ledger=read(LEDGER);record=ledger['storage_leases'][lease['id']]
        if record.get('deployment_id'):
            raise ValueError('Cannot cancel an identified deployment')
        ledger['unresolved_jobs']=[run for run in ledger['unresolved_jobs'] if run!=folder.name]
        record.update(status='deleted',closed_reason='owner_confirmed_no_create_or_start',closed_at=time.time())
        save(folder/'creation-never-started.json',{'lease_id':lease['id'],'at':time.time()})
        save(LEDGER,ledger);save(lease_path(),record)


def quote(catalog, release_id):
    from platform_preflight import storage_policy
    cost,pinned=storage_policy(ROOT,release_id)
    rates=[r.get('creditsPerGbMonth') for r in catalog.get('storage',[])
           if r.get('storageType')=='network_standard']
    if len(rates)!=1 or rates[0]!=pinned['catalog_credits_per_gb_month']:
        raise ValueError('Storage catalog changed')
    # Reserve a full hour (including cleanup margin), using the shortest month.
    return cost


def reserve(folder, credential, catalog, release_id, run_reservation, prior, seconds):
    now=time.time()
    with accounting_lock():
        ledger=read(LEDGER)
        if max(prior,ledger['conservative_prior_credits'])+run_reservation>authorized_ceiling(read(ROOT/'config/budget.yaml')):
            raise ValueError('Storage and execution reservations exceed cumulative ceiling')
        lease=read(lease_path()) if lease_path().exists() else None
        if lease and lease.get('status')!='deleted':
            if lease.get('account_sha256')!=account_digest(credential):
                raise ValueError('Storage lease account mismatch')
            pin=read(pin_path(ROOT)) if pin_path(ROOT).exists() else {}
            if (pin.get('origin_run')!=lease['origin_run'] or not pin.get('deployment_id')
                    or pin.get('release_id')!=release_id):
                raise ValueError('Existing lease has no bound owned deployment; cleanup required')
            if lease['expires_at']-now<seconds+CLEANUP_MARGIN:
                raise ValueError('Existing storage lease requires cleanup before another run')
            heartbeat=read(ROOT/'data'/('lease-'+lease['id']+'.heartbeat.json'))
            if now-heartbeat.get('at',0)>20:
                raise ValueError('Storage supervisor unavailable; recover existing lease first')
            return lease
        cost=quote(catalog,release_id)
        if max(prior,ledger['conservative_prior_credits'])+cost+run_reservation>authorized_ceiling(read(ROOT/'config/budget.yaml')):
            raise ValueError('Storage and execution reservations exceed cumulative ceiling')
        lease={'id':uuid.uuid4().hex,'origin_run':folder.name,'account_sha256':account_digest(credential),
               'created_at':now,'expires_at':now+max(LIFETIME,seconds+CLEANUP_MARGIN+600),'reserved_credits':cost,
               'status':'reserved','deployment_id':None,'release_id':release_id}
        ledger.setdefault('storage_leases',{})[lease['id']]=lease
        ledger['conservative_prior_credits']=max(prior,ledger['conservative_prior_credits'])+cost
        save(LEDGER,ledger);save(lease_path(),lease)
    return lease


def supervise(lease_id):
    from comfy_cli.deploy_api import DeployClient
    from run_platform_once import deletion_confirmed, controlplane_deletion_confirmed
    lock_path=ROOT/'data'/('lease-'+lease_id+'.lock')
    with lock_path.open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:portable_lock.lock(lock,blocking=False)
        except OSError:return
        credential=key();os.environ['COMFY_CLOUD_API_KEY']=credential
        client=DeployClient.from_credentials()
        while True:
            lease=read(lease_path())
            if lease['id']!=lease_id or lease['account_sha256']!=account_digest(credential):return
            save(ROOT/'data'/('lease-'+lease_id+'.heartbeat.json'),{'at':time.time(),'pid':os.getpid()})
            if lease.get('status')=='deleted':return
            if time.time()<lease['expires_at']:
                time.sleep(3);continue
            folder=ROOT/'data/gen'/lease['origin_run']
            try:
                attempt=read(folder/'attempt.json')
                did=attempt.get('deployment_id')
                if not did:
                    created=read(folder/'deployment-created.json')
                    did=created['id']
                snapshot=client.get_deployment(did)
                if snapshot.get('releaseId')!=attempt['release_id']:raise ValueError('Lease deployment mismatch')
                if not snapshot.get('deletedAt'):
                    client.stop_deployment(did);client.delete_deployment(did)
                    snapshot=client.get_deployment(did)
                if not (deletion_confirmed(snapshot) or controlplane_deletion_confirmed(client,snapshot,folder)):
                    raise ValueError('Lease deletion not confirmed')
                with accounting_lock():
                    ledger=read(LEDGER);record=ledger['storage_leases'][lease_id]
                    if record.get('status')!='deleted':
                        record.update(status='deleted',deleted_at=time.time(),deployment_id=did)
                        save(LEDGER,ledger);save(lease_path(),record)
                save(folder/'storage-deletion.json',snapshot)
                pin=pin_path(ROOT)
                if pin.exists() and read(pin).get('deployment_id')==did:pin.unlink()
                return
            except Exception as error:
                save(ROOT/'data'/('lease-'+lease_id+'.error.json'),{'type':type(error).__name__,'at':time.time()})
                time.sleep(5)


def launch(lease):
    started=time.time()
    with (ROOT/'data'/('lease-'+lease['id']+'.stderr.log')).open('ab') as errors:
        subprocess.Popen([sys.executable,str(ROOT/'server/storage_lease.py'),lease['id']],
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    heartbeat=ROOT/'data'/('lease-'+lease['id']+'.heartbeat.json')
    for _ in range(20):
        if heartbeat.exists() and started<=read(heartbeat).get('at',0)<=time.time():return
        time.sleep(0.5)
    raise RuntimeError('Storage supervisor did not start; no deployment created')


def ensure_existing(credential):
    if not lease_path().exists():return
    lease=read(lease_path())
    if lease.get('status')=='deleted':return
    if lease.get('account_sha256')!=account_digest(credential):raise ValueError('Existing lease account mismatch')
    launch(lease)
    if lease['expires_at']-time.time()<600+CLEANUP_MARGIN:
        raise ValueError('Existing lease cleanup pending; no new paid execution')


if __name__=='__main__':supervise(sys.argv[1])
