import hashlib
import pytest
from comfy_nodes.stage_gate import permitted

@pytest.mark.parametrize('version,expected',[('mg-report-2',True),('mg-report-3',True),('mg-report-4',False)])
def test_versions_keep_fail_closed_sources(tmp_path,version,expected):
 sources={}
 for role in ('reference','generated','gt'):
  p=tmp_path/role;p.write_bytes(role.encode())
  sources[role]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 report={'schema_version':version,'verdict':'PASS','failures':[],'uncertain_reasons':[], 'metrics':{'observed':True},'sources':sources}
 envelope={'report':report,'stage_context':{'stage_id':'test','sources':sources}}
 assert permitted(envelope,'test') is expected
 report['verdict']='FAIL';report['display_failures']=[]
 assert not permitted(envelope,'test')
