import hashlib
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from layout_claim import completed_claim


def fixture(root):
    run='t3-'+'a'*32
    folder=root/'data/gen'/run
    folder.mkdir(parents=True)
    def put(name,value):
        (folder/name).write_text(json.dumps(value),encoding='utf-8')
    put('execution-plan.json',{'execution_id':'execution'})
    put('state.json',{'status':'succeeded'})
    put('finished.json',{'at':2})
    put('attempt.json',{'release_id':'release','deployment_id':'deployment','started_at':0,'retain_models':True})
    final={'id':'deployment','releaseId':'release','status':'stopped'}
    put('deployment-final.json',final)
    put('control-plane-stop.json',{'snapshot':final,'events':{'deploymentId':'deployment','events':[{'status':'stopped','releaseId':'release','at':'2026-01-01T00:00:00Z'}]}})
    config={'enabled':True,'release_id':'release','claimed_run':run,'claimed_execution_id':'execution',
            'claimed_plan_sha256':hashlib.sha256((folder/'execution-plan.json').read_bytes()).hexdigest()}
    ledger={'known_runs':[run],'unresolved_jobs':[],'guarded_settlements':{'execution':{'run_id':run,'deployment_id':'deployment'}}}
    return folder,config,ledger,put


def test_settled_claim_allows_next_explicit_job_without_mutation(tmp_path):
    folder,config,ledger,put=fixture(tmp_path)
    before=json.dumps([config,ledger])
    assert completed_claim(tmp_path,config,ledger)
    assert json.dumps([config,ledger])==before


@pytest.mark.parametrize('missing',['running','unsettled','unfinished','cleanup','hash'])
def test_previous_job_must_be_finished_settled_and_cleaned(tmp_path,missing):
    folder,config,ledger,put=fixture(tmp_path)
    if missing=='running':put('state.json',{'status':'running'})
    elif missing=='unsettled':ledger['guarded_settlements']={}
    elif missing=='unfinished':(folder/'finished.json').unlink()
    elif missing=='cleanup':put('control-plane-stop.json',{'snapshot':{},'events':{}})
    else:config['claimed_plan_sha256']='wrong'
    assert not completed_claim(tmp_path,config,ledger)


def test_same_folder_cannot_be_prepared_again(tmp_path,monkeypatch):
    import app_layout
    folder,config,ledger,put=fixture(tmp_path)
    (tmp_path/'config').mkdir()
    cp=tmp_path/'config/layout-runtime.json';cp.write_text(json.dumps(config))
    lp=tmp_path/'config/ledger.json';lp.write_text(json.dumps(ledger))
    monkeypatch.setattr(app_layout,'ROOT',tmp_path)
    monkeypatch.setattr(app_layout,'LEDGER',lp)
    before=cp.read_bytes()
    with pytest.raises(ValueError,match='Existing execution'):
        app_layout.prepare_execution(folder)
    assert cp.read_bytes()==before


@pytest.mark.parametrize('mismatch',[False,True])
def test_retained_then_deleted_deployment(tmp_path,mismatch):
    folder,config,ledger,put=fixture(tmp_path)
    final={'id':'deployment','releaseId':'release','status':'stopped','deletedAt':'2026-01-01T00:01:00Z','releases':[]}
    put('deployment-final.json',final)
    put('control-plane-deletion.json',{'snapshot':{} if mismatch else final,
        'events':{'deploymentId':'deployment','events':[{'status':'stopped','releaseId':'release','at':'2026-01-01T00:00:00Z'}]},'deployments':[]})
    assert completed_claim(tmp_path,config,ledger) is not mismatch


@pytest.mark.parametrize('field',['deployment_id','release_id'])
def test_cleanup_must_match_actual_attempt(tmp_path,field):
    folder,config,ledger,put=fixture(tmp_path)
    attempt=json.loads((folder/'attempt.json').read_text())
    attempt[field]='other'
    put('attempt.json',attempt)
    assert not completed_claim(tmp_path,config,ledger)
