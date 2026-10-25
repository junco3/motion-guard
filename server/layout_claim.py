"""Read-only eligibility for another explicit job; never retry or clear a claim."""
import hashlib
import json
import re


def completed_claim(root, config, ledger):
    run = config.get('claimed_run')
    if not run:
        return True
    if not re.fullmatch(r't3-[a-f0-9]{32}', run) or ledger.get('unresolved_jobs'):
        return False
    folder = root/'data/gen'/run
    def read(name):
        return json.loads((folder/name).read_text(encoding='utf-8'))
    try:
        raw = (folder/'execution-plan.json').read_bytes()
        plan = json.loads(raw)
        execution = config['claimed_execution_id']
        if (hashlib.sha256(raw).hexdigest() != config['claimed_plan_sha256']
                or plan['execution_id'] != execution
                or read('state.json')['status'] not in ('succeeded', 'failed')
                or not (folder/'finished.json').is_file()
                or run not in ledger.get('known_runs', [])):
            return False
        settled = ledger.get('guarded_settlements', {}).get(execution, {})
        attempt = read('attempt.json')
        final = read('deployment-final.json')
        if (settled.get('run_id') != run or settled.get('deployment_id') != final.get('id')
                or not final.get('id') or attempt.get('deployment_id') != final.get('id')
                or not final.get('releaseId') or attempt.get('release_id') != final.get('releaseId')):
            return False
        from run_platform_once import deletion_confirmed, controlplane_evidence_valid
        if deletion_confirmed(final):
            return True
        if final.get('deletedAt'):
            deleted = read('control-plane-deletion.json')
            return deleted.get('snapshot') == final and controlplane_evidence_valid(final, deleted.get('events', {}), deleted.get('deployments', []))
        if attempt.get('retain_models'):
            from deployment_reuse import stopped_evidence_valid
            stop = read('control-plane-stop.json')
            return stop.get('snapshot') == final and stopped_evidence_valid(final, stop.get('events', {}), attempt)
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
