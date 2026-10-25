import sys,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app

def setup(tmp_path,monkeypatch,balance=9663.6):
    monkeypatch.setattr(app,'ROOT',tmp_path)
    ledger=tmp_path/'ledger.json';monkeypatch.setattr(app,'LEDGER',ledger)
    app.save(ledger,{'credential_sha256':'bound','billing_baseline_cents':10000,'credits_per_cent':2.11})
    app.save(tmp_path/'config/budget.yaml',{'max_total_credits':10000})
    path=tmp_path/'data/billing-display.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'credential_sha256':'bound','baseline_cents':10000,'credits_per_cent':2.11,'balance_cents':balance,'as_of':'verified'}),encoding='utf8')
    return path

def test_balance_debit_and_reference_headroom_are_separate(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch);r=app.billing_display()
    assert r['account_balance_credits']==pytest.approx(20390.196)
    assert r['account_decrease_credits']==pytest.approx(709.804)
    assert r['authorized_remaining_after_verified_debit']==pytest.approx(9290.196)
    assert r['reservation_is_spending'] is False

def test_topup_keeps_known_balance_but_not_invented_debit(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch,11000);r=app.billing_display()
    assert r['account_balance_credits']==23210
    assert r['account_decrease_credits'] is None and r['authorized_remaining_after_verified_debit'] is None

@pytest.mark.parametrize('balance',[None,-1,float('nan'),float('inf')])
def test_invalid_balance_is_unknown(tmp_path,monkeypatch,balance):
    setup(tmp_path,monkeypatch,balance);assert app.billing_display()['account_balance_credits'] is None

def test_wrong_binding_is_unknown(tmp_path,monkeypatch):
    p=setup(tmp_path,monkeypatch);s=app.read(p);s['credential_sha256']='other';app.save(p,s)
    assert app.billing_display()['status']=='unavailable'

def test_headroom_stops_at_zero(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch,0);assert app.billing_display()['authorized_remaining_after_verified_debit']==0
