"""Explicit first-use authorization. Never reset an existing spending history."""
import argparse
from pathlib import Path
import app

def provision(root,authorized_credits):
    root=Path(root)
    if app.nonnegative(authorized_credits,'authorization')!=1000:
        raise ValueError('This release supports an explicit 1000-credit ceiling only')
    config=root/'config';budget_path=config/'budget.yaml';ledger_path=config/'t1-spend-ledger.json'
    marker=config/'provision.lock'
    with marker.open('x',encoding='utf-8') as lock:
        lock.write('First-use provisioning in progress; no generation submitted.\n')
    try:
        budget=app.read(budget_path);ledger=app.read(ledger_path)
        if budget.get('allow_paid_execution') is not False:raise ValueError('Paid execution must be disabled')
        if (ledger.get('conservative_prior_credits')!=0 or ledger.get('known_runs')!=[] or
            ledger.get('unresolved_jobs')!=[] or 'billing_baseline_cents' in ledger or 'credential_sha256' in ledger):
            raise ValueError('Existing or partially provisioned ledger preserved')
        runs=root/'data/gen'
        if runs.exists() and any(runs.iterdir()):raise ValueError('Existing execution data preserved')
        credential=app.key()
        if not credential:raise ValueError('Missing credential')
        billing=app.api('/api/billing/usage/timeseries?months=1',credential)
        balance=app.nonnegative(billing['summary']['balance']['cloud_credit_balance_cents'],'balance cents')
        if app.read(budget_path)!=budget or app.read(ledger_path)!=ledger:raise ValueError('Configuration changed during provisioning')
        if runs.exists() and any(runs.iterdir()):raise ValueError('Execution data appeared during provisioning')
        updated={**ledger,'billing_baseline_cents':balance,'credits_per_cent':2.11,
                 'credential_sha256':app.sha(credential.encode()),'scope':'New operator, cumulative spending; never reset'}
        app.save(ledger_path,updated)
        # Last operation enables execution. Failure here leaves a closed budget and
        # a preserved partial ledger; rerunning cannot reset its baseline.
        app.save(budget_path,{**budget,'allow_paid_execution':True,'max_total_credits':1000,
                 'cancel_after_submission_seconds':600,'additional_purchase_allowed':False})
        return {'configured':True,'ceiling_credits':1000,'submitted_jobs':0}
    finally:
        marker.unlink()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-credits',type=int,required=True)
    args=parser.parse_args()
    print(provision(app.ROOT,args.authorize_credits))
