import copy
import json
import uuid
import pytest
from motionguard_core.report_artifact import write, read, validate, digest, digest_encoding


def report():
    r={'schema_version':'mg-report-2','verdict':'PASS','failures':[],
       'uncertain_reasons':[], 'metrics':{'M4_timing':{'per_joint':{2:{'lag_s':0.0},10:{'lag_s':0.1}}}}}
    r['observation_policy']={'strict_report':copy.deepcopy(r)}
    return r


def legacy():
    r=report()
    return json.loads(json.dumps({'schema':'motion-guard-artifact-1','run_id':str(uuid.uuid4()),
                                 'report':r,'report_sha256':digest(r)}))


def test_integer_keys_roundtrip(tmp_path):
    p=tmp_path/'result.png'; run=str(uuid.uuid4())
    payload=write(p,report(),{'timeline':{'frames':97,'fps':24}},run)
    assert read(p,run)==payload
    assert digest_encoding(payload['report'],payload['report_sha256'])=='json-string-keys'


def test_legacy_exact_digest():
    payload=legacy()
    assert validate(payload,payload['run_id'])==payload
    assert digest_encoding(payload['report'],payload['report_sha256'])=='legacy-integer-joint-keys'


@pytest.mark.parametrize('change',['number','other_field','noncanonical_key'])
def test_legacy_tamper_rejected(change):
    payload=legacy(); r=payload['report']
    if change=='number':r['metrics']['M4_timing']['per_joint']['2']['lag_s']=0.5
    elif change=='other_field':r['extra']='changed'
    else:r['metrics']['M4_timing']['per_joint']['02']=r['metrics']['M4_timing']['per_joint'].pop('2')
    with pytest.raises(ValueError,match='digest mismatch'):validate(payload,payload['run_id'])


@pytest.mark.parametrize('version,ok', [('mg-report-2', True), ('mg-report-3', True), ('mg-report-4', False)])
def test_carrier_accepts_the_versions_the_gate_accepts(tmp_path, version, ok):
    # The comparator writes mg-report-3; the in-graph carrier must accept what stage_gate accepts.
    r = report(); r['schema_version'] = version; run = str(uuid.uuid4())
    if ok:
        assert write(tmp_path/'r.png', r, {'timeline': {'frames': 97, 'fps': 24}}, run)['report']['schema_version'] == version
    else:
        with pytest.raises(ValueError):
            write(tmp_path/'r.png', r, {'timeline': {'frames': 97, 'fps': 24}}, run)
