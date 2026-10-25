import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app,provision

@pytest.fixture
def fresh(tmp_path,monkeypatch):
    app.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':False})
    app.save(tmp_path/'config/t1-spend-ledger.json',{'conservative_prior_credits':0,'known_runs':[],'unresolved_jobs':[]})
    monkeypatch.setattr(app,'key',lambda:'fixture-key')
    monkeypatch.setattr(app,'api',lambda *args:{'summary':{'balance':{'cloud_credit_balance_cents':321}}})
    return tmp_path

def test_first_use_then_refuse_reset(fresh):
    assert provision.provision(fresh,1000)['submitted_jobs']==0
    p=fresh/'config/t1-spend-ledger.json';ledger=app.read(p)
    assert ledger['billing_baseline_cents']==321
    assert app.cumulative_prior(ledger,320,'fixture-key')==2.11
    with pytest.raises(ValueError):provision.provision(fresh,1000)
    assert app.read(p)==ledger
    with pytest.raises(ValueError):app.cumulative_prior(ledger,320,'different-key')
    ledger['conservative_prior_credits']=459.067958
    assert app.cumulative_prior(ledger,400,'fixture-key')==459.067958

@pytest.mark.parametrize('value',[None,-1,float('nan'),float('inf'),True])
def test_invalid_billing_never_enables(fresh,monkeypatch,value):
    monkeypatch.setattr(app,'api',lambda *args:{'summary':{'balance':{'cloud_credit_balance_cents':value}}})
    with pytest.raises(ValueError):provision.provision(fresh,1000)
    assert app.read(fresh/'config/budget.yaml')['allow_paid_execution'] is False

def test_partial_write_preserves_closed_budget_and_baseline(fresh,monkeypatch):
    original=app.save
    def fail_budget(p,v):
        if p.name=='budget.yaml':raise PermissionError('fixture')
        original(p,v)
    monkeypatch.setattr(app,'save',fail_budget)
    with pytest.raises(PermissionError):provision.provision(fresh,1000)
    assert app.read(fresh/'config/budget.yaml')['allow_paid_execution'] is False
    before=app.read(fresh/'config/t1-spend-ledger.json')
    with pytest.raises(ValueError):provision.provision(fresh,1000)
    assert app.read(fresh/'config/t1-spend-ledger.json')==before

def test_existing_history_and_parallel_provision_are_preserved(fresh):
    marker=fresh/'config/provision.lock';marker.write_text('other')
    with pytest.raises(FileExistsError):provision.provision(fresh,1000)
    assert marker.read_text()=='other'
    marker.unlink()
    runs=fresh/'data/gen';runs.mkdir(parents=True);(runs/'existing').mkdir()
    with pytest.raises(ValueError):provision.provision(fresh,1000)
    assert app.read(fresh/'config/budget.yaml')['allow_paid_execution'] is False
