import json, sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import run_platform_once as runner

RID='dc0a1bfc-400d-4b91-956b-0684e8a45339'

@pytest.fixture
def harness(tmp_path,monkeypatch):
    (tmp_path/'data/gen').mkdir(parents=True);(tmp_path/'config').mkdir()
    runner.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':2000,'max_deployment_active_minutes':10,'max_storage_charge':2})
    runner.save(tmp_path/'config/guarded-runtime.json',{'build_id':'549af8e0-e768-4854-9d37-beffd0ca7ef8'})
    ledger=tmp_path/'config/ledger.json';runner.save(ledger,{'unresolved_jobs':[],'conservative_prior_credits':77})
    monkeypatch.setattr(runner,'ROOT',tmp_path);monkeypatch.setattr(runner,'LEDGER',ledger);monkeypatch.setattr(runner,'key',lambda:'test-key')
    monkeypatch.setattr(runner,'api',lambda *a:{'summary':{'balance':{'cloud_credit_balance_cents':10000}}})
    monkeypatch.setattr(runner,'cumulative_prior',lambda ledger,*args:ledger['conservative_prior_credits'])
    clock=[1000.0];monkeypatch.setattr(runner.time,'time',lambda:clock[0]);monkeypatch.setattr(runner.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    class Thread:
        def __init__(self,**kwargs):pass
        def start(self):pass
        def join(self,**kwargs):pass
    monkeypatch.setattr(runner.threading,'Thread',Thread)
    class Client:
        created=False;deleted=False;creates=0;deletes=0;stops=0;mode='timeout';fail_delete_once=False
        def snapshot(self):return {'id':'owned','releaseId':RID,'status':'stopped' if self.deleted else 'starting','deletedAt':'now' if self.deleted else None,'serving':{'workers':{'running':0,'idle':0,'initializing':0}}}
        def list_all_deployments(self):return [self.snapshot()] if self.created else []
        def get_deployment(self,*a):return self.snapshot()
        def get_compute_catalog(self):return {'regions':[{'region':'anywhere','gpus':[{'gpuClass':'rtx-pro-6000-server','creditsPerHour':957.94}]}]}
        def get_deploy_estimate(self,*a):return {}
        def create_deployment(self,*a,**k):
            self.creates+=1;self.created=True
            if self.mode=='ambiguous':raise TimeoutError()
            clock[0]+=601
            return self.snapshot()
        def stop_deployment(self,*a):self.stops+=1;return {}
        def delete_deployment(self,*a):
            self.deletes+=1
            if self.fail_delete_once and self.deletes==1:raise TimeoutError()
            self.deleted=True
    c=Client();monkeypatch.setattr(runner.DeployClient,'from_credentials',lambda:c)
    class Builder:
        def get_release(self,*a):return {'id':RID,'buildId':'549af8e0-e768-4854-9d37-beffd0ca7ef8','deployable':True,'artifacts':[{'os':'linux','gpu':'nvidia','status':'ready'}]}
    monkeypatch.setattr(runner.BuilderClient,'from_credentials',lambda *a:Builder())
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:pytest.fail('Generation must not be submitted in these scenarios'))
    return tmp_path,c

@pytest.mark.parametrize('mode', ['timeout', 'ambiguous', 'transient_cleanup'])
def test_missing_prepared_inputs_rejected_before_deployment(harness, mode):
    root,c=harness;c.mode=mode;c.fail_delete_once=mode=='transient_cleanup'
    with pytest.raises(ValueError,match='Explicit prepared input'):
        runner.main(RID)
    assert c.creates==0 and not c.deleted
    assert runner.read(root/'config/ledger.json')['unresolved_jobs']==[]
    assert not (root/'data/gen/t3-platform-once').exists()

def test_recovery_has_no_create_or_generation(harness):
    root,c=harness;c.created=True;c.fail_delete_once=True
    folder=root/'data/gen/t3-platform-once';folder.mkdir()
    runner.save(folder/'attempt.json',{'release_id':RID});runner.save(folder/'deployments-before.json',[])
    runner.recover(folder)
    assert c.creates==0 and c.deleted and c.deletes==2

def test_deletion_requires_zero_workers():
    assert not runner.deletion_confirmed({'deletedAt':'now','status':'stopped'})
    assert not runner.deletion_confirmed({'deletedAt':'now','status':'stopped','serving':{'workers':{'running':1}}})
    assert runner.deletion_confirmed({'deletedAt':'now','status':'stopped','serving':{'workers':{'running':0}}})

def test_recovery_uses_known_id_when_listing_omits_it(harness,monkeypatch):
    root,c=harness;c.created=True
    folder=root/'data/gen/t3-platform-once';folder.mkdir()
    runner.save(folder/'attempt.json',{'release_id':RID});runner.save(folder/'deployments-before.json',[])
    runner.save(folder/'deployment-created.json',{'id':'owned','releaseId':RID})
    monkeypatch.setattr(c,'list_all_deployments',lambda:[])
    runner.recover(folder)
    assert c.creates==0 and c.deleted

def test_actual_create_shape_recovers_from_latest(harness,monkeypatch):
    root,c=harness;c.created=True
    folder=root/'data/gen/t3-platform-once';folder.mkdir()
    runner.save(folder/'attempt.json',{'release_id':RID});runner.save(folder/'deployments-before.json',[])
    runner.save(folder/'deployment-created.json',{'id':'owned','status':'queued'})
    runner.save(folder/'deployment-latest.json',{'id':'owned','releaseId':RID,'status':'provisioning'})
    monkeypatch.setattr(c,'list_all_deployments',lambda:[])
    runner.recover(folder)
    assert c.creates==0 and c.deleted

def test_actual_api_without_worker_counts_requires_correlated_evidence(tmp_path):
    class Client:
        rows=[]
        def get_deployment_events(self,did):return {'deploymentId':did,'events':[{'status':'stopped','releaseId':RID}]}
        def list_all_deployments(self):return self.rows
    c=Client();snapshot={'id':'owned','releaseId':RID,'status':'stopped','deletedAt':'now','releases':[]}
    assert runner.controlplane_deletion_confirmed(c,snapshot,tmp_path)
    c.rows=[{'id':'owned','deletedAt':None}]
    assert not runner.controlplane_deletion_confirmed(c,snapshot,tmp_path)
    c.rows=[];snapshot['serving']={'workers':{'running':1}}
    assert not runner.controlplane_deletion_confirmed(c,snapshot,tmp_path)

@pytest.mark.parametrize('missing',[None,'',False,'   '])
def test_no_prepared_inputs_never_reads_credentials(harness,monkeypatch,missing):
    root,c=harness
    monkeypatch.setattr(runner,'key',lambda:pytest.fail('No input must fail before credentials'))
    with pytest.raises(ValueError,match='Explicit prepared input'):
        runner.main(RID,missing)
    assert c.creates==0
