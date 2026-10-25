"""Calibration diagnostic for slow one-direction motion; not a production verdict."""
import numpy as np

def missing_motion_windows(reference, generated, ground_truth, valid, torso, fps=24, energy_ratio=.4, net_distance=.12):
    r,g,gt=map(lambda x:np.asarray(x,float),(reference,generated,ground_truth))
    valid=np.asarray(valid,bool);torso=np.asarray(torso,float)
    if fps!=24 or r.ndim!=3 or r.shape!=g.shape or r.shape!=gt.shape or valid.shape!=r.shape[:2] or torso.shape!=(len(r),):
        raise ValueError('Invalid slow-motion timeline')
    if not all(np.isfinite(x).all() for x in (r,g,gt,torso)) or (torso<=0).any():raise ValueError('Invalid coordinates')
    findings=[]
    for seconds in (1,2):
        window=int(fps*seconds)
        for joint in range(2,min(14,r.shape[1])):
            for start in range(len(r)-window):
                end=start+window;sl=slice(start,end+1)
                if not valid[sl,joint].all():continue
                scale=float(np.median(torso[sl]))
                rn=float(np.linalg.norm(r[end,joint]-r[start,joint])/scale)
                tn=float(np.linalg.norm(gt[end,joint]-gt[start,joint])/scale)
                if min(rn,tn)<net_distance:continue
                re=float(np.linalg.norm(np.diff(r[sl,joint],axis=0),axis=1).sum()/scale)
                ge=float(np.linalg.norm(np.diff(g[sl,joint],axis=0),axis=1).sum()/scale)
                if re<=0 or ge/re>=energy_ratio:continue
                findings.append({'joint':joint,'window_seconds':seconds,'evidence_frames':[start,end],
                    'evidence_seconds':[start/fps,end/fps],'energy_ratio':ge/re,
                    'reference_net_normalized':rn,'gt_net_normalized':tn,
                    'error_boundaries_localized':False})
    return {'policy':'slow-directed-window-v2-calibration','automatic_failure':False,
            'window_seconds':[1,2],'thresholds':{'energy_ratio':energy_ratio,'net_distance':net_distance},
            'windows':findings,'limitations':['evidence window is not exact error interval','overlapping windows are not independent samples','net displacement misses closed motion paths']}
