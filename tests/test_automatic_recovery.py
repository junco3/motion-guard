import json
import sys
import subprocess
from pathlib import Path
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import recover_platform_result as recovery
import run_guarded_platform as runner
from import_platform_guard import save


@pytest.fixture
def case(tmp_path,monkeypatch):
    p=tmp_path/'run';p.mkdir()
    ledger=tmp_path/'ledger.json';monkeypatch.setattr(recovery,'LEDGER',ledger)
    for name,value in {
        'execution-plan.json':{'execution_id':'execution','approved_release_id':'release'},
        'attempt.json':{'deployment_id':'dep-test','release_id':'release'},
        'deployment-final.json':{'id':'dep-test','releaseId':'release','status':'stopped','endpointUrl':'https://dep-test.run.comfy.app'},
        'job-submitted.json':{'deployment_id':'dep-test','job_id':'job-test'},
        'finished.json':{},'state.json':{'status':'running'},
        'execution-error.json':{'type':'TimeoutError','message':'CLI deadline'},
        'cli-exit.json':{'returncode':1,'deadline_terminated':True}
    }.items():save(p/name,value)
    save(ledger,{'guarded_settlements':{'execution':{'run_id':'run','deployment_id':'dep-test'}},'unresolved_jobs':[]})
    return p


@pytest.mark.parametrize('name,field,value',[
    ('deployment-final.json','status','running'),('deployment-final.json','releaseId','wrong'),
    ('job-submitted.json','deployment_id','wrong')])
def test_recovery_cannot_start_before_cleanup_or_for_other_execution(case,name,field,value):
    row=json.loads((case/name).read_text());row[field]=value;save(case/name,row)
    with pytest.raises(ValueError):recovery.context(case)


def test_empty_stdout_recovers_after_cleanup_without_changing_cli_history(case,monkeypatch):
    process=Mock();monkeypatch.setattr(runner.subprocess,'run',process)
    finish=Mock(return_value={'restored':True});monkeypatch.setattr(runner,'finish_outputs',finish)
    assert runner.finish_or_explain(case)=={'restored':True}
    assert process.call_args.kwargs['timeout']==120
    finish.assert_called_once_with(case,recovered=True)
    assert json.loads((case/'cli-exit.json').read_text())['returncode']==1
    assert (case/'execution-error.json').exists()
    # Durable attempt marker prevents a repeated recovery process.
    runner.finish_or_explain(case)
    assert process.call_count==1


def test_recovery_timeout_keeps_original_error_and_no_success(case,monkeypatch):
    monkeypatch.setattr(runner.subprocess,'run',Mock(side_effect=subprocess.TimeoutExpired('recovery',120)))
    finish=Mock();monkeypatch.setattr(runner,'finish_outputs',finish)
    result=runner.finish_or_explain(case)
    assert result['status']=='failed' and result['generation_status']=='unconfirmed'
    assert result['error']=='CLI deadline'
    finish.assert_not_called()


@pytest.mark.parametrize('job',[{'id':'other','status':'succeeded'},{'id':'job-test','status':'running'}])
def test_get_cannot_download_wrong_or_unfinished_job(case,monkeypatch,job):
    import comfy_cli.http as http
    import comfy_cli.deploy_download as download
    monkeypatch.setattr(recovery,'key',lambda:'test')
    monkeypatch.setattr(http,'request_json',lambda *a,**k:(200,job))
    fetch=Mock();monkeypatch.setattr(download,'download_job_outputs',fetch)
    with pytest.raises(ValueError):recovery.recover(case)
    fetch.assert_not_called();assert not (case/'automatic-recovery.json').exists()

@pytest.mark.parametrize('stdout',['', '{"ok":false,"error":{"code":"download_failed"}}', '{"ok":'])
def test_all_interrupted_download_envelopes_recover_once(case,monkeypatch,stdout):
    (case/'cli-stdout.txt').write_text(stdout)
    def process(*a,**k):save(case/'automatic-recovery.json',{'test':'fixture'})
    mock=Mock(side_effect=process);monkeypatch.setattr(runner.subprocess,'run',mock)
    def finish(folder,recovered=False):
        assert recovered
        save(folder/'state.json',{'status':'succeeded','generation_status':'recovered'})
        return {'restored':True}
    monkeypatch.setattr(runner,'finish_outputs',finish)
    assert runner.finish_or_explain(case)=={'restored':True}
    assert runner.finish_or_explain(case)=={'restored':True}
    assert mock.call_count==1 and json.loads((case/'state.json').read_text())['status']=='succeeded'
    assert json.loads((case/'cli-exit.json').read_text())['returncode']==1

@pytest.mark.parametrize('field,value',[('deployment_id','wrong'),('release_id','wrong'),('outputs',[{'job_id':'wrong'}])])
def test_get_rejects_cross_deployment_release_and_output(case,monkeypatch,field,value):
    import comfy_cli.http as http
    import comfy_cli.deploy_download as download
    job={'id':'job-test','status':'succeeded','deployment_id':'dep-test','release_id':'release','outputs':[]}
    job[field]=value
    monkeypatch.setattr(recovery,'key',lambda:'test')
    monkeypatch.setattr(http,'request_json',lambda *a,**k:(200,job))
    fetch=Mock();monkeypatch.setattr(download,'download_job_outputs',fetch)
    with pytest.raises(ValueError):recovery.recover(case)
    fetch.assert_not_called()
