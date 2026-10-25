import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from reconcile_short_reservation import reconcile, RUN, EXECUTION, H100_RUN, H100_EXECUTION


def data():
    ledger={'conservative_prior_credits':1833.267958,'shared_account_decrease_credits':127.32,
            'unresolved_jobs':[], 'guarded_settlements':{EXECUTION:{
                'run_id':RUN,'reserved_credits_counted':404,'actual_invoice':False,'deployment_id':'owned'}}}
    snapshot={'id':'owned','status':'stopped','releases':[],
              'computeConfig':{'max':1,'gpuClass':'rtx-pro-6000-server'},
              'createdAt':'2026-10-20T00:27:11.398576Z','deletedAt':'2026-10-20T00:36:55.546655Z'}
    return ledger,snapshot


def test_adjustment_is_idempotent_and_preserves_original():
    ledger,snapshot=data(); original=copy.deepcopy(ledger)
    result=reconcile(ledger,snapshot,'hash')
    assert ledger==original
    assert result['conservative_prior_credits']==pytest.approx(1631.267958)
    assert result['guarded_settlements']==original['guarded_settlements']
    assert reconcile(result,snapshot,'hash')==result


@pytest.mark.parametrize('fault',['duration','identity','workers','floor','pending'])
def test_rejects_unsupported_reclassification(fault):
    ledger,snapshot=data()
    if fault=='duration': snapshot['deletedAt']='2026-10-20T00:40:00Z'
    if fault=='identity': snapshot['id']='someone-else'
    if fault=='workers': snapshot['computeConfig']['max']=2
    if fault=='floor': ledger['shared_account_decrease_credits']=1800
    if fault=='pending': ledger['unresolved_jobs']=['running']
    with pytest.raises(ValueError): reconcile(ledger,snapshot,'hash')


def test_h100_adjustment_preserves_storage_and_original_once():
    ledger,snapshot=data()
    ledger['conservative_prior_credits']=1916.267958
    ledger['storage_leases']={'owned':{'reserved_credits':5,'status':'deleted'}}
    ledger['guarded_settlements'][H100_EXECUTION]={
        'run_id':H100_RUN,'reserved_credits_counted':280,'actual_invoice':False,'deployment_id':'owned'}
    snapshot['computeConfig']['gpuClass']='h100-sxm'
    snapshot.update(createdAt='2026-10-20T06:18:32.220736Z',deletedAt='2026-10-20T06:23:03.326840Z')
    result=reconcile(ledger,snapshot,'hash',True)
    assert result['conservative_prior_credits']==pytest.approx(1776.267958)
    assert result['storage_leases']==ledger['storage_leases']
    assert result['guarded_settlements']==ledger['guarded_settlements']
    assert reconcile(result,snapshot,'hash',True)==result
    snapshot['deletedAt']='2026-10-20T06:24:00Z'
    with pytest.raises(ValueError): reconcile(ledger,snapshot,'hash',True)
