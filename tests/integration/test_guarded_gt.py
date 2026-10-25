import sys,json,hashlib,shutil
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app,app_guarded,run_platform_once

@pytest.mark.parametrize('selection',['../joints.json','C:/outside/joints.json','joints.observed.json'])
def test_invalid_or_missing_explicit_gt_never_falls_back(tmp_path,selection):
    (tmp_path/'joints.json').write_text('{}')
    app.save(tmp_path/'input.json',{'gt_file':selection})
    with pytest.raises(ValueError):app.selected_gt(tmp_path)

@pytest.mark.parametrize('audited',[False,True])
def test_guarded_prepared_input_uses_actual_observed_gt(tmp_path,monkeypatch,audited):
    original=app.ROOT
    template=original/'workflows/T5/guarded-ltx-local-template.api.json'
    dest=tmp_path/'workflows/T5'/template.name;dest.parent.mkdir(parents=True)
    shutil.copyfile(template,dest)
    app.save(tmp_path/'config/guarded-runtime.json',{'enabled':True,'template_sha256':app.sha(dest.read_bytes()),'release_id':'test-no-submission'})
    if audited:
        audit_source=tmp_path/'comfy_nodes/stage_audit.py'
        audit_source.parent.mkdir(parents=True)
        shutil.copyfile(original/'comfy_nodes/stage_audit.py',audit_source)
        config=app.read(tmp_path/'config/guarded-runtime.json')
        config['stage_audit_code_sha256']=app.sha(audit_source.read_bytes())
        app.save(tmp_path/'config/guarded-runtime.json',config)
    folder=tmp_path/'data/gen'/('t3-'+'a'*32);folder.mkdir(parents=True)
    app.save(folder/'input.json',{'gt_file':'joints.observed.json','prompt':'test'})
    (folder/'joints.json').write_text('{"wrong":"legacy"}')
    observed=original/'tests/fixtures/dance-gt.json'
    shutil.copyfile(observed,folder/'joints.observed.json')
    (folder/'character.png').write_bytes(b'local-validation-only')
    # This fixture tests GT selection and timing, not motion agreement between
    # the dance GT and these existing, fully decodable PickUp input videos.
    video_source=original/'tests/fixtures/prepared-short'
    for name in ('reference.mp4','pose.mp4'):
        shutil.copyfile(video_source/name,folder/name)
    monkeypatch.setattr(app_guarded,'ROOT',tmp_path)
    monkeypatch.setattr(run_platform_once,'ROOT',tmp_path)
    app_guarded.prepare_execution(folder)
    workflow=app.read(folder/'workflow.api.json');plan=app.read(folder/'execution-plan.json')
    from gt_compact import compact
    wire=json.dumps(compact(app.read(observed)),separators=(',',':'))
    assert workflow['mg_inspect']['inputs']['gt_json']==wire==(folder/'joints.observed.json').read_text(encoding='utf-8')
    assert plan['gt_file']=='joints.observed.json'
    assert plan['input_hashes']['joints.observed.json']==app.sha(wire.encode('utf-8'))
    assert 'joints.json' not in plan['input_hashes']
    run_platform_once.prepared_inputs(folder)
    if audited:
        assert workflow['mg_inspect']['inputs']['run_id']==['mg_audit_init',0]
        original_pin=plan['stage_audit']['graph_sha256']
        plan['stage_audit']['graph_sha256']='0'*64
        app.save(folder/'execution-plan.json',plan)
        with pytest.raises(AssertionError):run_platform_once.prepared_inputs(folder)
        plan['stage_audit']['graph_sha256']=original_pin
        app.save(folder/'execution-plan.json',plan)
    (folder/'joints.observed.json').write_text('{}')
    with pytest.raises(ValueError,match='changed'):run_platform_once.prepared_inputs(folder)

def test_result_restoration_preserves_selected_gt(tmp_path,monkeypatch):
    import run_guarded_platform as runner
    folder=tmp_path;observed=folder/'joints.observed.json';observed.write_text('{"observed":true}')
    reference=folder/'reference.mp4';reference.write_bytes(b'reference-input-fixture')
    app.save(folder/'execution-plan.json',{'execution_id':'11111111-1111-4111-8111-111111111111','gt_file':observed.name,'input_hashes':{observed.name:app.sha(observed.read_bytes()),'reference.mp4':app.sha(reference.read_bytes())}})
    app.save(folder/'cli-stdout.txt',{'ok':True,'data':{'job':{'id':'test','status':'succeeded'},'outputs':[]}})
    app.save(folder/'cli-exit.json',{'returncode':0})
    def restored(folder,outputs,execution,submitted,publish_success):
        assert submitted['gt']=={'path':str(observed),'sha256':app.sha(observed.read_bytes())}
        return {'verdict':'FAIL'}
    monkeypatch.setattr(runner,'restore',restored)
    result=runner.finish_outputs(folder)
    assert result['guard_verdict']=='FAIL'
    assert app.read(folder/'state.json')['downstream_status']=='held'
    assert app.read(folder/'state.json')['final_available'] is False

@pytest.mark.parametrize('name',['joints.json','joints.observed.json'])
def test_restore_maps_actual_submitted_gt(tmp_path,name):
    from import_platform_guard import mapped_gt_name
    assert mapped_gt_name(tmp_path,{'gt':{'path':str(tmp_path/name)}})==name
    with pytest.raises(ValueError):mapped_gt_name(tmp_path,{'gt':{'path':str(tmp_path.parent/name)}})
