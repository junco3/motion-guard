"""Bounded caller-owned, GET-only recovery after compute cleanup and settlement."""
import json
import sys
from pathlib import Path
from app import LEDGER, read, key
from import_platform_guard import save


def context(folder):
    plan = read(folder/'execution-plan.json')
    attempt = read(folder/'attempt.json')
    submitted = read(folder/'job-submitted.json')
    final = read(folder/'deployment-final.json')
    ledger = read(LEDGER)
    settlement = ledger.get('guarded_settlements', {}).get(plan['execution_id'], {})
    if not (folder/'finished.json').is_file() or final.get('status') != 'stopped':
        raise ValueError('Recovery requires completed compute cleanup')
    if (submitted.get('deployment_id') != attempt.get('deployment_id')
            or final.get('id') != submitted.get('deployment_id')
            or final.get('releaseId') != plan.get('approved_release_id')
            or attempt.get('release_id') != plan.get('approved_release_id')
            or settlement.get('run_id') != folder.name
            or settlement.get('deployment_id') != final['id']
            or folder.name in ledger.get('unresolved_jobs', [])):
        raise ValueError('Recovery execution or settlement identity mismatch')
    terminal = read(folder/'job-terminal.json') if (folder/'job-terminal.json').exists() else None
    if terminal and (terminal.get('job_id') != submitted.get('job_id')
                     or terminal.get('deployment_id') != submitted['deployment_id']):
        raise ValueError('Terminal journal identity mismatch')
    return submitted, final


def recover(folder):
    from comfy_cli.http import request_json
    from comfy_cli.target import Target
    from comfy_cli.deploy_download import validate_endpoint_origin, OutputDownloadRequest, download_job_outputs
    from comfy_cli.output import get_renderer
    submitted, final = context(folder)
    origin = validate_endpoint_origin(final['id'], final.get('endpointUrl'))
    token = key()
    target = Target(kind='cloud', base_url=origin, path_prefix='/api/v2', auth_token=token)
    status, job = request_json(target.url('jobs/'+submitted['job_id']), target,
                               timeout=20, max_bytes=4*1024*1024)
    if (status != 200 or job.get('id') != submitted['job_id'] or job.get('status') != 'succeeded'
            or job.get('deployment_id') != final['id'] or job.get('release_id') != final['releaseId']
            or any(row.get('job_id') != job['id'] for row in job.get('outputs', []))):
        raise ValueError('Same remote job has no confirmed successful result')
    outputs = download_job_outputs(OutputDownloadRequest(tuple(job.get('outputs') or []), origin,
                                                         token, folder/'outputs'), get_renderer())
    # Identity and local paths only; URLs from the remote response stay in memory.
    save(folder/'automatic-recovery.json', {'job': {'id': job['id'], 'status': job['status']},
        'deployment_id': final['id'], 'release_id': final['releaseId'], 'outputs': outputs,
        'method': 'same-job GET after cleanup; no submission'})


if __name__ == '__main__':
    recover(Path(sys.argv[1]).resolve(strict=True))
