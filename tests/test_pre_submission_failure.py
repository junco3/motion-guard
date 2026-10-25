import json
import sys
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import run_guarded_platform as runner


def test_diagnostic_failure_preserves_primary_execution_error(tmp_path):
    from run_platform_once import capture_deployment_logs
    original = b'{"type":"TimeoutError","message":"Execution deadline exceeded"}'
    primary = tmp_path/'execution-error.json'
    primary.write_bytes(original)
    client = Mock()
    client.get_deployment_logs.side_effect = RuntimeError('Log retrieval unavailable')
    capture_deployment_logs(client, 'dep-test', tmp_path)
    assert primary.read_bytes() == original
    assert json.loads((tmp_path/'deployment-logs-error.json').read_text()) == {
        'type': 'RuntimeError', 'message': 'Log retrieval unavailable'}
    client.get_deployment_logs.assert_called_once_with('dep-test')


def seed(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps({'run_id': 'test', 'guard_status': 'pending'}))


def test_startup_timeout_preserves_reason_without_claiming_guard_execution(tmp_path):
    seed(tmp_path)
    original = {'type': 'TimeoutError', 'message': 'Deployment startup exceeded600s'}
    (tmp_path / 'execution-error.json').write_text(json.dumps(original))
    with patch.object(runner, 'finish_outputs') as finish:
        result = runner.finish_or_explain(tmp_path)
    finish.assert_not_called()
    assert result['error_type'] == 'TimeoutError'
    assert result['error'] == original['message']
    assert result['guard_status'] == result['generation_status'] == result['stage2_status'] == 'not_started'
    assert json.loads((tmp_path / 'execution-error.json').read_text()) == original


def test_existing_cli_evidence_still_uses_recovery_despite_execution_error(tmp_path):
    seed(tmp_path)
    (tmp_path / 'execution-error.json').write_text('{"type":"TimeoutError"}')
    (tmp_path / 'cli-stdout.txt').write_text('{"ok":false}')
    with patch.object(runner, 'finish_outputs', return_value={'recovered': True}) as finish:
        assert runner.finish_or_explain(tmp_path) == {'recovered': True}
    finish.assert_called_once_with(tmp_path)


def test_missing_evidence_does_not_invent_startup_timeout(tmp_path):
    seed(tmp_path)
    result = runner.finish_or_explain(tmp_path)
    assert result['error_type'] == 'MissingExecutionResult'
    assert result['guard_status'] == 'unavailable'
    assert result['generation_status'] == result['stage2_status'] == 'unconfirmed'


def test_resume_preserves_pre_submission_failure_without_resubmitting(tmp_path):
    import app_guarded
    import run_platform_once
    seed(tmp_path)
    (tmp_path / 'finished.json').write_text('{}')
    (tmp_path / 'execution-error.json').write_text(
        '{"type":"TimeoutError","message":"Deployment startup exceeded600s"}')
    with patch.object(run_platform_once, 'prepared_directory', return_value=tmp_path), \
         patch.object(run_platform_once, 'recover') as recover, \
         patch.object(runner, 'settle') as settle, \
         patch.object(runner, 'finish_outputs') as finish:
        app_guarded.resume(tmp_path)
    recover.assert_not_called()
    finish.assert_not_called()
    settle.assert_called_once_with(tmp_path)
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['failure_stage'] == 'deployment_startup'
    assert state['guard_status'] == 'not_started'


def test_empty_cli_preserves_unknown_remote_outcome(tmp_path):
    seed(tmp_path)
    (tmp_path/'cli-stdout.txt').write_text('  \n')
    with patch.object(runner,'finish_outputs') as finish:
        result=runner.finish_or_explain(tmp_path)
    finish.assert_not_called()
    assert result['error_type']=='MissingExecutionResult'
    assert result['generation_status']==result['stage2_status']=='unconfirmed'
    assert result['guard_status']=='unavailable'


def test_empty_cli_preserves_recorded_deadline_reason(tmp_path):
    seed(tmp_path)
    (tmp_path/'cli-stdout.txt').write_text('')
    reason={'type':'TimeoutError','message':'Execution deadline exceeded; CLI terminated; remote outcome unconfirmed'}
    (tmp_path/'execution-error.json').write_text(json.dumps(reason))
    result=runner.finish_or_explain(tmp_path)
    assert result['error_type']=='TimeoutError'
    assert result['error']==reason['message']
    assert result['generation_status']=='unconfirmed'
