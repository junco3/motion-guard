"""Mock gate: no network calls or billing enforcement."""
from jsonschema import validate
SCHEMA={'type':'object','required':['verdict'],'additionalProperties':False,'properties':{'verdict':{'enum':['PASS','FAIL','UNCERTAIN','ERROR']}}}
def simulate(report,stage2):
    validate(report,SCHEMA)
    if report['verdict']=='PASS': return stage2()
    return None
def paid_execution_allowed(budget):
    return (budget.get('allow_paid_execution') is True and budget.get('require_human_approval') is True
            and bool(budget.get('approved_by')) and bool(budget.get('approval_reference'))
            and all(type(budget.get(k)) in (int,float) and budget[k]>0 for k in
                    ('max_total_charge','max_job_charge','max_total_credits','max_total_gpu_minutes','max_deployment_active_minutes')))
