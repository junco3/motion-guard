import hashlib
import json
import sys
import types
import uuid
from pathlib import Path
import pytest
from comfy_nodes import stage_audit as audit

@pytest.fixture
def initialized(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    run=str(uuid.uuid4())
    audit.MG_InitStageAudit().initialize(run,'a'*64)
    sources={}
    for role in ('reference','generated','gt'):
        p=tmp_path/role;p.write_bytes(role.encode())
        sources[role]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    report={'schema_version':'mg-report-2','verdict':'PASS','failures':[],
            'uncertain_reasons':[],'metrics':{'observed':True},'sources':sources}
    envelope={'report':report,'stage_context':{'stage_id':run,'sources':sources,'timeline':{'frames':97,'fps':24}}}
    return run,envelope

def test_actual_delegate_entry_order_and_fail_closed_logging(initialized,monkeypatch):
    run,_=initialized;called=[]
    assert audit.invoke(run,'upsampler',lambda **kw:called.append(kw) or 'result',samples=3)=='result'
    assert called==[{'samples':3}]
    rows=[json.loads(x) for x in (audit.directory(run)/'events.jsonl').read_text().splitlines()]
    assert [x['event'] for x in rows]==['initialized','entered','completed']
    monkeypatch.setattr(audit,'durable',lambda *a,**k:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):audit.invoke(run,'sampler',lambda:called.append('bad'))
    assert len(called)==1

@pytest.mark.parametrize('verdict',['FAIL','UNCERTAIN','ERROR'])
def test_nonpass_does_not_request_real_stage2(initialized,verdict):
    run,envelope=initialized;envelope['report']['verdict']=verdict
    if verdict=='FAIL':envelope['report']['failures']=[{'type':'motion_omission','frames':[24,47],'t_start_s':1,'t_end_s':2,'evidence':{}}]
    node=audit.MG_FinalizeStage()
    assert node.check_lazy_status(envelope,run)==[]
    result=node.finalize(envelope,run)
    assert result['ui']['images'][0]['filename']=='stage-audit.png'
    value=json.loads((audit.directory(run)/'audit.json').read_text())
    assert value['held'] and value['entered']==value['completed']==[]

def test_absence_or_wrong_identity_is_never_zero(initialized):
    run,envelope=initialized
    with pytest.raises(FileNotFoundError):audit.MG_FinalizeStage().check_lazy_status(envelope,str(uuid.uuid4()))
    (audit.directory(run)/'events.jsonl').unlink()
    with pytest.raises(ValueError):audit.MG_FinalizeStage().finalize(envelope,run)

def test_pass_requests_video_and_rejects_unrecorded_execution(initialized):
    run,envelope=initialized;node=audit.MG_FinalizeStage()
    assert node.check_lazy_status(envelope,run)==['video']
    with pytest.raises(ValueError):node.finalize(envelope,run,object())

def test_held_after_real_entry_is_rejected(initialized):
    run,envelope=initialized;envelope['report']['verdict']='FAIL'
    audit.invoke(run,'upsampler',lambda:None)
    with pytest.raises(ValueError):audit.MG_FinalizeStage().finalize(envelope,run)

def test_duplicate_run_cannot_reinitialize(initialized):
    run,_=initialized
    with pytest.raises(FileExistsError):audit.MG_InitStageAudit().initialize(run,'a'*64)
