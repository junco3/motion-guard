import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from import_platform_guard import verified_wire_gt

@pytest.mark.parametrize('change',['none','original','workflow','execution','existing','remote'])
def test_only_exact_wire_content_is_recovered(tmp_path,change):
    raw=b'{\r\n "frames": []\r\n}'
    wire=raw.replace(b'\r\n',b'\n')
    (tmp_path/'joints.json').write_bytes(raw)
    workflow=tmp_path/'workflow.api.json'
    workflow.write_bytes(json.dumps({'mg_inspect':{'inputs':{'gt_json':wire.decode()}}}).encode())
    plan={'execution_id':'run','input_hashes':{'workflow.api.json':hashlib.sha256(workflow.read_bytes()).hexdigest()}}
    (tmp_path/'execution-plan.json').write_text(json.dumps(plan))
    digest=hashlib.sha256(wire).hexdigest()
    if change=='original':(tmp_path/'joints.json').write_bytes(b'{}')
    if change=='workflow':workflow.write_bytes(b'{}')
    if change=='existing':(tmp_path/'joints.wire.json').write_bytes(b'{}')
    if change=='remote':digest='0'*64
    args=(tmp_path,'joints.json',digest,'other' if change=='execution' else 'run')
    if change=='none':
        assert verified_wire_gt(*args)=='joints.wire.json'
        assert (tmp_path/'joints.wire.json').read_bytes()==wire
        assert (tmp_path/'joints.json').read_bytes()==raw
        assert verified_wire_gt(*args)=='joints.wire.json'
    else:
        with pytest.raises(ValueError):verified_wire_gt(*args)
