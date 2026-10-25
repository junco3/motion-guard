"""Official Layout graph plus a lazy Guard boundary; no remote submission."""
import copy
import json
import uuid
from pathlib import Path
from stage_audit_graph import digest, ancestors

ROOT = Path(__file__).resolve().parents[1]
UP = '9034/9025'
SAMPLE = '9034/9033'
CROP = ['5516/5000', 2]


def build(run_id, image, layout, reference, gt_json, prompt, seed):
    uuid.UUID(run_id)
    g = json.loads((ROOT/'workflows/T1/layout-i2v.api.json').read_text(encoding='utf-8'))
    g['9009']['inputs']['image'] = image
    g['5001']['inputs']['file'] = layout
    g['5014/2483']['inputs']['text'] = prompt
    for node in ('5516/4832', '9034/9031'):
        g[node]['inputs']['noise_seed'] = seed
    g['mg_bind'] = {'class_type': 'MG_BindStage', 'inputs': {'latent': CROP.copy(), 'run_id': run_id}}
    g['mg_audit_init'] = {'class_type': 'MG_InitStageAudit', 'inputs': {'run_id': ['mg_bind', 1], 'graph_sha256': ''}}
    g['diag_decode'] = copy.deepcopy(g['5518/5538'])
    g['diag_decode']['inputs']['samples'] = ['mg_bind', 0]
    g['diag_video'] = copy.deepcopy(g['5518/4849'])
    g['diag_video']['inputs']['images'] = ['diag_decode', 0]
    g['diag_save'] = copy.deepcopy(g['4852'])
    g['diag_save']['inputs'].update(video=['diag_video', 0], filename_prefix='motion-guard-draft')
    g['mg_inspect'] = {'class_type': 'MG_InspectDraft', 'inputs': {
        'images': ['diag_decode', 0], 'reference_video': reference,
        'gt_json': gt_json, 'run_id': ['mg_audit_init', 0]}}
    g['mg_gate'] = {'class_type': 'MG_StageGate', 'inputs': {
        'report': ['mg_inspect', 0], 'stage_id': ['mg_audit_init', 0], 'latent': ['mg_bind', 0]}}
    g[UP]['inputs']['samples'] = ['mg_gate', 0]
    for node, kind in ((UP, 'MG_AuditedUpsampler'), (SAMPLE, 'MG_AuditedSampler')):
        g[node]['class_type'] = kind
        g[node]['inputs']['run_id'] = ['mg_audit_init', 0]
    g['4852'] = {'class_type': 'MG_FinalizeStage', 'inputs': {
        'report': ['mg_inspect', 0], 'run_id': ['mg_audit_init', 0], 'video': ['5518/4849', 0]}}
    g['mg_audit_init']['inputs']['graph_sha256'] = digest(g)
    return g


def validate(g):
    # Rebuild from the official graph and compare every connection/value. Only
    # explicit request data may vary; a caller cannot authorize a bypass by hashing it.
    expected = build(g['mg_bind']['inputs']['run_id'], g['9009']['inputs']['image'],
                     g['5001']['inputs']['file'], g['mg_inspect']['inputs']['reference_video'],
                     g['mg_inspect']['inputs']['gt_json'], g['5014/2483']['inputs']['text'],
                     g['5516/4832']['inputs']['noise_seed'])
    if g != expected:
        raise ValueError('Layout graph differs from official guarded contract')
    for output in ('diag_save', 'mg_inspect'):
        if {UP, SAMPLE} & ancestors(g, output):
            raise ValueError('Stage2 reachable from unconditional output')
    if 'mg_gate' not in ancestors(g, SAMPLE):
        raise ValueError('Layout Stage2 bypasses Guard')
    return True
