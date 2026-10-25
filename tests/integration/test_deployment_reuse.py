import sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app, deployment_reuse as reuse, run_platform_once as runner, run_guarded_platform as guarded
import comfy_cli.deploy_download as download
import storage_lease


class Deployment:
    def __init__(self, release):
        self.release=release;self.row=None;self.calls=[];self.events=[];self.fail_start=False
    def list_all_deployments(self):return [dict(self.row)] if self.row else []
    def get_compute_catalog(self):return {'regions':[{'region':'anywhere','gpus':[{'gpuClass':'rtx-pro-6000-server','creditsPerHour':957.94}]}], 'storage':[{'storageType':'network_standard','creditsPerGbMonth':42.2}]}
    def get_deploy_estimate(self,*a):return {'bytesHeld':0,'billableStorageBytesUpperBound':80000000000}
    def create_deployment(self,release,compute,**kwargs):
        self.calls.append('create');self.row={'id':'dep-owned','releaseId':release,'status':'ready','computeConfig':{**compute,'keepWarmSeconds':180},'releases':[{'current':True,'releaseId':release,'storageMonthlyCents':1540}]}
        return {'id':'dep-owned','status':'queued'}
    def get_deployment(self,did):assert did=='dep-owned';return dict(self.row)
    def start_deployment(self,did):
        self.calls.append('start');self.row['status']='ready'
        if self.fail_start:raise ConnectionError('Response lost after start')
        return dict(self.row)
    def stop_deployment(self,did):
        self.calls.append('stop');self.row['status']='stopped'
        self.events.append({'status':'stopped','releaseId':self.release,'at':datetime.fromtimestamp(time.time()+0.002,timezone.utc).isoformat()})
        return dict(self.row)
    def get_deployment_events(self,did):return {'deploymentId':did,'events':self.events[:]}
    def get_deployment_logs(self,did):return {}
    def delete_deployment(self,did):pytest.fail('Reusable deployment must not be deleted')


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    for module in (runner,guarded,storage_lease):
        monkeypatch.setattr(module,'ROOT',tmp_path)
        monkeypatch.setattr(module,'LEDGER',tmp_path/'ledger.json')
    app.save(tmp_path/'ledger.json',{'conservative_prior_credits':0,'unresolved_jobs':[],'known_runs':[]})
    app.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':2000,'max_deployment_active_minutes':10,'max_storage_charge':2})
    build=str(uuid.uuid4());release=str(uuid.uuid4());client=Deployment(release)
    evidence=tmp_path/'data/gen/previous/deployment-latest.json'
    app.save(evidence,{'releases':[{'current':True,'releaseId':release,'storageMonthlyCents':1540}]})
    app.save(tmp_path/'config/platform-storage-quote.json',{'release_id':release,'evidence':'data/gen/previous/deployment-latest.json','sha256':app.sha(evidence.read_bytes()),'storage_monthly_cents':1540,'catalog_credits_per_gb_month':42.2,'credits_per_cent':2.11})
    app.save(tmp_path/'config/guarded-runtime.json',{'build_id':build})
    monkeypatch.setattr(runner,'key',lambda:'fake-key')
    monkeypatch.setattr(runner,'api',lambda *a:{'summary':{'balance':{'cloud_credit_balance_cents':10000}}})
    monkeypatch.setattr(runner,'cumulative_prior',lambda ledger,*a:ledger['conservative_prior_credits'])
    monkeypatch.setattr(runner.DeployClient,'from_credentials',lambda:client)
    monkeypatch.setattr(runner.BuilderClient,'from_credentials',lambda *a:SimpleNamespace(get_release=lambda r:{'id':r,'buildId':build,'deployable':True,'artifacts':[{'os':'linux','gpu':'nvidia','status':'ready'}]}))
    monkeypatch.setattr(storage_lease,'launch',lambda lease:app.save(tmp_path/'data'/('lease-'+lease['id']+'.heartbeat.json'),{'at':time.time()}))
    monkeypatch.setattr(runner,'prepared_inputs',lambda p:(p,{}))
    class Process:
        returncode=0
        def __init__(self,*a,**k):client.calls.append('workflow')
        def poll(self):return 0
    monkeypatch.setattr(runner.subprocess,'Popen',Process)
    def run():
        folder=tmp_path/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
        app.save(folder/'execution-plan.json',{'approved_release_id':release,'execution_id':str(uuid.uuid4()),'deadline_seconds':600,'max_credits_reservation':202})
        runner.main(release,folder)
        return folder
    return tmp_path,client,run


def test_create_stop_start_same_deployment_and_accounting(runtime):
    root,client,run=runtime
    first=run();guarded.settle(first)
    second=run();guarded.settle(second)
    assert client.calls==['create','workflow','stop','start','workflow','stop']
    assert app.read(second/'attempt.json')['reused_deployment'] is True
    assert app.read(root/'ledger.json')['conservative_prior_credits']==409
    assert app.read(root/'ledger.json')['unresolved_jobs']==[]


@pytest.mark.parametrize('mode',['ok','missing','over','query_error','policy_error','no_allowance','corrupt_prior'])
def test_first_release_storage_bootstrap(runtime,monkeypatch,mode):
    root,client,run=runtime
    quote_path=root/'config/platform-storage-quote.json'
    quote=app.read(quote_path);quote['release_id']='old-release'
    evidence=root/quote['evidence']
    app.save(evidence,{'releases':[{'current':True,'releaseId':'old-release','storageMonthlyCents':1540}]})
    quote['sha256']=app.sha(evidence.read_bytes());app.save(quote_path,quote)
    prior_bytes=quote_path.read_bytes()
    code=root/'comfy_nodes/stage_audit.py';code.parent.mkdir();code.write_bytes(b'fixture-code')
    config=app.read(root/'config/guarded-runtime.json')
    config.update(release_id=client.release,bootstrap_storage_reservation_credits=10,
                  stage_audit_code_sha256=app.sha(code.read_bytes()))
    if mode=='no_allowance':config.pop('bootstrap_storage_reservation_credits')
    app.save(root/'config/guarded-runtime.json',config)
    if mode=='corrupt_prior':evidence.write_bytes(b'changed')
    original_get=client.get_deployment
    failed=[False]
    def get(did):
        if mode=='query_error' and not failed[0]:
            failed[0]=True
            raise ConnectionError('initial quote unavailable')
        row=original_get(did)
        if mode in ('missing','over') and not row.get('deletedAt'):
            row['releases'][0]['storageMonthlyCents']=None if mode=='missing' else 999999
        return row
    monkeypatch.setattr(client,'get_deployment',get)
    if mode=='policy_error':
        import platform_preflight
        original_policy=platform_preflight.storage_policy
        def policy(*args):
            if client.row is not None:raise OSError('policy read failed after create')
            return original_policy(*args)
        monkeypatch.setattr(platform_preflight,'storage_policy',policy)
    def delete(did):
        client.calls.append('delete')
        client.row.update(status='stopped',releases=[],deletedAt=datetime.now(timezone.utc).isoformat(),
                          serving={'workers':{'running':0,'ready':0}})
        return dict(client.row)
    monkeypatch.setattr(client,'delete_deployment',delete)
    if mode in ('no_allowance','corrupt_prior'):
        with pytest.raises(ValueError):run()
        assert client.calls==[]
    else:
        folder=run()
        if mode=='ok':
            assert client.calls==['create','workflow','stop']
            assert app.read(folder/'bootstrap-storage-verified.json')['reserved_credits']==10
        else:
            assert client.calls==['create','stop','delete']
            assert 'workflow' not in client.calls
            assert app.read(folder/'deployment-final.json')['deletedAt']
        assert next(iter(app.read(root/'ledger.json')['storage_leases'].values()))['reserved_credits']==10
    assert quote_path.read_bytes()==prior_bytes


def test_storage_lease_is_not_extended_or_duplicated(runtime):
    root,client,run=runtime
    first=run();guarded.settle(first);original=app.read(storage_lease.lease_path())
    second=run()
    assert app.read(second/'storage-lease.json')['expires_at']==original['expires_at']
    assert len(app.read(root/'ledger.json')['storage_leases'])==1


def test_expiring_lease_rejects_restart(runtime):
    root,client,run=runtime
    first=run();guarded.settle(first)
    lease=app.read(storage_lease.lease_path());lease['expires_at']=time.time()+600;app.save(storage_lease.lease_path(),lease)
    with pytest.raises(ValueError,match='cleanup pending'):run()
    assert client.calls==['create','workflow','stop']


def test_storage_quote_rejects_changed_evidence(runtime):
    root,client,run=runtime
    assert storage_lease.quote(client.get_compute_catalog(),client.release)==5
    app.save(root/'data/gen/previous/deployment-latest.json',{'bytesTotal':71914405655})
    with pytest.raises(ValueError,match='evidence changed'):
        storage_lease.quote(client.get_compute_catalog(),client.release)


def test_lost_start_response_stops_same_id_without_fallback(runtime):
    root,client,run=runtime;first=run();guarded.settle(first)
    client.fail_start=True;second=run();guarded.settle(second)
    assert client.calls==['create','workflow','stop','start','stop']
    assert app.read(second/'execution-error.json')['type']=='ConnectionError'


@pytest.mark.parametrize('field,value',[('account_sha256','wrong'),('release_id','wrong'),('creation_key','wrong')])
def test_mismatched_pin_fails_before_start(runtime,field,value):
    root,client,run=runtime;first=run();guarded.settle(first)
    pin=app.read(reuse.pin_path(root));pin[field]=value;app.save(reuse.pin_path(root),pin)
    with pytest.raises(ValueError):run()
    assert client.calls==['create','workflow','stop']


def test_stop_failed_or_stale_event_never_settles(runtime):
    root,client,run=runtime;folder=run()
    proof=app.read(folder/'control-plane-stop.json')
    proof['events']['events'][0]['at']='2000-01-01T00:00:00Z';app.save(folder/'control-plane-stop.json',proof)
    with pytest.raises(ValueError,match='stop evidence'):guarded.settle(folder)
    assert app.read(root/'ledger.json')['unresolved_jobs']==[folder.name]
    assert not reuse.stopped_evidence_valid({**proof['snapshot'],'status':'stop_failed'},proof['events'],app.read(folder/'attempt.json'))


def test_unrelated_same_release_is_not_adopted():
    attempt={'release_id':'release','idempotency_key':'own-key'}
    assert reuse.identify_lost_create([{'id':'other','releaseId':'release'}],attempt) is None
    assert reuse.identify_lost_create([{'id':'other','releaseId':'release','idempotencyKey':'other-key'}],attempt) is None


def test_recover_unknown_identity_keeps_reservation(runtime):
    root,client,run=runtime
    folder=root/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    app.save(folder/'attempt.json',{'release_id':client.release,'idempotency_key':'lost-key','retain_models':True})
    app.save(folder/'deployments-before.json',[])
    client.row={'id':'other','releaseId':client.release,'status':'ready'}
    assert runner.recover(folder) is False
    assert client.calls==[] and not (folder/'finished.json').exists()


def test_reused_failed_job_output_recovery(runtime, monkeypatch):
    root,client,run=runtime
    first=run();guarded.settle(first);second=run()
    monkeypatch.setattr(download,'validate_endpoint_origin',lambda did,url: 'https://owned.example' if did=='dep-owned' else pytest.fail('Wrong deployment'))
    monkeypatch.setattr(download,'download_job_outputs',lambda request,renderer: [])
    monkeypatch.setattr(guarded,'key',lambda:'fake-key')
    result=guarded.recover_outputs(second,{'error':{'details':{'job':{'id':'existing-job','outputs':[]}}}})
    assert result['job']['id']=='existing-job'
    assert not (second/'deployment-created.json').exists()
    assert client.calls==['create','workflow','stop','start','workflow','stop']


@pytest.mark.parametrize('fail_delete',[False,True])
def test_supervisor_releases_only_after_verified_delete(runtime,monkeypatch,fail_delete):
    root,client,run=runtime
    folder=run();guarded.settle(folder)
    lease=app.read(storage_lease.lease_path());lease['expires_at']=0;app.save(storage_lease.lease_path(),lease)
    monkeypatch.setattr(storage_lease,'key',lambda:'fake-key')
    def delete(did):
        assert did=='dep-owned'
        if fail_delete:raise ConnectionError('delete unavailable')
        client.row.update(deletedAt=datetime.now(timezone.utc).isoformat(),status='stopped',serving={'workers':{'ready':0}})
    monkeypatch.setattr(client,'delete_deployment',delete)
    def stop_wait(seconds):raise InterruptedError('End one failed cleanup observation')
    monkeypatch.setattr(storage_lease.time,'sleep',stop_wait)
    if fail_delete:
        with pytest.raises(InterruptedError):storage_lease.supervise(lease['id'])
        assert app.read(storage_lease.lease_path())['status']=='reserved'
        assert reuse.pin_path(root).exists()
    else:
        storage_lease.supervise(lease['id'])
        assert app.read(storage_lease.lease_path())['status']=='deleted'
        assert not reuse.pin_path(root).exists()
    assert app.read(root/'ledger.json')['conservative_prior_credits']==207


def test_storage_reservation_cannot_cross_budget(runtime):
    root,client,run=runtime
    app.save(root/'ledger.json',{'conservative_prior_credits':1794,'unresolved_jobs':[],'known_runs':[]})
    with pytest.raises(ValueError,match='reservations exceed'):run()
    assert client.calls==[]


def test_lease_without_created_deployment_cannot_be_reassigned(runtime):
    root,client,run=runtime
    folder=root/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    lease=storage_lease.reserve(folder,'fake-key',client.get_compute_catalog(),client.release,202,0,600)
    storage_lease.launch(lease)
    with pytest.raises(ValueError,match='no bound owned deployment'):run()
    assert client.calls==[]
    assert app.read(storage_lease.lease_path())['origin_run']==folder.name


def test_lost_create_response_persists_verified_identity(runtime,monkeypatch):
    root,client,run=runtime
    create=client.create_deployment
    def lose(release,compute,**kwargs):
        create(release,compute,**kwargs)
        client.row['idempotencyKey']=kwargs['idempotency_key']
        raise ConnectionError('Created but response lost')
    monkeypatch.setattr(client,'create_deployment',lose)
    folder=run()
    assert app.read(folder/'attempt.json')['deployment_id']=='dep-owned'
    assert app.read(folder/'recovered-deployment.json')['id']=='dep-owned'
    assert client.calls==['create','stop']


@pytest.mark.parametrize('reason',['timeout','cancel'])
def test_prepared_startup_failure_stops_without_workflow(runtime,monkeypatch,reason):
    root,client,run=runtime
    clock=[time.time()]
    monkeypatch.setattr(runner.time,'time',lambda:clock[0])
    monkeypatch.setattr(runner.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    create=client.create_deployment
    def interrupted(*args,**kwargs):
        result=create(*args,**kwargs)
        if reason=='timeout':clock[0]+=601
        else:
            for plan in (root/'data/gen').glob('*/execution-plan.json'):
                app.save(plan.parent/'cancel-request.json',{'requested':True})
        return result
    monkeypatch.setattr(client,'create_deployment',interrupted)
    folder=run()
    assert client.calls==['create','stop']
    assert app.read(folder/'execution-error.json')
    assert app.read(folder/'deployment-final.json')['status']=='stopped'


def test_reused_stop_cannot_use_previous_stop_event(runtime):
    root,client,run=runtime;folder=run()
    proof=app.read(folder/'control-plane-stop.json');attempt=app.read(folder/'attempt.json')
    attempt['stop_not_before']=time.time()+1
    assert not reuse.stopped_evidence_valid(proof['snapshot'],proof['events'],attempt)


def test_lifecycle_probe_never_submits_workflow(runtime):
    root,client,run=runtime
    folder=root/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    app.save(folder/'execution-plan.json',{'purpose':'model_reuse_probe','execution_id':str(uuid.uuid4()),'approved_release_id':client.release,'deadline_seconds':600,'max_credits_reservation':202})
    runner.main(client.release,folder,True)
    assert client.calls==['create','stop','start','stop']
    assert app.read(folder/'restart-result.json')['same_deployment'] is True
    assert (folder/'finished.json').exists()


def test_supervisor_start_failure_closes_uncreated_lease(runtime,monkeypatch):
    root,client,run=runtime
    def fail(lease):raise RuntimeError('supervisor launch failed')
    monkeypatch.setattr(storage_lease,'launch',fail)
    with pytest.raises(RuntimeError,match='launch failed'):run()
    assert client.calls==[]
    lease=app.read(storage_lease.lease_path())
    assert lease['status']=='deleted' and lease['closed_reason']=='owner_confirmed_no_create_or_start'


def test_probe_timeout_is_failure_even_when_cleanup_finishes(tmp_path,monkeypatch):
    import run_reuse_probe as probe
    monkeypatch.setattr(probe,'ROOT',tmp_path)
    app.save(tmp_path/'config/guarded-runtime.json',{'release_id':'test'})
    def fail_start(release,folder,mode):app.save(folder/'execution-error.json',{'message':'Deployment startup exceeded600s'})
    monkeypatch.setattr(probe,'main',fail_start);monkeypatch.setattr(probe,'settle',lambda folder:None)
    with pytest.raises(RuntimeError,match='verification failed'):probe.run()


def test_registration_conflict_closes_only_uncreated_owned_lease(runtime,monkeypatch):
    root,client,run=runtime
    original_launch=storage_lease.launch
    def concurrent_reservation(lease):
        original_launch(lease)
        ledger=app.read(root/'ledger.json')
        ledger['unresolved_jobs']=['other-running-job']
        app.save(root/'ledger.json',ledger)
    monkeypatch.setattr(storage_lease,'launch',concurrent_reservation)
    with pytest.raises(RuntimeError,match='reserved concurrently'):run()
    assert client.calls==[]
    lease=app.read(storage_lease.lease_path())
    ledger=app.read(root/'ledger.json')
    assert lease['status']=='deleted'
    assert ledger['unresolved_jobs']==['other-running-job']
    assert ledger['conservative_prior_credits']==5
    folder=root/'data/gen'/lease['origin_run']
    assert (folder/'attempt.json').exists()
    assert (folder/'creation-never-started.json').exists()


@pytest.mark.parametrize('seconds,reservation',[(600,280),(450,210)])
def test_h100_probe_restarts_same_deployment_and_settles(runtime,monkeypatch,seconds,reservation):
    root,client,run=runtime
    original_catalog=client.get_compute_catalog
    def catalog():
        value=original_catalog()
        value['regions'][0]['gpus'].append({'gpuClass':'h100-sxm','creditsPerHour':1314.53})
        return value
    monkeypatch.setattr(client,'get_compute_catalog',catalog)
    folder=root/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    app.save(folder/'execution-plan.json',{'purpose':'model_reuse_probe','gpu_class':'h100-sxm',
        'execution_id':str(uuid.uuid4()),'approved_release_id':client.release,
        'deadline_seconds':seconds,'max_credits_reservation':reservation})
    runner.main(client.release,folder,True)
    guarded.settle(folder)
    assert client.calls==['create','stop','start','stop']
    assert client.row['computeConfig']['gpuClass']=='h100-sxm'
    assert app.read(root/'ledger.json')['conservative_prior_credits']==reservation+5


@pytest.mark.parametrize('purpose,seconds,reservation',[
    ('video',600,280),('model_reuse_probe',600,202),('model_reuse_probe',1200,404),
    ('model_reuse_probe',600,210),('model_reuse_probe',450,202)])
def test_h100_rejects_wrong_purpose_or_reservation(tmp_path,purpose,seconds,reservation):
    app.save(tmp_path/'execution-plan.json',{'purpose':purpose,'gpu_class':'h100-sxm',
        'deadline_seconds':seconds,'max_credits_reservation':reservation})
    with pytest.raises(ValueError,match='restricted'):
        runner.execution_limits(tmp_path,{'max_total_credits':2000})


def test_h100_cannot_execute_as_video(runtime):
    root,client,run=runtime
    folder=root/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    app.save(folder/'execution-plan.json',{'purpose':'model_reuse_probe','gpu_class':'h100-sxm',
        'approved_release_id':client.release,'deadline_seconds':600,'max_credits_reservation':280})
    with pytest.raises(ValueError,match='requires lifecycle probe'):
        runner.main(client.release,folder)
    assert client.calls==[]


@pytest.mark.parametrize('price,wrong_release,allowed',[
    (1439,False,True),(1541,False,False),(None,False,False),
    (True,False,False),(1439,True,False)])
def test_storage_quote_is_a_ceiling_with_cleanup(runtime,monkeypatch,price,wrong_release,allowed):
    root,client,run=runtime
    original_create=client.create_deployment
    def create(*args,**kwargs):
        result=original_create(*args,**kwargs)
        client.row['releases'][0]['storageMonthlyCents']=price
        if wrong_release:client.row['releases'][0]['releaseId']='other-release'
        return result
    def delete(did):
        client.calls.append('delete')
        client.row.update(status='stopped',releases=[],
            deletedAt=datetime.now(timezone.utc).isoformat(),
            serving={'workers':{'running':0,'ready':0}})
        return dict(client.row)
    monkeypatch.setattr(client,'create_deployment',create)
    monkeypatch.setattr(client,'delete_deployment',delete)
    folder=root/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    app.save(folder/'execution-plan.json',{'purpose':'model_reuse_probe',
        'execution_id':str(uuid.uuid4()),'approved_release_id':client.release,
        'deadline_seconds':600,'max_credits_reservation':202})
    runner.main(client.release,folder,True)
    if allowed:
        assert client.calls==['create','stop','start','stop']
        assert (folder/'restart-result.json').exists()
    else:
        assert client.calls==['create','stop','delete']
        assert (folder/'execution-error.json').exists()
        assert app.read(folder/'deployment-final.json')['deletedAt']


@pytest.mark.parametrize('price',[float('nan'),float('inf'),True,None,-1,0])
def test_nonfinite_or_invalid_storage_quote_rejected(price):
    assert not runner.storage_price_within_ceiling(price,1540)

@pytest.mark.parametrize("seconds,reservation,allowed",[(600,280,True),(450,210,False),(600,202,False)])
def test_h100_app_profile(tmp_path,seconds,reservation,allowed):
    app.save(tmp_path/'execution-plan.json',{'purpose':'User-requested guarded generation','gpu_class':'h100-sxm','deadline_seconds':seconds,'max_credits_reservation':reservation})
    if allowed: assert runner.execution_limits(tmp_path,{}) == (600,280)
    else:
        with pytest.raises(ValueError): runner.execution_limits(tmp_path,{})
