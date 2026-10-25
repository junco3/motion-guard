import sys,hashlib
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app,run_platform_once as runner

def test_default_does_not_expand(tmp_path):
    assert runner.execution_limits(tmp_path,{'max_total_credits':2000})==(600,202)

def test_one_run_approval_hash_identity_and_limits(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    folder=tmp_path/'data/gen/t3-test';folder.mkdir(parents=True)
    plan={'execution_id':'test','deadline_seconds':1200,'max_credits_reservation':404}
    app.save(folder/'execution-plan.json',plan)
    budget={'max_total_credits':2000}
    with pytest.raises(FileNotFoundError):runner.execution_limits(folder,budget)
    approval={'run_id':folder.name,'execution_id':'test','deadline_seconds':1200,'reservation':404,'cumulative_ceiling':2000,'plan_sha256':app.sha((folder/'execution-plan.json').read_bytes()),'user_quote':'delegated operating decision','scope':'single_guarded_execution'}
    path=tmp_path/'config/guarded-one-run-approval.json';app.save(path,approval)
    assert runner.execution_limits(folder,budget)==(1200,404)
    for field,bad in [('run_id','another'),('plan_sha256','changed'),('reservation',405),('cumulative_ceiling',3000)]:
        app.save(path,{**approval,field:bad})
        with pytest.raises(ValueError):runner.execution_limits(folder,budget)
    app.save(path,approval)
    app.save(folder/'execution-plan.json',{**plan,'deadline_seconds':1800})
    with pytest.raises(ValueError):runner.execution_limits(folder,budget)

@pytest.mark.parametrize('seconds,reservation',[(600,202),(1200,404)])
def test_main_serializes_numeric_reservation_with_released_files(tmp_path,monkeypatch,seconds,reservation):
    from types import SimpleNamespace
    import json,uuid
    monkeypatch.setattr(runner,'ROOT',tmp_path);monkeypatch.setattr(runner,'LEDGER',tmp_path/'ledger.json')
    folder=tmp_path/'data/gen/new';folder.mkdir(parents=True)
    app.save(tmp_path/'data/gen/old/reservation.json',{'released':True})
    app.save(tmp_path/'ledger.json',{'unresolved_jobs':[],'conservative_prior_credits':1042.667958})
    app.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':2000,'max_deployment_active_minutes':40,'max_storage_charge':2})
    build=str(uuid.uuid4());app.save(tmp_path/'config/guarded-runtime.json',{'build_id':build})
    release=str(uuid.uuid4());app.save(folder/'execution-plan.json',{'approved_release_id':release})
    monkeypatch.setattr(runner,'prepared_inputs',lambda p:(folder,{}))
    monkeypatch.setattr(runner,'execution_limits',lambda p,b:(seconds,reservation))
    monkeypatch.setattr(runner.storage_lease,'ensure_existing',lambda *a:None)
    monkeypatch.setattr(runner.storage_lease,'reserve',lambda *a:{'id':'test-lease','expires_at':runner.time.time()+1800})
    monkeypatch.setattr(runner.storage_lease,'launch',lambda *a:None)
    monkeypatch.setattr(runner,'key',lambda:'local-fake')
    monkeypatch.setattr(runner,'api',lambda *a:{'summary':{'balance':{'cloud_credit_balance_cents':10000}}})
    monkeypatch.setattr(runner,'cumulative_prior',lambda *a:1042.667958)
    client=SimpleNamespace(list_all_deployments=lambda:[],get_compute_catalog=lambda:{'regions':[{'region':'anywhere','gpus':[{'gpuClass':'rtx-pro-6000-server','creditsPerHour':957.94}]}]},get_deploy_estimate=lambda *a:{})
    monkeypatch.setattr(runner.DeployClient,'from_credentials',lambda:client)
    builder=SimpleNamespace(get_release=lambda r:{'id':r,'buildId':build,'deployable':True,'artifacts':[{'os':'linux','gpu':'nvidia','status':'ready'}]})
    monkeypatch.setattr(runner.BuilderClient,'from_credentials',lambda *a:builder)
    original=json.dump
    class Serialized(Exception):pass
    def capture(value,stream,*args,**kwargs):
        original(value,stream,*args,**kwargs)
        if 'reserved_credits' in value:raise Serialized()
    monkeypatch.setattr(runner.json,'dump',capture)
    with pytest.raises(Serialized):runner.main(release,folder)
    actual=app.read(folder/'attempt.json')
    assert type(actual['reserved_credits']) is int and actual['reserved_credits']==reservation
    assert actual['deadline']-actual['started_at']==seconds

def test_unconfigured_platform_build_fails_before_credentials(tmp_path,monkeypatch):
    import uuid
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    app.save(tmp_path/'config/guarded-runtime.json',{'build_id':None})
    monkeypatch.setattr(runner,'key',lambda:pytest.fail('Credential access before configuration'))
    with pytest.raises(ValueError,match='account-owned'):runner.main(str(uuid.uuid4()))
