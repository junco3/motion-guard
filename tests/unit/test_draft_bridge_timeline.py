import json
import sys
import types
import uuid
from pathlib import Path
import numpy as np
import pytest
import comfy_nodes
from comfy_nodes.draft_bridge import MG_InspectDraft
from motionguard_core.report_artifact import read


class Images:
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return np.zeros((1,1,1,3),dtype=np.float32)


@pytest.mark.parametrize('valid_gt',[False,True])
def test_bridge_error_preserves_only_validated_axis(tmp_path,monkeypatch,valid_gt):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    def forbidden(*args,**kwargs): raise AssertionError('Pose inference must not execute')
    monkeypatch.setattr(comfy_nodes.MG_ExtractPose,'extract',forbidden)
    gt={'meta':{'frames':721,'fps':24},
        'frames':[{'frame':i,'time_s':i/24} for i in range(721)]} if valid_gt else {}
    run=str(uuid.uuid4())
    result=MG_InspectDraft().inspect(Images(),'unused.mp4',json.dumps(gt),run)['result'][0]
    assert result['report']['verdict']=='ERROR'
    assert result['stage_context']['timeline']==({'frames':721,'fps':24} if valid_gt else None)
    payload=read(tmp_path/'motion-guard'/run/'guard-result.png',run)
    assert payload['stage_context']==result['stage_context']


@pytest.mark.parametrize('width,height',[(768,512),(960,544)])
def test_bridge_encodes_both_supported_sizes(tmp_path,monkeypatch,width,height):
    import cv2
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    source=tmp_path/'reference.mp4'
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),24,(width,height))
    for _ in range(9):writer.write(np.zeros((height,width,3),np.uint8))
    writer.release()
    class Tensor(Images):
        def numpy(self):return np.zeros((9,height,width,3),np.float32)
    gt={'meta':{'frames':9,'fps':24,'width':width,'height':height},
        'frames':[{'frame':i,'time_s':i/24,'camera':{'width':width,'height':height}} for i in range(9)]}
    monkeypatch.setattr(comfy_nodes.MG_LoadReference,'load',lambda *a:({},))
    def reached_pose(self,ref,video,out):
        cap=cv2.VideoCapture(video)
        assert (int(cap.get(3)),int(cap.get(4)),int(cap.get(7)),cap.get(5))==(width,height,9,24)
        cap.release()
        raise RuntimeError('pose boundary reached')
    monkeypatch.setattr(comfy_nodes.MG_ExtractPose,'extract',reached_pose)
    result=MG_InspectDraft().inspect(Tensor(),str(source),json.dumps(gt),str(uuid.uuid4()))['result'][0]
    assert result['report']['error']=='pose boundary reached'


@pytest.mark.parametrize('width,height',[(None,544),(True,544),(960.0,544),(544,960),(1000,544)])
def test_bridge_rejects_invalid_dimensions(tmp_path,monkeypatch,width,height):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    gt={'meta':{'frames':9,'fps':24,'width':width,'height':height},
        'frames':[{'frame':i,'time_s':i/24} for i in range(9)]}
    result=MG_InspectDraft().inspect(Images(),'unused',json.dumps(gt),str(uuid.uuid4()))['result'][0]
    assert result['report']['error']=='Unsupported GT image dimensions'


@pytest.mark.parametrize('kind',['transposed','nan','range'])
def test_layout_bridge_rejects_bad_tensor(tmp_path,monkeypatch,kind):
    monkeypatch.setitem(sys.modules,'folder_paths',types.SimpleNamespace(get_output_directory=lambda:str(tmp_path)))
    class Tensor(Images):
        def numpy(self):
            a=np.zeros((9,960,544,3) if kind=='transposed' else (9,544,960,3),np.float32)
            if kind!='transposed':a.flat[0]=np.nan if kind=='nan' else 1.1
            return a
    gt={'meta':{'frames':9,'fps':24,'width':960,'height':544},
        'frames':[{'frame':i,'time_s':i/24} for i in range(9)]}
    result=MG_InspectDraft().inspect(Tensor(),'unused',json.dumps(gt),str(uuid.uuid4()))['result'][0]
    assert result['report']['error']=='Expected finite 9x544x960 RGB frames in [0,1]'
