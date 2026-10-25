"""CPU dependency probes, deliberately NOT real Stage1/Stage2 generation."""
import json
from pathlib import Path
def event(log,name,**extra):
    with Path(log).open('a',encoding='utf-8') as f:f.write(json.dumps(dict(event=name,**extra))+'\n')
class ProbeReport:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'path':('STRING',),'stage_id':('STRING',),'mode':('STRING',),'log':('STRING',)}}
    RETURN_TYPES=('MG_REPORT',);FUNCTION='run';CATEGORY='test'
    def run(self,path,stage_id,mode,log):
        import motionguard_core.compare as core
        event(log,'report',core_file=core.__file__)
        if mode=='exception':raise RuntimeError('Intentional Guard exception probe')
        report=json.loads(Path(path).read_text(encoding='utf-8'))
        if mode=='error':report['verdict']='ERROR'
        if mode=='malformed':report={'verdict':'PASS'}
        context={'stage_id':stage_id,'sources':report.get('sources')}
        if mode=='stale':context['stage_id']='old-run'
        return ({'report':report,'stage_context':context},)
class ProbeLatent:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'stage_id':('STRING',),'mode':('STRING',),'log':('STRING',)}}
    RETURN_TYPES=('LATENT',);FUNCTION='run';CATEGORY='test'
    def run(self,stage_id,mode,log):
        import torch
        event(log,'latent_preparation')
        return ({'samples':torch.zeros((1,4,2,2)),'motion_guard_stage_id':'wrong' if mode=='latent_mismatch' else stage_id},)
class ProbeDownstream:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'latent':('LATENT',),'log':('STRING',)}}
    RETURN_TYPES=();FUNCTION='run';CATEGORY='test';OUTPUT_NODE=True
    def run(self,latent,log):
        event(log,'downstream',stage_id=latent['motion_guard_stage_id'],sample_sum=float(latent['samples'].sum()))
        return {'ui':{'text':['CPU downstream executed']}}
NODE_CLASS_MAPPINGS={c.__name__:c for c in [ProbeReport,ProbeLatent,ProbeDownstream]}
