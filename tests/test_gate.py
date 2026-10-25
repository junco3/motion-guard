import pytest
from jsonschema.exceptions import ValidationError
from motionguard_core.gate import simulate,paid_execution_allowed
@pytest.mark.parametrize('verdict,count',[('PASS',1),('FAIL',0),('UNCERTAIN',0),('ERROR',0)])
def test_states(verdict,count):
    calls=[]
    simulate({'verdict':verdict},lambda:calls.append(1))
    assert len(calls)==count
@pytest.mark.parametrize('report',[{}, {'verdict':'pass'},{'verdict':'DONE'},{'verdict':'PASS','extra':1}])
def test_invalid(report):
    calls=[]
    with pytest.raises(ValidationError): simulate(report,lambda:calls.append(1))
    assert calls==[]
def test_budget():
    assert not paid_execution_allowed({})
    assert not paid_execution_allowed({'allow_paid_execution':True,'max_total_charge':0})
def test_failure():
    def broken(): raise RuntimeError('stub')
    with pytest.raises(RuntimeError): simulate({'verdict':'PASS'},broken)
