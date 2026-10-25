"""Decode-to-inspection bridge; execution identity follows the same latent edge."""
import json,uuid,shutil,subprocess,os
from pathlib import Path
import numpy as np

REPAIRS={}  # run_id -> latent cells replaced by MG_BindStage, reported by MG_InspectDraft

class MG_BindStage:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'latent':('LATENT',),'run_id':('STRING',)}}
    RETURN_TYPES=('LATENT','STRING');FUNCTION='bind';CATEGORY='MotionGuard'
    def bind(self,latent,run_id):
        uuid.UUID(run_id)
        # Both the draft decode and Stage2 read this latent, so a repaired spike is gone from both.
        from motionguard_core.latent_repair import repair,METHOD
        samples=latent['samples'];records=[]
        if samples.ndim==5 and samples.shape[0]==1:
            fixed,records=repair(samples[0].detach().float().cpu().numpy())
            if records:
                import torch
                samples=torch.from_numpy(fixed).to(samples.device,samples.dtype).unsqueeze(0)
        REPAIRS[run_id]={'method':METHOD,'cells':records}
        return ({**latent,'samples':samples,'motion_guard_stage_id':run_id},run_id)

class MG_InspectDraft:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'reference_video':('STRING',),'gt_json':('STRING',{'multiline':True}),'run_id':('STRING',)}}
    RETURN_TYPES=('MG_REPORT',);FUNCTION='inspect';CATEGORY='MotionGuard';OUTPUT_NODE=True
    def inspect(self,images,reference_video,gt_json,run_id):
        import folder_paths,cv2
        from . import MG_LoadReference,MG_ExtractPose,MG_Compare
        uuid.UUID(run_id)
        folder=Path(folder_paths.get_output_directory())/'motion-guard'/run_id
        folder.mkdir(parents=True,exist_ok=False)
        context={'stage_id':run_id,'timeline':None,'latent_repairs':REPAIRS.pop(run_id,None)}
        try:
            from motionguard_core.reference_io import validate_timeline
            gt=json.loads(gt_json)
            axis=validate_timeline(gt)
            context['timeline']={'frames':axis['frames'],'fps':axis['fps']}
            n=axis['frames']
            width,height=gt['meta'].get('width'),gt['meta'].get('height')
            if type(width) is not int or type(height) is not int or (width,height) not in ((768,512),(960,544)):
                raise ValueError('Unsupported GT image dimensions')
            a=images.detach().cpu().numpy()
            if a.shape!=(n,height,width,3) or not np.isfinite(a).all() or a.min()<0 or a.max()>1:
                raise ValueError(f'Expected finite {n}x{height}x{width} RGB frames in [0,1]')
            source=Path(reference_video)
            if not source.is_file():source=Path(folder_paths.get_annotated_filepath(reference_video))
            cap=cv2.VideoCapture(str(source));shape=(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),cap.get(cv2.CAP_PROP_FPS),int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)));cap.release()
            if shape!=(n,24,width,height):raise ValueError('Reference timeline or dimensions mismatch')
            for f in gt['frames']:
                if f['camera']['width']!=width or f['camera']['height']!=height:raise ValueError('GT camera dimensions mismatch')
            (folder/'joints.json').write_text(gt_json,encoding='utf-8')
            shutil.copyfile(source,folder/'reference.mp4')
            ref=MG_LoadReference().load(str(folder))[0]
            rgb=np.rint(a*255).astype(np.uint8)
            executable=shutil.which('ffmpeg')
            if executable is None:
                import imageio_ffmpeg
                executable=imageio_ffmpeg.get_ffmpeg_exe()
            args=[executable,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r','24','-i','pipe:0','-an','-c:v','libx264rgb','-crf','0','-pix_fmt','rgb24',str(folder/'generated.mp4')]
            subprocess.run(args,input=rgb.tobytes(),check=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            poses=MG_ExtractPose().extract(ref,str(folder/'generated.mp4'),str(folder))[0]
            result=MG_Compare().compare(poses)[0]
            result['stage_context']={**context,'sources':result['report']['sources'],'encoding':'RGB float rounded to uint8; libx264rgb CRF0 rgb24, 24fps; no frame resampling or RGB-to-YUV conversion'}
            (folder/'stage-context.json').write_text(json.dumps(result['stage_context'],indent=2),encoding='utf-8')
        except Exception as exc:
            report={'schema_version':'mg-report-2','verdict':'ERROR','failures':[],'error':str(exc)}
            (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            result={'report':report,'stage_context':context,'out':str(folder)}
        from motionguard_core.report_artifact import write
        observations={k:result[k] for k in ('r','g')} if 'r' in result and 'g' in result else None
        write(folder/'guard-result.png',result['report'],result['stage_context'],run_id,observations)
        artifacts=[{'filename':'guard-result.png','subfolder':'motion-guard/'+run_id,'type':'output'}]
        if (folder/'generated.mp4').is_file():
            artifacts.append({'filename':'generated.mp4','subfolder':'motion-guard/'+run_id,'type':'output'})
        return {'ui':{'images':artifacts,
                      'text':[json.dumps({'run_id':run_id,'verdict':result['report']['verdict'],'report':str(folder/'report.json')})]},'result':(result,)}
