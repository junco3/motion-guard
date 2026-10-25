"""One approved guarded run; cleanup and conservative accounting precede restoration."""
import json
import shutil
import sys
import subprocess
from pathlib import Path
import portable_lock
import cv2
from app import ROOT, LEDGER, read, key
from import_platform_guard import restore, save, sha, preserve_draft
from run_platform_once import main, prepared_directory, deletion_confirmed, controlplane_evidence_valid
from deployment_reuse import stopped_evidence_valid
from platform_preflight import H100_GUARDED_PROFILES


def recover_outputs(folder, envelope):
    """Read-only recovery of known failed job evidence; never submits or restarts."""
    from comfy_cli.deploy_download import (validate_endpoint_origin, resolve_endpoint_link,
                                           OutputDownloadRequest, download_job_outputs)
    from comfy_cli.http import request_json
    from comfy_cli.target import Target
    from comfy_cli.output import get_renderer
    details = (envelope.get('error') or {}).get('details') or {}
    job = details.get('job') or {}
    if not job.get('id'):
        raise ValueError('CLI returned no recoverable job identity; original evidence retained')
    attempt = read(folder/'attempt.json')
    if attempt.get('reused_deployment'):
        pin = read(folder/'deployment-reuse.json')
        if pin.get('deployment_id') != attempt.get('deployment_id') or pin.get('release_id') != attempt.get('release_id'):
            raise ValueError('Recovery reuse identity mismatch')
        deployment = {'id': attempt['deployment_id']}
    else:
        deployment = read(folder/'deployment-created.json')
    if attempt.get('deployment_id') and deployment.get('id') != attempt['deployment_id']:
        raise ValueError('Recovery attempt identity mismatch')
    if not deployment.get('endpointUrl') and (folder/'deployment-latest.json').exists():
        latest = read(folder/'deployment-latest.json')
        if latest.get('id') != deployment['id']:
            raise ValueError('Recovery deployment identity mismatch')
        deployment = latest
    origin = validate_endpoint_origin(deployment['id'], deployment.get('endpointUrl'))
    token = key()
    link = (job.get('urls') or {}).get('self')
    if link:
        try:
            status, current = request_json(resolve_endpoint_link(origin, link),
                                   Target(kind='cloud', base_url=origin, path_prefix='/api/v2', auth_token=token),
                                   max_bytes=4*1024*1024)
            if not 200 <= status < 300 or not isinstance(current, dict) or current.get('id') != job['id']:
                raise ValueError('Recovery returned a different job')
            job = current
        except Exception as exc:
            save(folder/'recovery-read-error.json', {'type': type(exc).__name__})
    save(folder/'recovered-job.json', job)
    outputs = download_job_outputs(OutputDownloadRequest(tuple(job.get('outputs') or []), origin,
                                                        token, folder/'outputs'), get_renderer())
    return {'job': job, 'outputs': outputs}


def settle(folder):
    attempt = read(folder/'attempt.json')
    final = read(folder/'deployment-final.json')
    if not (folder/'finished.json').exists():
        raise ValueError('Cleanup not finished')
    fallback = read(folder/'control-plane-deletion.json') if (folder/'control-plane-deletion.json').exists() else {}
    if attempt.get('retain_models'):
        stopped = read(folder/'control-plane-stop.json')
        if stopped.get('snapshot') != final or not stopped_evidence_valid(final,stopped.get('events',{}),attempt):
            raise ValueError('Fresh deployment stop evidence missing')
    elif not deletion_confirmed(final):
        events = fallback.get('events', {})
        deployments = fallback.get('deployments', [])
        if (fallback.get('snapshot') != final or not final.get('deletedAt')
                or final.get('status') != 'stopped' or final.get('releases') != []
                or final.get('releaseId') != attempt['release_id']
                or events.get('deploymentId') != final['id']
                or not any(e.get('status') == 'stopped' and e.get('releaseId') == final['releaseId'] for e in events.get('events', []))
                or any(d.get('id') == final['id'] and not d.get('deletedAt') for d in deployments)
                or not controlplane_evidence_valid(final,events,deployments)):
            raise ValueError('Deployment deletion evidence missing')
    execution = read(folder/'execution-plan.json')['execution_id']
    with (LEDGER.parent/'guarded-accounting.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        portable_lock.lock(lock)
        try:
            ledger = read(LEDGER)
            records = ledger.setdefault('guarded_settlements', {})
            if execution in records:
                if records[execution]['run_id'] != folder.name:
                    raise ValueError('Execution ID already belongs to another run')
                return records[execution]
            if folder.name not in ledger['unresolved_jobs'] or folder.name in ledger['known_runs']:
                raise ValueError('Unresolved reservation identity mismatch')
            reservation=attempt['reserved_credits']
            plan=read(folder/'execution-plan.json')
            h100_probe=(plan.get('purpose')=='model_reuse_probe' and plan.get('gpu_class')=='h100-sxm'
                        and (attempt.get('compute') or {}).get('gpuClass')=='h100-sxm'
                        and (plan.get('deadline_seconds'),reservation) in ((600,280),(450,210)))
            h100_probe |= (plan.get('purpose')=='User-requested guarded generation'
                           and plan.get('gpu_class')=='h100-sxm'
                           and (attempt.get('compute') or {}).get('gpuClass')=='h100-sxm'
                           and (plan.get('deadline_seconds'),reservation) in H100_GUARDED_PROFILES)
            if (reservation not in (202,404,210) and (plan.get('deadline_seconds'),reservation) not in H100_GUARDED_PROFILES
                    or reservation!=plan.get('max_credits_reservation',202)
                    or abs(attempt['deadline']-attempt['started_at']-plan.get('deadline_seconds',600))>0.01
                    or ((plan.get('deadline_seconds',600),reservation) not in ((600,202),(1200,404)) and not h100_probe)):
                raise ValueError('Unexpected reservation')
            prior = max(ledger['conservative_prior_credits'], attempt['prior_credits'])
            record = {'run_id': folder.name, 'reserved_credits_counted': reservation,
                      'actual_invoice': False, 'deployment_id': final['id']}
            records[execution] = record
            ledger['conservative_prior_credits'] = prior + reservation
            ledger['known_runs'].append(folder.name)
            ledger['unresolved_jobs'].remove(folder.name)
            ledger['note'] = f'Guarded run counts full {reservation} reservation conservatively, not actual invoice.'
            save(LEDGER, ledger)
            return record
        finally:
            lock.seek(0); portable_lock.unlock(lock)


def finish_outputs(folder, recovered=False):
    plan = read(folder/'execution-plan.json')
    if recovered:
        from recover_platform_result import context
        submitted, deployment = context(folder)
        data = read(folder/'automatic-recovery.json')
        if (data.get('deployment_id') != deployment['id'] or data.get('release_id') != deployment['releaseId']
                or data.get('job', {}).get('id') != submitted['job_id']):
            raise ValueError('Recovered result identity mismatch')
        envelope = {'ok': True}
    else:
        envelope = json.loads((folder/'cli-stdout.txt').read_text(encoding='utf-8'))
        data = envelope.get('data') or {}
    if not data.get('outputs') and envelope.get('ok') is not True:
        data = recover_outputs(folder, envelope)
    job = data.get('job') or {}
    successful = ((recovered or read(folder/'cli-exit.json')['returncode'] == 0)
                  and envelope.get('ok') is True and job.get('status') == 'succeeded')
    state = read(folder/'state.json') if (folder/'state.json').exists() else {}
    save(folder/'state.json', {**state, 'run_id': folder.name, 'job_id': job.get('id'),
                             'status': 'restoring', 'guard_status': 'complete' if state.get('guard_status')=='complete' else 'running'})
    outputs = data.get('outputs') or []
    save(folder/'remote-outputs.json', outputs)
    gt_name=plan.get('gt_file','joints.json')
    if gt_name not in ('joints.json','joints.skin-v2.json','joints.observed.json'):
        raise ValueError('Invalid result reference GT')
    submitted = {role: {'path': str(folder/name), 'sha256': plan['input_hashes'][name]}
                 for role, name in [('reference', 'reference.mp4'), ('gt', gt_name)]}
    # Preserve and inspect any retrieved evidence even when downstream execution failed.
    preserve_draft(folder, outputs, plan['execution_id'], submitted)
    stage_audit = None
    if plan.get('stage_audit'):
        from stage_audit_result import consume
        stage_audit = consume(folder, outputs, plan)
        save(folder/'verified-stage-audit.json', stage_audit)
    report = restore(folder, outputs, plan['execution_id'], submitted, publish_success=False)
    finals = [o for o in outputs if o.get('node_id') == '4852' and o.get('type') == 'video']
    verdict = report['verdict']
    result = {'guard_verdict': verdict, 'job_succeeded': successful,
              'stage2_artifact_count': len(finals), 'stage2_execution_absence_proven': False}
    if stage_audit is not None:
        if stage_audit['guard_verdict'] != verdict:
            raise ValueError('Stage audit and restored Guard disagree')
        result.update(stage2_execution_absence_proven=successful and stage_audit['held'],
                      stage_audit=stage_audit)
    if verdict == 'PASS':
        if len(finals) != 1:
            raise ValueError('Guard PASS but final Stage2 artifact missing or ambiguous')
        video = Path(finals[0]['path']).resolve()
        if video.parent != folder/'outputs' or not video.is_file():
            raise ValueError('Final artifact outside run')
        cap = cv2.VideoCapture(str(video)); count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS); width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); decoded = 0
        while True:
            ok, frame = cap.read()
            if not ok: break
            decoded += 1
        cap.release()
        from motionguard_core.reference_io import validate_timeline
        gt_file=plan.get('gt_file','joints.json');gt_path=folder/gt_file
        if sha(gt_path)!=plan['input_hashes'][gt_file]:raise ValueError('Final GT source changed')
        expected=validate_timeline(read(gt_path))
        if plan.get('expected_frames',expected['frames'])!=expected['frames'] or plan.get('expected_fps',24)!=24:raise ValueError('Plan and GT timeline disagree')
        if count != expected['frames'] or decoded != expected['frames'] or fps != 24 or [width, height] != plan['expected_final_size']:
            raise ValueError('Final Stage2 video timeline or size invalid')
        shutil.copyfile(video, folder/'final.mp4')
        result.update(final_sha256=sha(video), final_size=[width, height], final_frames=decoded)
    elif finals:
        raise ValueError('Non-PASS Guard unexpectedly produced final Stage2 output')
    save(folder/'downstream-result.json', result)
    state = read(folder/'state.json')
    if successful:
        for key in ('error', 'error_type', 'guard_error', 'failure_stage'):
            state.pop(key, None)
    if recovered:
        state.update(generation_status='recovered', stage2_status='complete' if verdict=='PASS' else 'held',
                     recovery_provenance='automatic-recovery.json', automatic_recovery=True, draft_available=True)
    save(folder/'state.json', {**state, 'status': 'succeeded' if successful else 'failed',
                             'downstream_status': ('complete' if verdict == 'PASS' else 'held') if successful else 'error',
                             'final_available': successful and verdict == 'PASS'})
    if not successful:
        raise ValueError('Remote job failed; recovered Guard evidence retained')
    return result


def finish_or_explain(folder):
    """Keep pre-submission failures distinct from an actual Guard error."""
    if (folder/'automatic-recovery.json').exists():
        # Revalidate the same local artifacts; never repeat network recovery.
        return finish_outputs(folder, recovered=True)
    envelope = None
    if (folder/'cli-stdout.txt').exists():
        try:
            envelope = json.loads((folder/'cli-stdout.txt').read_text(encoding='utf-8'))
        except (ValueError, TypeError):
            pass
    if isinstance(envelope, dict) and envelope.get('ok') is True and read(folder/'cli-exit.json').get('returncode') == 0:
        return finish_outputs(folder)
    # Existing failed-job envelope handling remains for executions without a journal.
    if isinstance(envelope, dict) and not (folder/'job-submitted.json').exists():
        return finish_outputs(folder)
    if (folder/'job-submitted.json').exists():
        from recover_platform_result import context
        from platform_cli import record_once
        try:
            context(folder)
            record_once(folder/'automatic-recovery-started.json', {'limit_seconds':120, 'new_submission':False})
            save(folder/'recovery-original-state.json', read(folder/'state.json'))
            subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'server/recover_platform_result.py'), str(folder)],
                           check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return finish_outputs(folder, recovered=True)
        except Exception as exc:
            save(folder/'automatic-recovery-error.json', {'type':type(exc).__name__, 'message':str(exc)[:500]})
    source = read(folder/'execution-error.json') if (folder/'execution-error.json').exists() else None
    state = read(folder/'state.json')
    state.pop('guard_error', None)
    startup_timeout = (isinstance(source, dict) and source.get('type') == 'TimeoutError'
                       and str(source.get('message', '')).startswith('Deployment startup exceeded'))
    details = {
        'status': 'failed', 'final_available': False, 'draft_available': False,
        'guard_status': 'not_started' if startup_timeout else 'unavailable',
        'error_type': source.get('type', 'PlatformExecutionError') if source else 'MissingExecutionResult',
        'error': source.get('message', 'Platform execution failed') if source else
                 'No CLI result or original execution error was recorded',
        'failure_stage': 'deployment_startup' if startup_timeout else 'execution_result',
        'generation_status': 'not_started' if startup_timeout else 'unconfirmed',
        'stage2_status': 'not_started' if startup_timeout else 'unconfirmed',
    }
    save(folder/'state.json', {**state, **details})
    return details


def run(release, folder):
    folder = prepared_directory(folder)
    if (folder/'attempt.json').exists():
        raise ValueError('Existing attempt preserved; never resubmit')
    save(folder/'state.json', {'run_id': folder.name, 'status': 'running', 'guard_status': 'pending',
                              'source_type': 'platform_guarded', 'final_available': False})
    try:
        main(release, folder)
        settle(folder)
        return finish_or_explain(folder)
    except Exception as exc:
        state = read(folder/'state.json')
        if state.get('guard_status') == 'complete':
            state['downstream_status'] = 'error'
        elif (folder/'finished.json').exists():
            state.update(guard_status='error', guard_error=type(exc).__name__)
        save(folder/'state.json', {**state, 'status': 'failed', 'final_available': False,
                                  'error': str(exc)[:1000], 'error_type': type(exc).__name__})
        raise


if __name__ == '__main__':
    print(json.dumps(run(sys.argv[1], ROOT/'data/gen'/sys.argv[2])))
