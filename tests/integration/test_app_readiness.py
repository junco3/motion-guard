import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app
from platform_preflight import preview

def setup(root):
    def put(name,value):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value));return p
    evidence=put('data/gen/example/quote.json',{'releases':[{'current':True,'releaseId':'r','storageMonthlyCents':1540}]})
    put('config/platform-storage-quote.json',{'release_id':'r','evidence':'data/gen/example/quote.json',
        'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),'storage_monthly_cents':1540,
        'credits_per_cent':2.11,'catalog_credits_per_gb_month':42.2})
    graph=put('workflows/T5/guarded-ltx-local-template.api.json',{})
    config={'enabled':True,'release_id':'r','build_id':'b','template_sha256':hashlib.sha256(graph.read_bytes()).hexdigest()}
    put('config/guarded-runtime.json',config)
    put('config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':2000})
    return put,config

@pytest.mark.parametrize('remaining,allowed',[(202,False),(206,False),(207,True)])
def test_policy_includes_new_storage_before_accepting_input(tmp_path,monkeypatch,remaining,allowed):
    put,config=setup(tmp_path)
    ledger=put('config/ledger.json',{'conservative_prior_credits':2000-remaining,'unresolved_jobs':[]})
    monkeypatch.setattr(app,'ROOT',tmp_path);monkeypatch.setattr(app,'LEDGER',ledger)
    before=ledger.read_bytes()
    result=app.generation_policy('platform_guarded')
    assert result['required_reservation']==207
    assert result['generation_allowed'] is allowed
    assert ledger.read_bytes()==before

def test_missing_quote_and_expired_lease_fail_before_preparation(tmp_path):
    put,config=setup(tmp_path)
    quote=tmp_path/'config/platform-storage-quote.json'
    original=quote.read_bytes();quote.unlink()
    assert preview(tmp_path,config,100)['ready'] is False
    quote.write_bytes(original)
    put('data/platform-storage-lease.json',{'id':'x','origin_run':'run','status':'reserved',
        'account_sha256':'account','expires_at':700})
    put('data/platform-deployment.json',{'origin_run':'run','deployment_id':'dep',
        'account_sha256':'account','release_id':'r','build_id':'b',
        'compute':{'gpuClass':'rtx-pro-6000-server','region':'anywhere','min':0,'max':1}})
    put('data/lease-x.heartbeat.json',{'at':100})
    assert preview(tmp_path,config,100)['ready'] is False
    put('data/platform-storage-lease.json',{'id':'x','origin_run':'run','status':'reserved',
        'account_sha256':'account','expires_at':1000})
    assert preview(tmp_path,config,100)['required_reservation']==202
    assert preview(tmp_path,config,130)['ready'] is False

def test_failed_run_draft_is_available_only_with_unchanged_sources(tmp_path):
    app.save(tmp_path/'state.json',{'status':'failed','source_type':'platform_guarded','guard_status':'complete'})
    pins={}
    for role in ('reference','generated'):
        p=tmp_path/(role+'.mp4');p.write_bytes(role.encode())
        pins[role]={'path':str(p),'sha256':app.sha(p.read_bytes())}
    app.save(tmp_path/'guard-inputs.json',pins)
    (tmp_path/'comparison.mp4').write_bytes(b'comparison')
    assert app.job_view(tmp_path)['status']=='failed'
    assert app.job_view(tmp_path)['draft_available'] is True
    (tmp_path/'generated.mp4').write_bytes(b'changed')
    assert app.job_view(tmp_path)['draft_available'] is False

def test_guard_error_does_not_hide_independently_verified_draft(tmp_path):
    app.save(tmp_path/'state.json',{'status':'failed','source_type':'platform_guarded','guard_status':'error'})
    app.save(tmp_path/'execution-plan.json',{'execution_id':'job'})
    for role in ('reference','generated'):(tmp_path/(role+'.mp4')).write_bytes(role.encode())
    app.save(tmp_path/'draft-result.json',{'execution_id':'job',
        'reference_sha256':app.sha(b'reference'),'generated_sha256':app.sha(b'generated')})
    state=app.job_view(tmp_path)
    assert state['status']=='failed' and state['guard_status']=='error'
    assert state['draft_available'] is True and state['draft_comparison_available'] is False

def test_preserve_actual_existing_video_without_guard_report(tmp_path):
    import shutil
    from import_platform_guard import preserve_draft
    samples=Path(__file__).resolve().parents[2]/'public_samples'
    (tmp_path/'outputs').mkdir()
    shutil.copyfile(samples/'reference.mp4',tmp_path/'reference.mp4')
    shutil.copyfile(samples/'generated.mp4',tmp_path/'outputs/generated.mp4')
    execution='11111111-1111-4111-8111-111111111111'
    assert preserve_draft(tmp_path,[{'node_id':'mg_inspect','name':'generated.mp4','type':'video',
        'path':str(tmp_path/'outputs/generated.mp4')}],execution,
        {'reference':{'sha256':app.sha((tmp_path/'reference.mp4').read_bytes())}})
    evidence=app.read(tmp_path/'draft-result.json')
    assert evidence['frames']==97 and evidence['fps']==24
    assert evidence['generated_sha256']==app.sha((samples/'generated.mp4').read_bytes())

@pytest.mark.parametrize("gpu,cost",[("h100-sxm",285),("rtx-pro-6000-server",207)])
def test_profile_preview(tmp_path,gpu,cost):
    put,config=setup(tmp_path)
    config['gpu_class']=gpu
    assert preview(tmp_path,config)['required_reservation']==cost

def test_invalid_profile(tmp_path):
    put,config=setup(tmp_path)
    config['gpu_class']='other'
    assert not preview(tmp_path,config)['ready']


def test_preserve_layout_diag_draft_and_reject_ambiguity(tmp_path):
    import cv2
    import numpy as np
    import shutil
    from import_platform_guard import preserve_draft
    (tmp_path/'outputs').mkdir()
    ref=tmp_path/'reference.mp4'
    writer=cv2.VideoWriter(str(ref),cv2.VideoWriter_fourcc(*'mp4v'),24,(960,544))
    for _ in range(9):writer.write(np.zeros((544,960,3),np.uint8))
    writer.release()
    target=tmp_path/'outputs/draft.mp4';shutil.copyfile(ref,target)
    row={'node_id':'diag_save','type':'video','name':'draft.mp4','path':str(target)}
    execution='11111111-1111-4111-8111-111111111111'
    sources={'reference':{'sha256':app.sha(ref.read_bytes())}}
    assert preserve_draft(tmp_path,[row],execution,sources)
    record=app.read(tmp_path/'draft-result.json')
    assert record['size']==[960,544] and record['source_node']=='diag_save'
    with pytest.raises(ValueError,match='Ambiguous'):
        preserve_draft(tmp_path,[row,row],execution,sources)
    writer=cv2.VideoWriter(str(ref),cv2.VideoWriter_fourcc(*'mp4v'),24,(768,512))
    for _ in range(9):writer.write(np.zeros((512,768,3),np.uint8))
    writer.release()
    sources={'reference':{'sha256':app.sha(ref.read_bytes())}}
    with pytest.raises(ValueError,match='timeline invalid'):
        preserve_draft(tmp_path,[row],execution,sources)
