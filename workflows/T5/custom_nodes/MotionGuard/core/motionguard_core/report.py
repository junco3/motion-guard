"""Render evidence, never turn absent failure intervals into a per-frame PASS."""
import json, hashlib
import subprocess
from pathlib import Path
import cv2
import numpy as np

LIMBS=[(2,3),(3,4),(5,6),(6,7),(2,5),(2,8),(5,11),(8,11),(8,9),(9,10),(11,12),(12,13)]


JOINT_LABELS={2:'R shoulder',3:'R elbow',4:'R wrist',5:'L shoulder',6:'L elbow',7:'L wrist',8:'R hip',9:'R knee',10:'R ankle',11:'L hip',12:'L knee',13:'L ankle'}
FINGER_LABELS={91+off+tip:f'{side} {name}' for side,off in (('L',0),('R',21)) for tip,name in {4:'thumb',8:'index',12:'middle',16:'ring',20:'little'}.items()}


def failure_markers(failures, pose, frame):
    """Locate only explicitly implicated joints on the generated video's pixels."""
    w,h=pose['size']
    if not 0 <= frame < len(pose['points']): return []
    result=[];seen=set()
    for failure in failures:
        bounds=failure.get('frames',[])
        if len(bounds)!=2 or not bounds[0]<=frame<=bounds[1]: continue
        for joint in failure.get('joints',[]):
            if not isinstance(joint,int) or isinstance(joint,bool) or joint not in JOINT_LABELS and joint not in FINGER_LABELS: continue
            points,scores,index=(pose['points'],pose['scores'],joint) if joint in JOINT_LABELS else (pose.get('hands',[]),pose.get('hand_scores',[]),joint-91)
            if frame>=len(points) or index>=len(points[frame]) or index>=len(scores[frame]): continue
            xy=np.asarray(points[frame][index],dtype=float)
            score=scores[frame][index]
            if xy.shape!=(2,) or not np.isfinite(xy).all() or not np.isfinite(score) or score<.5: continue
            if not (0<=xy[0]<w and 0<=xy[1]<h): continue
            key=(joint,failure['type'])
            if key in seen: continue
            seen.add(key)
            result.append({'joint':joint,'pixel':xy.tolist(),'type':failure['type'],
                           'time_s':frame/pose['fps'],'label':JOINT_LABELS.get(joint) or FINGER_LABELS[joint]})
    return result

def render(reference, generated, report_dir):
    out=Path(report_dir);report=json.loads((out/'report.json').read_text(encoding='utf-8'))
    r=json.loads((out/'reference-pose.json').read_text(encoding='utf-8'))
    g=json.loads((out/'generated-pose.json').read_text(encoding='utf-8'))
    gt_source=report.get('sources',{}).get('gt')
    gt_path=Path(gt_source['path']) if gt_source else Path(reference).parent/'joints.json'
    if gt_source and (not gt_path.is_file() or hashlib.sha256(gt_path.read_bytes()).hexdigest()!=gt_source['sha256']):
        raise ValueError('Explicit GT missing or hash mismatch')
    gt=json.loads(gt_path.read_text(encoding='utf-8')) if gt_path.is_file() else None
    n=r['frames'];w,h=r['size'];fps=r['fps']
    if n!=g['frames'] or fps!=g['fps'] or r['size']!=g['size']:raise ValueError('Overlay input timeline mismatch')
    caps=[cv2.VideoCapture(str(p)) for p in [reference,generated]]
    temporary=out/'overlay-working.avi';writer=cv2.VideoWriter(str(temporary),cv2.VideoWriter_fourcc(*'MJPG'),fps,(w*3,h+100))
    if not writer.isOpened():raise RuntimeError('Video encoder unavailable')
    samples=[];intervals=report.get('display_failures',report.get('failures',[]));frame_labels=[]

    timeline=np.full((18,w*3,3),100,dtype=np.uint8)
    for f in intervals:
        start,end=f['frames']
        left=round(max(0,start)*w*3/n);right=round(min(n,end+1)*w*3/n)
        cv2.rectangle(timeline,(left,0),(right,17),(50,50,220),-1)
    try:
        for i in range(n):
            frames=[]
            for cap in caps:
                ok,img=cap.read()
                if not ok:raise ValueError('Overlay missing frame')
                frames.append(img)
            skel=np.full_like(frames[0],35)
            if gt:
                joints=gt['frames'][i]['joints']
                for a,b in LIMBS:
                    if joints[a].get('pixel') and joints[b].get('pixel'):
                        cv2.line(skel,tuple(np.asarray(joints[a]['pixel'],int)),tuple(np.asarray(joints[b]['pixel'],int)),(255,210,30),1)
            for data,color in [(r,(80,230,80)),(g,(80,170,255))]:
                xy=np.asarray(data['points'][i]);scores=np.asarray(data['scores'][i])
                for a,b in LIMBS:
                    if min(scores[a],scores[b])>=.5:cv2.line(skel,tuple(xy[a].astype(int)),tuple(xy[b].astype(int)),color,2)
                for j in range(2,14):
                    if scores[j]>=.5:cv2.circle(skel,tuple(xy[j].astype(int)),3,color,-1)
            canvas=np.zeros((h+100,w*3,3),np.uint8);canvas[:h]=np.hstack([*frames,skel])
            labels=['REFERENCE','GENERATED','GT cyan / estimated R green / G orange']
            for col,label in enumerate(labels):
                cv2.rectangle(canvas,(col*w,0),((col+1)*w,36),(20,20,20),-1)
                cv2.putText(canvas,label,(col*w+10,25),cv2.FONT_HERSHEY_SIMPLEX,.65,(240,240,240),1)

            markers=failure_markers(intervals,g,i)
            for marker in markers:
                x,y=map(lambda v:int(round(v)),marker['pixel'])
                cv2.circle(canvas,(w+x,y),max(14,round(min(w,h)*.035)),(0,0,255),3,cv2.LINE_AA)
                label=marker['label']+' '+marker['type']+f' {i/fps:.2f}s'
                tx=min(w+x+18,w*2-330);ty=max(48,min(h-10,y-18))
                cv2.putText(canvas,label,(max(w+5,tx),ty),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,255),2,cv2.LINE_AA)
            active=[f['type'] for f in intervals if f['frames'][0]<=i<=f['frames'][1]]
            # Report has clip-level PASS/UNCERTAIN, not a full per-frame classifier.
            state='ERROR' if report['verdict']=='ERROR' else 'FAIL' if active else 'UNCERTAIN'
            color={'FAIL':(50,50,220),'UNCERTAIN':(130,130,130),'ERROR':(200,60,200)}[state]
            frame_labels.append({'frame':i,'status':state,'failures':active,'markers':markers})
            canvas[h+65:h+83]=timeline
            cv2.line(canvas,(round(i*w*3/n),h+60),(round(i*w*3/n),h+90),(255,255,255),2)
            text=f'{i:03d}/{n-1} {i/fps:.3f}s | clip: {report["verdict"]} | '+(','.join(active) if active else 'no certified per-frame PASS')
            cv2.putText(canvas,text,(12,h+27),cv2.FONT_HERSHEY_SIMPLEX,.7,color,2)
            coverage=report.get('coverage',{}).get('active_valid_joint_fraction',0)
            cv2.putText(canvas,f'Motion only. Gray = unconfirmed. Active coverage {coverage:.1%}; exclusion reasons in report.json.',(12,h+53),cv2.FONT_HERSHEY_SIMPLEX,.55,(220,220,220),1)
            writer.write(canvas)
            if i in [6,18,30,42,54]:samples.append(canvas.copy())
        writer.release()
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(temporary),'-c:v','libx264','-crf','19','-pix_fmt','yuv420p',str(out/'overlay.mp4')],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if samples:cv2.imwrite(str(out/'contact_sheet.jpg'),np.vstack([cv2.resize(s,(1152,306)) for s in samples]))
        (out/'overlay-timeline.json').write_text(json.dumps({'frames':frame_labels,'fps':fps,'not_per_frame_pass':True},indent=2),encoding='utf-8')
    finally:
        writer.release()
        for cap in caps:cap.release()
        if temporary.exists():temporary.unlink()
    return str(out/'overlay.mp4')
