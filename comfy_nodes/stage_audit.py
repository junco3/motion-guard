"""Execution-bound Stage2 entry records and a single lazy final-output root."""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from .stage_gate import permitted


def directory(run_id):
    import folder_paths
    uuid.UUID(run_id)
    return Path(folder_paths.get_output_directory())/'motion-guard-audit'/run_id


def durable(path, value, mode='x'):
    with path.open(mode, encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, sort_keys=True)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def manifest(run_id):
    path=directory(run_id)
    value=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if value['run_id']!=run_id or value['code_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Stage audit identity changed')
    if not (path/'events.jsonl').is_file():
        raise ValueError('Missing initialized event stream')
    return path,value


def invoke(run_id, stage, fn, **inputs):
    path,_=manifest(run_id)
    durable(path/'events.jsonl',{'stage':stage,'event':'entered','run_id':run_id},'a')
    result=fn(**inputs)
    durable(path/'events.jsonl',{'stage':stage,'event':'completed','run_id':run_id},'a')
    return result


class MG_InitStageAudit:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'run_id':('STRING',),'graph_sha256':('STRING',)}}
    RETURN_TYPES=('STRING',);FUNCTION='initialize';CATEGORY='MotionGuard'
    def initialize(self,run_id,graph_sha256):
        if not re.fullmatch(r'[0-9a-f]{64}',graph_sha256):raise ValueError('Invalid graph pin')
        path=directory(run_id);path.mkdir(parents=True,exist_ok=False)
        durable(path/'events.jsonl',{'event':'initialized','run_id':run_id})
        durable(path/'manifest.json',{'run_id':run_id,'graph_sha256':graph_sha256,
            'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        return (run_id,)


class MG_AuditedUpsampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'samples':('LATENT',),'upscale_model':('LATENT_UPSCALE_MODEL',),
                            'vae':('VAE',),'run_id':('STRING',)}}
    RETURN_TYPES=('LATENT',);FUNCTION='execute';CATEGORY='MotionGuard'
    def execute(self,samples,upscale_model,vae,run_id):
        from comfy_extras.nodes_lt_upsampler import LTXVLatentUpsampler
        result=invoke(run_id,'upsampler',LTXVLatentUpsampler.execute,
                      samples=samples,upscale_model=upscale_model,vae=vae)
        return tuple(result.result)


class MG_AuditedSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'noise':('NOISE',),'guider':('GUIDER',),'sampler':('SAMPLER',),
                            'sigmas':('SIGMAS',),'latent_image':('LATENT',),'run_id':('STRING',)}}
    RETURN_TYPES=('LATENT','LATENT');FUNCTION='execute';CATEGORY='MotionGuard'
    def execute(self,noise,guider,sampler,sigmas,latent_image,run_id):
        from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
        result=invoke(run_id,'sampler',SamplerCustomAdvanced.execute,
                      noise=noise,guider=guider,sampler=sampler,sigmas=sigmas,latent_image=latent_image)
        return tuple(result.result)


class MG_FinalizeStage:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'report':('MG_REPORT',),'run_id':('STRING',),
                            'video':('VIDEO',{'lazy':True})}}
    RETURN_TYPES=();FUNCTION='finalize';CATEGORY='MotionGuard';OUTPUT_NODE=True
    def check_lazy_status(self,report,run_id,video=None):
        manifest(run_id)
        return ['video'] if permitted(report,run_id) and video is None else []
    def finalize(self,report,run_id,video=None):
        path,pin=manifest(run_id)
        rows=[json.loads(line) for line in (path/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        if not rows or rows[0]!={'event':'initialized','run_id':run_id}:
            raise ValueError('Audit stream was not initialized')
        if any(row.get('run_id')!=run_id for row in rows):raise ValueError('Mixed execution audit')
        entered=[r['stage'] for r in rows if r['event']=='entered']
        completed=[r['stage'] for r in rows if r['event']=='completed']
        allow=permitted(report,run_id)
        artifacts=[]
        if allow:
            if video is None or entered!=['upsampler','sampler'] or completed!=entered:
                raise ValueError('Missing actual Stage2 execution records')
            from comfy_api.latest._util.video_types import VideoContainer,VideoCodec
            video.save_to(str(path/'stage2.mp4'),format=VideoContainer('mp4'),codec=VideoCodec('h264'))
            artifacts.append({'filename':'stage2.mp4','subfolder':'motion-guard-audit/'+run_id,'type':'output'})
        elif entered or completed or video is not None:
            raise ValueError('Stage2 executed despite a held draft')
        audit={**pin,'initialized':True,'entered':entered,'completed':completed,
               'guard_verdict':report.get('report',{}).get('verdict'),'held':not allow}
        durable(path/'audit.json',audit)
        from motionguard_core.report_artifact import write
        context={**report.get('stage_context',{}),'stage_audit':audit}
        write(path/'stage-audit.png',report['report'],context,run_id)
        artifacts.append({'filename':'stage-audit.png','subfolder':'motion-guard-audit/'+run_id,'type':'output'})
        return {'ui':{'images':artifacts}}


NODE_CLASS_MAPPINGS={c.__name__:c for c in
    (MG_InitStageAudit,MG_AuditedUpsampler,MG_AuditedSampler,MG_FinalizeStage)}
