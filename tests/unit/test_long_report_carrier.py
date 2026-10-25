import copy
import json
import uuid
import pytest
from motionguard_core.report_artifact import write, read, validate, digest, MAX_BYTES


def failed():
    return {'schema_version':'mg-report-2','verdict':'FAIL','failures':[
        {'type':'motion_omission','frames':[720,720],'t_start_s':30,
         't_end_s':721/24,'evidence':{'joint':10}}]}


def test_long_last_frame_roundtrip(tmp_path):
    run=str(uuid.uuid4())
    pose={'frames':721,'fps':24,'points':[[[0.123456789,0.987654321]]*18]*721,
          'scores':[[0.987654321]*18]*721,'people':[1]*721}
    path=tmp_path/'result.png'
    payload=write(path,failed(),{'timeline':{'frames':721,'fps':24}},run,{'r':pose,'g':pose})
    assert len(json.dumps(payload).encode())>512_000
    assert len(json.dumps(payload).encode())<MAX_BYTES
    assert read(path,run)==payload


@pytest.mark.parametrize('axis',[None,{}, {'frames':True,'fps':24},
    {'frames':721,'fps':True},{'frames':721,'fps':30},{'frames':722,'fps':24}])
def test_invalid_axis_rejected(tmp_path,axis):
    with pytest.raises(ValueError,match='timeline'):
        write(tmp_path/'bad.png',failed(),{'timeline':axis},str(uuid.uuid4()))


def test_new_schema_never_defaults_to_97(tmp_path):
    with pytest.raises(ValueError,match='timeline'):
        write(tmp_path/'bad.png',failed(),{},str(uuid.uuid4()))


def test_past_last_frame_rejected(tmp_path):
    report=failed();report['failures'][0].update(frames=[721,721],t_start_s=721/24,t_end_s=722/24)
    with pytest.raises(ValueError,match='interval'):
        write(tmp_path/'bad.png',report,{'timeline':{'frames':721,'fps':24}},str(uuid.uuid4()))


def test_observations_must_match_axis(tmp_path):
    pose={'frames':97,'fps':24,'points':[],'scores':[],'people':[]}
    with pytest.raises(ValueError,match='Observation'):
        write(tmp_path/'bad.png',failed(),{'timeline':{'frames':721,'fps':24}},str(uuid.uuid4()),{'r':pose,'g':pose})


def test_invalid_input_error_has_no_invented_axis(tmp_path):
    run=str(uuid.uuid4());report={'schema_version':'mg-report-2','verdict':'ERROR','failures':[],'error':'invalid GT'}
    p=tmp_path/'error.png'
    write(p,report,{'timeline':None},run)
    assert read(p,run)['stage_context']['timeline'] is None


def test_legacy_97_still_valid():
    report=failed();report['failures'][0].update(frames=[96,96],t_start_s=4,t_end_s=97/24)
    payload={'schema':'motion-guard-artifact-1','run_id':str(uuid.uuid4()),'report':report,'report_sha256':digest(report)}
    assert validate(copy.deepcopy(payload),payload['run_id'])==payload
