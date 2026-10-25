import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
import platform_cli
from comfy_cli.command import deploy_run


def setup_journal(monkeypatch, tmp_path, **mock_args):
    (tmp_path/'execution-plan.json').write_text(json.dumps({'approved_release_id':'release'}))
    monkeypatch.setattr(deploy_run, '_terminal_result', deploy_run._terminal_result)
    original = Mock(**mock_args)
    monkeypatch.setattr(deploy_run.DeployJobClient, 'submit_job', original)
    platform_cli.install_journal(tmp_path)
    return original, SimpleNamespace(deployment_id='dep-test', idempotency_key='attempt-test')


def test_terminal_journal_precedes_download_and_drops_urls(monkeypatch,tmp_path):
    original, request=setup_journal(monkeypatch,tmp_path,return_value={'id':'job-test'})
    object.__new__(deploy_run.DeployJobClient).submit_job(request,'control')
    deploy_run._terminal_result({'id':'job-test','deployment_id':'dep-test','release_id':'release','status':'succeeded','token':'SECRET',
        'outputs':[{'id':'output','job_id':'job-test','name':'generated.mp4','url':'SECRET','hash':'blake3:abc'}]})
    recorded=json.loads((tmp_path/'job-terminal.json').read_text())
    assert recorded['status']=='succeeded' and recorded['outputs']==[{'id':'output','job_id':'job-test','name':'generated.mp4','hash':'blake3:abc'}]
    assert 'SECRET' not in (tmp_path/'job-terminal.json').read_text()
    assert original.call_count==1


@pytest.mark.parametrize('job',[{'id':'other','status':'succeeded'},{'id':'job-test','status':'running'}])
def test_terminal_journal_refuses_wrong_identity_or_nonterminal(monkeypatch,tmp_path,job):
    _,request=setup_journal(monkeypatch,tmp_path,return_value={'id':'job-test'})
    object.__new__(deploy_run.DeployJobClient).submit_job(request,'control')
    with pytest.raises(RuntimeError):deploy_run._terminal_result(job)
    assert not (tmp_path/'job-terminal.json').exists()


def test_cli_binding_records_identity_before_wait_and_filters_secrets(monkeypatch, tmp_path):
    response = {'id':'job-test', 'token':'SECRET', 'outputs':[{'url':'SECRET'}]}
    original, request = setup_journal(monkeypatch,tmp_path,return_value=response)
    client = object.__new__(deploy_run.DeployJobClient)
    assert client.submit_job(request, 'control') is response
    original.assert_called_once_with(client, request, 'control')
    assert json.loads((tmp_path/'job-submitted.json').read_text()) == {
        'deployment_id':'dep-test', 'job_id':'job-test'}
    assert 'SECRET' not in ''.join(p.read_text() for p in tmp_path.iterdir())
    # Subsequent watch interruption cannot erase the already-published identity.
    with pytest.raises(KeyboardInterrupt):
        raise KeyboardInterrupt()
    assert (tmp_path/'job-submitted.json').exists()
    with pytest.raises(FileExistsError):
        client.submit_job(request, 'control')
    assert original.call_count == 1


def test_pre_submit_write_failure_blocks_submission(monkeypatch,tmp_path):
    original, request = setup_journal(monkeypatch,tmp_path)
    monkeypatch.setattr(platform_cli,'record_once',Mock(side_effect=OSError('disk')))
    with pytest.raises(OSError):
        object.__new__(deploy_run.DeployJobClient).submit_job(request,'control')
    original.assert_not_called()


def test_submit_exception_is_preserved_without_retry(monkeypatch,tmp_path):
    error = RuntimeError('submit unavailable')
    original, request = setup_journal(monkeypatch,tmp_path,side_effect=error)
    with pytest.raises(RuntimeError) as caught:
        object.__new__(deploy_run.DeployJobClient).submit_job(request,'control')
    assert caught.value is error
    assert original.call_count == 1
    assert json.loads((tmp_path/'job-submit-started.json').read_text())['remote_outcome']=='unconfirmed'


def test_post_submit_write_failure_keeps_unknown_outcome(monkeypatch,tmp_path):
    original, request = setup_journal(monkeypatch,tmp_path,return_value={'id':'job-test'})
    write = platform_cli.record_once
    def fail_response(path,value):
        if path.name=='job-submitted.json': raise OSError('disk')
        write(path,value)
    monkeypatch.setattr(platform_cli,'record_once',fail_response)
    with pytest.raises(OSError):
        object.__new__(deploy_run.DeployJobClient).submit_job(request,'control')
    assert original.call_count==1
    assert (tmp_path/'job-submit-started.json').exists()
    assert not (tmp_path/'job-submitted.json').exists()


def test_unknown_response_shape_is_not_recorded_as_success(monkeypatch,tmp_path):
    original, request = setup_journal(monkeypatch,tmp_path,return_value={})
    with pytest.raises(RuntimeError,match='remote outcome unconfirmed'):
        object.__new__(deploy_run.DeployJobClient).submit_job(request,'control')
    assert original.call_count==1
    assert not (tmp_path/'job-submitted.json').exists()


def test_full_cli_orchestration_journals_before_interrupted_watch(monkeypatch,tmp_path):
    response={'id':'job-test','status':'queued'}
    original, _ = setup_journal(monkeypatch,tmp_path,return_value=response)
    control=SimpleNamespace(target=SimpleNamespace(api_key='SECRET'),
        get_deployment=lambda _: {'status':'ready','endpointUrl':'https://example.invalid'})
    monkeypatch.setattr(deploy_run,'RunControlClient',SimpleNamespace)
    monkeypatch.setattr(deploy_run,'get_renderer',Mock())
    monkeypatch.setattr(deploy_run,'require_option',lambda *a,**k:'workflow.json')
    monkeypatch.setattr(deploy_run,'resolve_asset_roots',lambda *a,**k:())
    monkeypatch.setattr(deploy_run,'load_deploy_workflow',lambda *a,**k:None)
    monkeypatch.setattr(deploy_run,'_command_clients',lambda:(None,control))
    monkeypatch.setattr(deploy_run,'resolve_deployment_id',lambda *a:'dep-test')
    monkeypatch.setattr(deploy_run,'validate_endpoint_origin',lambda *a:'https://example.invalid')
    monkeypatch.setattr(deploy_run,'resolve_assets',lambda *a:SimpleNamespace(workflow={}))
    monkeypatch.setattr(deploy_run,'_job_link',lambda *a:'https://example.invalid/job')
    class InterruptedWatch(BaseException): pass
    def interrupted(*a):
        assert json.loads((tmp_path/'job-submitted.json').read_text())['job_id']=='job-test'
        raise InterruptedWatch()
    monkeypatch.setattr(deploy_run,'_watch_with_timeout',interrupted)
    from typer.testing import CliRunner
    from comfy_cli.command.deploy import app as deploy_app
    with pytest.raises(InterruptedWatch):
        CliRunner().invoke(deploy_app, ['run', '--workflow', 'workflow.json',
            '--deployment', 'dep-test', '--timeout', '10', '--output-dir', str(tmp_path)])
    assert original.call_count==1

@pytest.mark.parametrize('timeout_args',[[],['--timeout','10']])
def test_real_cli_watch_paths_journal_before_download_interrupt(monkeypatch,tmp_path,timeout_args):
    response={'id':'job-test','status':'queued'}
    original,_=setup_journal(monkeypatch,tmp_path,return_value=response)
    control=SimpleNamespace(target=SimpleNamespace(api_key='SECRET'),get_deployment=lambda _: {'status':'ready','endpointUrl':'https://example.invalid'})
    monkeypatch.setattr(deploy_run,'RunControlClient',SimpleNamespace)
    monkeypatch.setattr(deploy_run,'get_renderer',Mock())
    monkeypatch.setattr(deploy_run,'require_option',lambda *a,**k:'workflow.json')
    monkeypatch.setattr(deploy_run,'resolve_asset_roots',lambda *a,**k:())
    monkeypatch.setattr(deploy_run,'load_deploy_workflow',lambda *a,**k:None)
    monkeypatch.setattr(deploy_run,'_command_clients',lambda:(None,control))
    monkeypatch.setattr(deploy_run,'resolve_deployment_id',lambda *a:'dep-test')
    monkeypatch.setattr(deploy_run,'validate_endpoint_origin',lambda *a:'https://example.invalid')
    monkeypatch.setattr(deploy_run,'resolve_assets',lambda *a:SimpleNamespace(workflow={}))
    monkeypatch.setattr(deploy_run,'_job_link',lambda *a:'https://example.invalid/job')
    watched=SimpleNamespace(job={'id':'job-test','status':'succeeded','deployment_id':'dep-test','release_id':'release','outputs':[]},outputs=[])
    monkeypatch.setattr(deploy_run,'watch_job',lambda *a:watched)
    monkeypatch.setattr(deploy_run,'_watch_with_timeout',lambda *a:watched)
    class DownloadInterrupted(BaseException):pass
    def interrupted(*a):
        assert json.loads((tmp_path/'job-terminal.json').read_text())['status']=='succeeded'
        raise DownloadInterrupted()
    monkeypatch.setattr(deploy_run,'download_job_outputs',interrupted)
    from typer.testing import CliRunner
    from comfy_cli.command.deploy import app as deploy_app
    with pytest.raises(DownloadInterrupted):
        CliRunner().invoke(deploy_app,['run','--workflow','workflow.json','--deployment','dep-test','--output-dir',str(tmp_path)]+timeout_args)
    assert original.call_count==1
