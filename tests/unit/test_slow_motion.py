import numpy as np
from motionguard_core.slow_motion import missing_motion_windows

def sample():
    n=721;r=np.zeros((n,18,2));t=np.arange(n)/24
    r[:,10,0]=np.clip(t-14,0,6)*12
    return r,r.copy(),np.ones((n,18),bool),np.full(n,130.)

def inspect(r,g,valid,torso):return missing_motion_windows(r,g,r,valid,torso)['windows']

def test_long_slow_freeze_detected_beyond_four_seconds():
    r,g,v,l=sample();g[336:480,10]=r[336,10]
    rows=inspect(r,g,v,l)
    assert rows and all(x['joint']==10 for x in rows)
    assert all(x['evidence_frames'][1]>336 and x['evidence_frames'][0]<480 for x in rows)
    assert any(x['evidence_frames'][0]>=336 and x['evidence_frames'][1]<480 for x in rows)

def test_normal_slow_motion_and_shared_pause_no_warning():
    r,g,v,l=sample();assert inspect(r,g,v,l)==[]
    r[350:360]=r[350];g=r.copy();assert inspect(r,g,v,l)==[]

def test_brief_generated_pause_not_missing_motion():
    r,g,v,l=sample();g[370:373]=g[370];assert inspect(r,g,v,l)==[]

def test_small_estimator_jitter_no_warning():
    r,g,v,l=sample();g+=np.random.default_rng(7).normal(0,.2,g.shape)
    assert inspect(r,g,v,l)==[]

def test_unobserved_freeze_has_no_localization():
    r,g,v,l=sample();g[336:480,10]=r[336,10];v[336:480,10]=False
    assert inspect(r,g,v,l)==[]

def test_short_input_and_normal_return_motion():
    r,g,v,l=sample();assert inspect(r[:20],g[:20],v[:20],l[:20])==[]
    r[:,10,0]=40*np.sin(np.arange(721)/24);g=r.copy()
    assert inspect(r,g,v,l)==[]
