"""Local Motion Guard node package. Engine loading must be verified separately."""
import json, hashlib
from pathlib import Path


class MG_LoadReference:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'directory':('STRING',{'default':''})},'optional':{'gt_file':('STRING',{'default':'joints.json'})}}
    RETURN_TYPES=('MG_REFERENCE',);FUNCTION='load';CATEGORY='MotionGuard'
    def load(self,directory,gt_file='joints.json'):
        p=Path(directory);gp=p/gt_file;raw=gp.read_bytes();gt=json.loads(raw)
        from motionguard_core.reference_io import project_world,finite
        import numpy as np
        if not finite(gt['frames']):raise ValueError('Nonfinite GT')
        for i,frame in enumerate(gt['frames']):
            if frame['frame']!=i or abs(frame['time_s']-i/24)>1e-6:raise ValueError('GT timeline mismatch')
            for joint in frame['joints']:
                if joint.get('available') and np.linalg.norm(project_world(joint['world'],frame['camera'])-joint['pixel'])>=1:
                    raise ValueError('GT reprojection mismatch')
        video=next((p/n for n in ['reference.mp4','ref_textured.mp4'] if (p/n).is_file()),None)
        if video is None:raise ValueError('Missing reference video')
        # Finger ground truth for runs exported before hands were recorded: a separate, frame-aligned file.
        hands_path=p/'joints.hands.json';hands_sha=None
        if hands_path.is_file() and not any('hands' in f for f in gt['frames']):
            hraw=hands_path.read_bytes();hands=json.loads(hraw)['frames'];hands_sha=hashlib.sha256(hraw).hexdigest()
            if len(hands)<len(gt['frames']) or any(h['frame']!=i for i,h in enumerate(hands[:len(gt['frames'])])):raise ValueError('Hand GT timeline mismatch')
            for f,h in zip(gt['frames'],hands):f['hands']=h['hands']
        return ({'directory':str(p),'gt':gt,'gt_path':str(gp.resolve()),'gt_sha256':hashlib.sha256(raw).hexdigest(),'video':str(video),
                 **({'gt_hands_path':str(hands_path.resolve()),'gt_hands_sha256':hands_sha} if hands_sha else {})},)


class MG_ExtractPose:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'reference':('MG_REFERENCE',),'generated_video':('STRING',),'output_directory':('STRING',)}}
    RETURN_TYPES=('MG_POSES',);FUNCTION='extract';CATEGORY='MotionGuard'
    def extract(self,reference,generated_video,output_directory):
        from motionguard_core.estimator import make_estimator,extract
        out=Path(output_directory);model=make_estimator()
        r=extract(reference['video'],out/'reference-pose.json',model);g=extract(generated_video,out/'generated-pose.json',model)
        return ({'reference':reference,'r':r,'g':g,'generated_video':generated_video,'out':str(out)},)


class MG_Compare:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'poses':('MG_POSES',)}}
    RETURN_TYPES=('MG_REPORT',);FUNCTION='compare';CATEGORY='MotionGuard'
    def compare(self,poses):
        from motionguard_core.observation_candidate import compare_candidate as compare
        report=compare(poses['r'],poses['g'],poses['reference']['gt']);out=Path(poses['out']);out.mkdir(parents=True,exist_ok=True)
        report['sources']={label:{'path':str(Path(value).resolve()),'sha256':hashlib.sha256(Path(value).read_bytes()).hexdigest()} for label,value in [('reference',poses['reference']['video']),('generated',poses['generated_video']),('gt',poses['reference']['gt_path'])]}
        if poses['reference'].get('gt_hands_path'):report['finger_gt_source']={'path':poses['reference']['gt_hands_path'],'sha256':poses['reference']['gt_hands_sha256']}
        if report['sources']['gt']['sha256']!=poses['reference']['gt_sha256']:raise ValueError('GT changed after loading')
        report['versions']={'primary_estimator':poses['r']['estimator'],'settings':poses['r']['settings'],'gt_visibility':poses['reference']['gt'].get('meta',{}).get('visibility_method')}
        (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        return ({**poses,'report':report},)


class MG_Report:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'report':('MG_REPORT',)}}
    RETURN_TYPES=('STRING',);FUNCTION='render';CATEGORY='MotionGuard';OUTPUT_NODE=True
    def render(self,report):
        from motionguard_core.report import render
        path=render(report['reference']['video'],report['generated_video'],report['out'])
        return {'ui':{'text':[report['report']['verdict'],path]},'result':(path,)}


NODE_CLASS_MAPPINGS={cls.__name__:cls for cls in [MG_LoadReference,MG_ExtractPose,MG_Compare,MG_Report]}
NODE_DISPLAY_NAME_MAPPINGS={name:name.replace('_',' ') for name in NODE_CLASS_MAPPINGS}
from .stage_gate import MG_StageGate
NODE_CLASS_MAPPINGS['MG_StageGate']=MG_StageGate
NODE_DISPLAY_NAME_MAPPINGS['MG_StageGate']='Motion Guard Stage Gate'
from .draft_bridge import MG_BindStage,MG_InspectDraft
for cls in [MG_BindStage,MG_InspectDraft]:
    NODE_CLASS_MAPPINGS[cls.__name__]=cls
    NODE_DISPLAY_NAME_MAPPINGS[cls.__name__]=cls.__name__.replace('_',' ')
from .stage_audit import NODE_CLASS_MAPPINGS as AUDIT_NODES
NODE_CLASS_MAPPINGS.update(AUDIT_NODES)
