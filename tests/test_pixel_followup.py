import sys
import json
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import requests
from unittest.mock import MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import app
import pixel_followup


def test_script_entrypoint_shares_lock_with_worker(tmp_path):
    import subprocess
    script = '''
import sys, runpy, http.server
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
class Server:
    def __init__(self, *args): pass
    def serve_forever(self):
        import app, pixel_followup
        assert app is sys.modules['__main__']
        app.LOCK.acquire()
        pixel_followup.run(Path(sys.argv[3]))
        assert not app.LOCK.locked()
        print('SCRIPT_LOCK_RELEASED')
with patch.object(Path, 'glob', return_value=[]), patch.object(http.server, 'ThreadingHTTPServer', Server):
    runpy.run_path(sys.argv[2], run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'server'),
                             str(ROOT / 'server/app.py'), str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'SCRIPT_LOCK_RELEASED' in result.stdout


def test_worker_initialization_failure_releases_lock(tmp_path):
    app.LOCK.acquire()
    pixel_followup.run(tmp_path)
    assert not app.LOCK.locked()
    assert app.read(tmp_path / 'pixel-worker-error.json')['error_type'] == 'FileNotFoundError'


def test_uncertain_holds_without_provider(tmp_path):
    pin = {'allowed': False, 'guard_verdict': 'UNCERTAIN'}
    with patch.object(pixel_followup, 'verified_report', return_value=({}, pin)), \
         patch.object(app, 'key', side_effect=AssertionError('credential accessed')):
        state, launch = pixel_followup.begin(tmp_path)
    assert not launch and state['status'] == 'held'
    assert not state['provider_contact_started']


def test_restart_cancels_original_job_before_changed_input_validation(tmp_path):
    import comfy_sdk
    state = {'job_id': 'original-job', 'submitted_at': 100, 'status': 'running'}
    app.save(tmp_path / 'pixel-state.json', state)
    app.save(tmp_path / 'pixel-attempt.json', state)
    app.save(tmp_path / 'pixel-reservation.json', {'prior': 300, 'reserved': 179.6})
    ledger_path = tmp_path / 'ledger.json'
    app.save(ledger_path, {'conservative_prior_credits': 100, 'known_runs': [],
                          'unresolved_jobs': [tmp_path.name + ':pixel']})
    job = MagicMock(status='running')
    def cancel():
        job.status = 'canceled'
    job.cancel.side_effect = cancel
    client = MagicMock()
    client.jobs.get.return_value = job
    factory = MagicMock()
    factory.return_value.__enter__.return_value = client
    with patch.object(comfy_sdk, 'Comfy', factory), patch.object(app, 'key', return_value='test-only'), \
         patch.object(app, 'LEDGER', ledger_path), patch.object(app.time, 'time', return_value=701), \
         patch.object(app.time, 'sleep'), \
         patch.object(pixel_followup, 'verified_report', side_effect=ValueError('changed source')):
        pixel_followup.recover_known(tmp_path)
    client.jobs.get.assert_called_once_with('original-job')
    job.cancel.assert_called_once()
    client.submit.assert_not_called()
    client.assets.from_file.assert_not_called()
    assert app.read(ledger_path)['conservative_prior_credits'] == pytest.approx(479.6)
    assert app.read(tmp_path / 'pixel-state.json')['status'] == 'error'
    assert not app.LOCK.locked()


def test_pass_submits_once_validates_and_publishes(tmp_path):
    import comfy_sdk
    import cv2
    import timeline_contract
    import motionguard_core.reference_io
    folder = tmp_path / 't3-test'
    folder.mkdir()
    pin = {'allowed': True, 'guard_verdict': 'PASS'}
    app.save(folder / 'pixel-request.json', pin)
    app.save(folder / 'pixel-state.json', {**pin, 'status': 'ready'})
    app.save(tmp_path / 'config/budget.yaml', {'allow_paid_execution': True,
             'additional_purchase_allowed': False, 'cancel_after_submission_seconds': 600,
             'max_total_credits': 10000})
    ledger_path = tmp_path / 'ledger.json'
    app.save(ledger_path, {'conservative_prior_credits': 100, 'known_runs': [], 'unresolved_jobs': []})
    video = MagicMock(content_type='video/mp4')
    video.to_file.side_effect = lambda p: p.write_bytes(b'test-output')
    job = MagicMock(status='succeeded', id='only-job', outputs=[video])
    client = MagicMock()
    client.submit.return_value = job
    factory = MagicMock()
    factory.return_value.__enter__.return_value = client
    cap_in, cap_out = MagicMock(), MagicMock()
    cap_in.get.side_effect = [768, 512]
    cap_out.get.side_effect = [1536, 1024]
    info = {v['class_type']: {} for v in pixel_followup.workflow().values()}
    info['UpscaleModelLoader'] = {'input': {'required': {'model_name': [[pixel_followup.MODEL]]}}}
    def api(path, key):
        if path == '/api/object_info': return info
        if path == '/api/queue': return {}
        return {'summary': {'balance': {'cloud_credit_balance_cents': 1}}}
    with patch.object(app, 'ROOT', tmp_path), patch.object(app, 'LEDGER', ledger_path), \
         patch.object(app, 'api', side_effect=api), patch.object(app, 'key', return_value='test'), \
         patch.object(app, 'cumulative_prior', return_value=300), \
         patch.object(app, 'selected_gt', return_value=folder / 'gt.json'), \
         patch.object(pixel_followup, 'verified_report', return_value=({}, pin)), \
         patch.object(comfy_sdk, 'Comfy', factory), \
         patch.object(cv2, 'VideoCapture', side_effect=[cap_in, cap_out]), \
         patch.object(timeline_contract, 'validate_cloud_output') as validate, \
         patch.object(motionguard_core.reference_io, 'validate_timeline', return_value={'frames': 97, 'fps': 24}):
        app.save(folder / 'gt.json', {})
        app.LOCK.acquire()
        pixel_followup.run(folder)
    state = app.read(folder / 'pixel-state.json')
    assert state['status'] == 'complete'
    assert state['final_sha256'] == app.sha(b'test-output')
    assert state['final_size'] == [1536, 1024]
    client.submit.assert_called_once()
    assert validate.call_count == 2
    assert app.read(ledger_path)['conservative_prior_credits'] == pytest.approx(479.6)
    assert pixel_followup.begin(folder)[1] is False
    assert not app.LOCK.locked()


@pytest.mark.parametrize('fixture_index',[0,1])
def test_recorded_fail_binding_blocks_before_provider(tmp_path,monkeypatch,fixture_index):
    # Recorded verdict payload, freshly bound synthetic file bytes: HTTP/gate test,
    # not a new video-analysis or historical owner-workspace test.
    folder=tmp_path/('t3-'+str(fixture_index)*32);folder.mkdir()
    directory='guard-'+'a'*32
    app.save(folder/'state.json',{'status':'succeeded','guard_status':'complete',
        'guard_directory':directory,'guard_verdict':'FAIL','source_type':'cloud_local_guard'})
    pins={}
    for key,name in [('reference','reference.mp4'),('generated','generated.mp4'),('gt','joints.json')]:
        path=folder/name;path.write_bytes(b'HTTP binding fixture')
        pins[key]={'path':str(path),'sha256':app.sha(path.read_bytes())}
    app.save(folder/'guard-inputs.json',pins)
    report=app.read(ROOT/'tests/fixtures'/f'fail-report-{fixture_index}.json')
    report['sources']=pins;app.save(folder/directory/'report.json',report)
    monkeypatch.setattr(app,'RUNS',tmp_path)
    original = (folder / 'state.json').read_bytes()
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    headers = {'Origin': base, 'X-MotionGuard-Token': app.TOKEN}
    try:
        with patch.object(app, 'key', side_effect=AssertionError('credential accessed')) as key, \
             patch.object(app, 'api', side_effect=AssertionError('provider accessed')) as api, \
             patch('pixel_followup.run', side_effect=AssertionError('worker started')) as worker:
            responses = [requests.post(base + '/api/finalize', json={'run_id': folder.name},
                                      headers=headers, timeout=10) for _ in range(2)]
            assert all(r.status_code == 200 for r in responses)
            decision = responses[0].json()['pixel_followup']
            assert decision['status'] == 'held'
            assert decision['guard_verdict'] == 'FAIL'
            assert decision['allowed'] is False and decision['submitted'] is False
            assert key.call_count == api.call_count == worker.call_count == 0
            assert not (folder / 'pixel-attempt.json').exists()
            assert not (folder / 'pixel-reservation.json').exists()
            assert (folder / 'state.json').read_bytes() == original
            assert not app.LOCK.locked()
            evidence = {'run_id': folder.name, 'http': [r.status_code for r in responses],
                        'verdict': 'FAIL', 'decision': 'held', 'credential_calls': key.call_count,
                        'api_calls': api.call_count, 'worker_calls': worker.call_count,
                        'original_state_unchanged': True, 'automatic_retry': False,
                        'coverage': 'actual local HTTP and recorded FAIL payload bound to fixture files; no provider submission'}
            evidence['source_type'] = app.read(folder / 'state.json').get('source_type')

            app.save(tmp_path / 'http-evidence.json', evidence)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
