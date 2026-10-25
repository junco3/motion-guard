"""Reclassify one verified short-lived deployment; not invoice settlement."""
import copy
import hashlib
import json
from datetime import datetime

RUN = 't3-eff4e35305684320ad18fea2554c1a62'
EXECUTION = 'ee1f215d-371a-4f85-83bc-93b0f3a75ba8'
H100_RUN = 't3-7232b7d6990a450880e07d76fae2277b'
H100_EXECUTION = '29dac581-e1d9-430c-8d7e-dcb1da4e88df'


def reconcile(ledger, snapshot, evidence_sha256, h100=False):
    run,execution,original,target,window,gpu=(H100_RUN,H100_EXECUTION,280,140,300,'h100-sxm') if h100 else (RUN,EXECUTION,404,202,600,'rtx-pro-6000-server')
    result = copy.deepcopy(ledger)
    adjustments = result.setdefault('reservation_adjustments', {})
    if execution in adjustments:
        return result
    record = result['guarded_settlements'][execution]
    if (record['run_id'] != run or record['reserved_credits_counted'] != original
            or record['actual_invoice'] is not False or result['unresolved_jobs']):
        raise ValueError('Reservation identity or pending execution mismatch')
    compute = snapshot['computeConfig']
    if (snapshot['id'] != record['deployment_id'] or snapshot['status'] != 'stopped'
            or snapshot['releases'] != [] or compute['max'] != 1
            or compute['gpuClass'] != gpu):
        raise ValueError('Deployment identity or lifecycle mismatch')
    start = datetime.fromisoformat(snapshot['createdAt'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(snapshot['deletedAt'].replace('Z', '+00:00'))
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError('Timezone required')
    seconds = (end-start).total_seconds()
    if not 0 < seconds <= window:
        raise ValueError('Deployment exceeded short reservation window')
    remaining = result['conservative_prior_credits']-(original-target)
    if remaining < max(0, result.get('shared_account_decrease_credits', 0)):
        raise ValueError('Observed account decrease floor violated')
    adjustments[execution] = {
        'run_id': run, 'original_reservation': original, 'reclassified_reservation': target,
        'released_excess': original-target, 'actual_invoice': False,
        'lifetime_seconds': seconds, 'deployment_evidence_sha256': evidence_sha256,
        'reviewer': 'product_gap_review',
        'reason': f'Full deployment lifetime within {window}s; max1 worker; reviewed conservative bound {target}; storage reservation preserved',
    }
    result['conservative_prior_credits'] = remaining
    result['note'] = 'Original reservations retained; explicit reviewed short-lifetime adjustment applied. Not invoice settlement.'
    return result


if __name__ == '__main__':
    import sys,argparse
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
    from app import ROOT, LEDGER, read, save
    from storage_lease import accounting_lock
    parser=argparse.ArgumentParser();parser.add_argument('--h100',action='store_true')
    args=parser.parse_args()
    evidence = ROOT/'data/gen'/(H100_RUN if args.h100 else RUN)/'deployment-final.json'
    with accounting_lock():
        current = read(LEDGER)
        updated = reconcile(current, read(evidence), hashlib.sha256(evidence.read_bytes()).hexdigest(),args.h100)
        save(LEDGER, updated)
    print(json.dumps({'conservative_credits': updated['conservative_prior_credits'],
                      'remaining': 2000-updated['conservative_prior_credits'],
                      'actual_invoice': False}))
