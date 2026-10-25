"""Run the installed CLI with a durable, credential-free submission journal."""
import json
import os
import sys
import uuid
from pathlib import Path


def record_once(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication without replacing an earlier submission record.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install_journal(folder):
    from comfy_cli.deploy_jobs import DeployJobClient
    from comfy_cli.command import deploy_run
    if deploy_run.DeployJobClient is not DeployJobClient:
        raise RuntimeError('Unsupported CLI submission binding')
    original = DeployJobClient.submit_job

    def submit(client, request, *args, **kwargs):
        record_once(folder/'job-submit-started.json', {
            'deployment_id': request.deployment_id,
            'idempotency_key': request.idempotency_key,
            'remote_outcome': 'unconfirmed'})
        response = original(client, request, *args, **kwargs)
        # The pre-submit record survives all post-submit exceptions. No retry.
        if not isinstance(response, dict) or not isinstance(response.get('id'), str) or not response['id']:
            raise RuntimeError('Submitted job response has no supported identity; remote outcome unconfirmed')
        record_once(folder/'job-submitted.json', {
            'deployment_id': request.deployment_id,
            'job_id': response['id']})
        return response

    DeployJobClient.submit_job = submit
    terminal_result = deploy_run._terminal_result

    def terminal(job):
        terminal_result(job)
        submitted = json.loads((folder/'job-submitted.json').read_text(encoding='utf-8'))
        plan = json.loads((folder/'execution-plan.json').read_text(encoding='utf-8'))
        if (job.get('id') != submitted['job_id'] or job.get('deployment_id') != submitted['deployment_id']
                or job.get('release_id') != plan['approved_release_id']
                or job.get('status') not in {'succeeded', 'failed', 'canceled', 'expired'}
                or any(row.get('job_id') != job['id'] for row in job.get('outputs', []))):
            raise RuntimeError('Terminal job identity or status mismatch')
        # Do not persist signed URLs or credentials. Recovery reads this same job.
        record_once(folder/'job-terminal.json', {
            **submitted, 'status': job['status'], 'release_id':job['release_id'],
            'outputs': [{k: row[k] for k in ('id','name','node_id','type','size_bytes','sha256','hash','job_id') if k in row}
                        for row in job.get('outputs', [])]})

    deploy_run._terminal_result = terminal
    return original


if __name__ == '__main__':
    folder = Path(sys.argv.pop(1)).resolve(strict=True)
    install_journal(folder)
    from comfy_cli.__main__ import main
    main()
