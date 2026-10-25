"""Same CPU RTMPose settings for reference and generated video; no GUI."""
import os, json, hashlib, importlib.metadata, time
from pathlib import Path
import numpy as np
import cv2

ROOT=Path(__file__).resolve().parents[2]
NAMES=['nose','neck','right_shoulder','right_elbow','right_wrist','left_shoulder','left_elbow','left_wrist','right_hip','right_knee','right_ankle','left_hip','left_knee','left_ankle','right_eye','left_eye','right_ear','left_ear']
# COCO17 anatomical labels to the exporter OpenPose18 layout.
COCO=[0,None,6,8,10,5,7,9,12,14,16,11,13,15,2,1,4,3]

def staged_mode():
    import sys
    registry=sys.modules.get('folder_paths')
    has_registered=bool(registry and 'motion_guard' in registry.folder_names_and_paths)
    return 'MG_MODEL_DIR' in os.environ or os.environ.get('MG_STAGED_REQUIRED')=='1' or has_registered

def make_estimator():
    os.environ['TORCH_HOME']=str(ROOT/'data/models/rtmpose')
    from rtmlib import Body
    import sys
    registry=sys.modules.get('folder_paths')
    has_registered=bool(registry and 'motion_guard' in registry.folder_names_and_paths)
    if staged_mode():
        from .staged_models import prepare,resolve_directory
        registered=registry.get_folder_paths('motion_guard') if has_registered else []
        directory=resolve_directory(registered,os.environ.get('MG_MODEL_DIR'))
        paths=prepare(directory,ROOT/'data/models/rtmpose/staged')
        return Body(det=paths['det'],pose=paths['pose'],det_input_size=(640,640),
                    pose_input_size=(192,256),to_openpose=False,backend='onnxruntime',device='cpu')
    return Body(mode='balanced',to_openpose=False,backend='onnxruntime',device='cpu')

HAND_MODEL=ROOT/'data/models/rtmw/end2end.onnx'
HAND_URL='https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122.zip'
HAND_SETTINGS='rtmw-dw-l-m-256x192-hands42-v1'
_hand=[]

def make_hand_model():
    """Whole-body RTMW used only for its 42 hand points; absent file = fingers not measured."""
    if not _hand:
        if staged_mode() and not HAND_MODEL.is_file():
            # A private deployment never downloads: use the hash-pinned archive staged beside the body models.
            import sys
            from rtmlib import RTMPose
            from .staged_models import prepare_hand,resolve_directory
            registry=sys.modules.get('folder_paths')
            registered=registry.get_folder_paths('motion_guard') if registry and 'motion_guard' in registry.folder_names_and_paths else []
            try:
                path=prepare_hand(resolve_directory(registered,os.environ.get('MG_MODEL_DIR')),ROOT/'data/models/rtmpose/staged')
                _hand.append(path and RTMPose(path,model_input_size=(192,256),to_openpose=False,backend='onnxruntime',device='cpu'))
            except Exception:_hand.append(None)
        else:
            # Like the body model, the first local run downloads the official archive into the cache.
            os.environ.setdefault('TORCH_HOME',str(ROOT/'data/models/rtmpose'))
            from rtmlib import RTMPose
            source=str(HAND_MODEL) if HAND_MODEL.is_file() else HAND_URL
            try:_hand.append(RTMPose(source,model_input_size=(192,256),to_openpose=False,backend='onnxruntime',device='cpu'))
            except Exception:_hand.append(None)  # fingers are then reported as not measured
    return _hand[0]

def predict(model,img,hand=None):
    if hand is None:
        xy,score=model(img);hxy=hs=None
    else:
        boxes=model.det_model(img);xy,score=model.pose_model(img,bboxes=boxes)
        hxy,hs=hand(img,bboxes=boxes)
    if len(xy)!=1:
        empty=(np.zeros((18,2)),np.zeros(18),int(len(xy)))
        return empty+((np.zeros((42,2)),np.zeros(42)),) if hand is not None else empty
    out=np.zeros((18,2));conf=np.zeros(18)
    for j,k in enumerate(COCO):
        if k is not None:out[j]=xy[0,k];conf[j]=score[0,k]
    out[1]=(xy[0,5]+xy[0,6])/2;conf[1]=min(score[0,5],score[0,6])
    if hand is not None:return out,conf,1,(hxy[0,91:133],hs[0,91:133]) if len(hxy)==1 else (np.zeros((42,2)),np.zeros(42))
    return out,conf,1

def extract(video,output,model=None):
    video=Path(video);output=Path(output);digest=hashlib.sha256(video.read_bytes()).hexdigest()
    cache_version='rtmpose-balanced-coco17-to-openpose18-v1'
    if output.exists():
        prior=json.loads(output.read_text(encoding='utf-8'))
        # Decide from the call, not by loading the hand model: a cache hit needs no network.
        wants_hands=not staged_mode() and (model is None or hasattr(model,'det_model'))
        hands_ok=not wants_hands or prior.get('hand_settings')==HAND_SETTINGS or (_hand and _hand[0] is None)
        if prior.get('video_sha256')==digest and prior.get('settings')==cache_version and hands_ok:return prior
    model=model or make_estimator();hand=make_hand_model() if hasattr(model,'det_model') else None
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened():raise ValueError('Cannot decode video')
    pts=[];scores=[];people=[];hands=[];hand_scores=[];start=time.perf_counter();size=None
    while True:
        ok,img=cap.read()
        if not ok:break
        size=[img.shape[1],img.shape[0]];res=predict(model,img,hand);p,s,n=res[:3];pts.append(p.tolist());scores.append(s.tolist());people.append(n)
        if hand is not None:hands.append(res[3][0].tolist());hand_scores.append(res[3][1].tolist())
    cap.release()
    if not pts:raise ValueError('Empty video')
    if not np.isfinite(pts).all() or not np.isfinite(scores).all():raise ValueError('Nonfinite estimator output')
    result={'video_sha256':digest,'settings':cache_version,'estimator':'rtmlib '+importlib.metadata.version('rtmlib'),'fps':fps,'size':size,'frames':len(pts),'points':pts,'scores':scores,'people':people,'elapsed_s':time.perf_counter()-start}
    if hand is not None:result.update(hand_settings=HAND_SETTINGS,hands=hands,hand_scores=hand_scores)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,allow_nan=False),encoding='utf-8');return result
