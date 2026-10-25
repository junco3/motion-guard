"""Pinned audit graph: only Finalize can request any Stage2 computation."""
import copy
import hashlib
import json
from pathlib import Path

UP='5517/4975'
SAMPLE='5517/4971'

def digest(graph):
    value=copy.deepcopy(graph)
    value['mg_audit_init']['inputs']['graph_sha256']=''
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def ancestors(graph,node):
    seen=set()
    def visit(key):
        if key in seen:return
        seen.add(key)
        for value in graph[key]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in graph:
                visit(value[0])
    visit(node)
    return seen

def validate(graph):
    base=json.loads((Path(__file__).resolve().parents[1]/'workflows/T5/guarded-ltx-local-template.api.json').read_text(encoding='utf-8'))
    assert set(graph)==set(base)|{'mg_audit_init'}
    overrides={UP:'MG_AuditedUpsampler',SAMPLE:'MG_AuditedSampler','4852':'MG_FinalizeStage'}
    for key,value in base.items():
        assert graph[key]['class_type']==overrides.get(key,value['class_type'])
    assert graph['mg_audit_init']['class_type']=='MG_InitStageAudit'
    assert graph['mg_audit_init']['inputs']['graph_sha256']==digest(graph)
    assert graph['4852']=={'class_type':'MG_FinalizeStage','inputs':{
        'report':['mg_inspect',0],'run_id':['mg_audit_init',0],'video':['5518/4849',0]}}
    for key,kind in ((UP,'MG_AuditedUpsampler'),(SAMPLE,'MG_AuditedSampler')):
        assert graph[key]['class_type']==kind
        assert graph[key]['inputs']['run_id']==['mg_audit_init',0]
        assert key in ancestors(graph,'4852')
    assert graph[UP]['inputs']['samples']==['mg_gate',0]
    for output in ('diag_save','mg_inspect'):
        assert not ({UP,SAMPLE}&ancestors(graph,output))
    # A fixed graph contract prevents an unaudited extra output path.
    allowed={'SaveVideo':{'diag_save'},'MG_InspectDraft':{'mg_inspect'},'MG_FinalizeStage':{'4852'}}
    for kind,ids in allowed.items():
        assert {k for k,v in graph.items() if v['class_type']==kind}==ids
    assert not any(v['class_type'] in ('PreviewImage','SaveImage','SaveLatent','MG_Report') for v in graph.values())
    return True

def upgrade(graph):
    graph=copy.deepcopy(graph)
    graph['mg_audit_init']={'class_type':'MG_InitStageAudit','inputs':{
        'run_id':['mg_bind',1],'graph_sha256':''}}
    graph['mg_inspect']['inputs']['run_id']=['mg_audit_init',0]
    graph['mg_gate']['inputs']['stage_id']=['mg_audit_init',0]
    for key,kind in ((UP,'MG_AuditedUpsampler'),(SAMPLE,'MG_AuditedSampler')):
        graph[key]['class_type']=kind
        graph[key]['inputs']['run_id']=['mg_audit_init',0]
    graph['4852']={'class_type':'MG_FinalizeStage','inputs':{
        'report':['mg_inspect',0],'run_id':['mg_audit_init',0],'video':['5518/4849',0]}}
    graph['mg_audit_init']['inputs']['graph_sha256']=digest(graph)
    validate(graph)
    return graph
