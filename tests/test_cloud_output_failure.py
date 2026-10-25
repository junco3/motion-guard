import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'core')]
import app


class CloudFailure(unittest.TestCase):
    def test_preflight_never_uploads(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=pathlib.Path(temp)
            app.save(folder/'state.json', {'status':'preparing'})
            app.save(folder/'input.json', {'prompt':'test'})
            (folder/'pose.mp4').write_bytes(b'invalid')
            (folder/'joints.json').write_text('{}')
            with patch.object(app,'LOCK'),patch.object(app,'key') as key,patch('comfy_sdk.Comfy') as client:
                app.generate_cloud_legacy(folder)
                key.assert_not_called()
                client.assert_not_called()
            self.assertEqual(app.read(folder/'state.json')['status'],'preflight_failed')
            self.assertFalse((folder/'attempt.json').exists())

    def test_terminal_output_error_preserves_video_and_settles_once(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=pathlib.Path(temp)/'run';folder.mkdir()
            app.save(folder/'state.json',{'status':'preparing'})
            app.save(folder/'input.json',{'prompt':'test'})
            (folder/'pose.mp4').touch();(folder/'joints.json').write_text('{}')
            ledger=pathlib.Path(temp)/'ledger.json'
            app.save(pathlib.Path(temp)/'config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':1000,'cancel_after_submission_seconds':600,'additional_purchase_allowed':False})
            app.save(ledger,{'unresolved_jobs':[],'known_runs':[],'conservative_prior_credits':10})
            job=MagicMock();job.status='succeeded';job.id='test-job'
            output=MagicMock();output.content_type='video/mp4';output.id='video';output.size_bytes=3
            output.node_id='diag_save'
            output.to_file.side_effect=lambda p:p.write_bytes(b'bad')
            job.outputs=[output]
            client=MagicMock();client.__enter__.return_value=client;client.submit.return_value=job
            with patch.object(app,'ROOT',pathlib.Path(temp)),patch.object(app,'LOCK'),patch.object(app,'LEDGER',ledger),patch.object(app,'key',return_value='test'), \
                 patch.object(app,'api',side_effect=[{'summary':{'balance':{'cloud_credit_balance_cents':10}}},{}]), \
                 patch.object(app,'cumulative_prior',return_value=10),patch('comfy_sdk.Comfy',return_value=client), \
                 patch('timeline_contract.validate_cloud',return_value={'frames':721,'fps':24}), \
                 patch('timeline_contract.validate_cloud_output',side_effect=ValueError('Generated video timeline mismatch')), \
                 patch.object(app,'analyze') as analyze,patch.object(app.subprocess,'run') as encode:
                observer=MagicMock(side_effect=lambda j,p:(p/'diagnostic-evidence.json').write_text('{"retained":true}'))
                app.generate_cloud_legacy(folder,ROOT/'workflows/T1/depth-stage1.api.json',observer)
                observer.assert_called_once_with(job,folder)
                analyze.assert_not_called();encode.assert_not_called()
            state=app.read(folder/'state.json')
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['terminal_status'],'succeeded')
            self.assertEqual(state['failure_stage'],'output_processing')
            self.assertEqual((folder/'generated.mp4').read_bytes(),b'bad')
            self.assertEqual(app.read(ledger)['conservative_prior_credits'],189.6)
            self.assertTrue(app.read(folder/'reservation.json')['released'])
            self.assertTrue(app.read(folder/'diagnostic-evidence.json')['retained'])


if __name__=='__main__':unittest.main()
