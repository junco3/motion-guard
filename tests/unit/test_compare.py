"""Analytic fixtures: unit tests, not rendered synthetic acceptance data."""
import copy
import numpy as np
import pytest
from motionguard_core.compare import compare,lag_measure,spans

def sample():
 n=97;base=np.array([[300,80],[300,100],[240,120],[220,170],[180,210],[360,120],[380,170],[420,210],[260,250],[260,320],[260,390],[340,250],[340,320],[340,390],[290,75],[310,75],[280,80],[320,80]],float)
 t=np.arange(n)/24;pts=np.repeat(base[None],n,axis=0);trajectory=65*(np.tanh((t-1.3)*4)+1)+25*(np.tanh((t-2.8)*7)+1);pts[:,:,0]+=trajectory[:,None]
 track={'points':pts.tolist(),'scores':np.ones((n,18)).tolist(),'fps':24,'settings':'analytic-unit-fixture'}
 gt={'meta':{'root_translation_ground_truth':True},'frames':[{'frame':i,'time_s':i/24,'camera':{'fixed':True},'joints':[{'available':True,'pixel':p.tolist(),'in_frame':True,'visibility':'surface_near'} for p in pts[i]]} for i in range(n)]}
 return track,copy.deepcopy(track),gt

def test_clean_and_zero_swap():
 r,g,gt=sample();o=compare(r,g,gt);assert o['verdict']=='PASS',o
 assert not any(f['type']=='WRONG_SIDE' for f in o['failures'])

@pytest.mark.parametrize('mode',['nan','truncated','fps','gt_nan','missing_settings'])
def test_invalid(mode):
 r,g,gt=sample()
 if mode=='nan':g['points'][0][2][0]=float('nan')
 if mode=='truncated':g['points'].pop();g['scores'].pop()
 if mode=='fps':g['fps']=30
 if mode=='gt_nan':gt['frames'][0]['time_s']=float('nan')
 if mode=='missing_settings':r.pop('settings');g.pop('settings')
 assert compare(r,g,gt)['verdict']=='ERROR'

def test_missing_and_wrong_reference_uncertain():
 r,g,gt=sample();g['scores']=np.zeros((97,18)).tolist();assert compare(r,g,gt)['verdict']=='UNCERTAIN'
 r,g,gt=sample();r['points']=(np.array(r['points'])+300).tolist();o=compare(r,g,gt);assert o['verdict']=='UNCERTAIN';assert o['coverage']['valid_joint_frames']==0

def test_freeze_missing_motion():
 r,g,gt=sample();g['points']=np.repeat(np.array(g['points'])[:1],97,axis=0).tolist();o=compare(r,g,gt)
 assert o['verdict']=='FAIL';assert any(f['type']=='MISSING_MOTION' for f in o['failures'])

def test_side_six_consecutive():
 r,g,gt=sample();a=np.array(g['points']);a[:,[4,7]]=a[:,[7,4]];g['points']=a.tolist();assert any(f['type']=='WRONG_SIDE' for f in compare(r,g,gt)['failures'])
 r,g,gt=sample();a=np.array(g['points']);a[:5,[4,7]]=a[:5,[7,4]];g['points']=a.tolist();assert not any(f['type']=='WRONG_SIDE' for f in compare(r,g,gt)['failures'])

def test_framing():
 r,g,gt=sample();g['points']=(np.array(g['points'])*1.2+[40,30]).tolist();o=compare(r,g,gt);assert o['verdict']=='PASS';assert abs(o['metrics']['M8_framing']['scale']-1.2)<1e-6

@pytest.mark.parametrize('delay',[6,12])
def test_lag(delay):
 r,g,gt=sample();a=np.array(r['points']);g['points']=np.concatenate([np.repeat(a[:1],delay,axis=0),a[:-delay]]).tolist();o=compare(r,g,gt)
 assert abs(o['metrics']['M4_timing']['lag_s']-delay/24)<=1/24
 assert any(f['type']=='TIMING_MISMATCH' for f in o['failures'])==(delay>6)

def test_occluded_side():
 r,g,gt=sample();a=np.array(g['points']);a[:,[4,7]]=a[:,[7,4]];g['points']=a.tolist()
 for f in gt['frames']:
  for j in [4,7]:f['joints'][j]['visibility']='occluded'
 assert not any(f['type']=='WRONG_SIDE' for f in compare(r,g,gt)['failures'])

def test_periodic_and_span():
 a=np.tile([0.,1.,0.,0.],24);_,reason,_=lag_measure(a,a,np.ones(96,bool),24);assert reason=='periodic_or_ambiguous_lag';assert spans([True]*6+[False],6)==[[0,5]]


def test_root_reverse_requires_locomotion_tag():
 r,g,gt=sample();a=np.array(g['points']);origin=a[0].mean(0);a[:,:,0]=2*origin[0]-a[:,:,0];g['points']=a.tolist();o=compare(r,g,gt)
 assert any(f['evidence']['metric_name']=='M3_root' for f in o['failures'])
 gt['meta']['root_translation_ground_truth']=False;o=compare(r,g,gt)
 assert not any(f['evidence']['metric_name']=='M3_root' for f in o['failures'])

def test_zero_torso_uncertain():
 r,g,gt=sample()
 for f in gt['frames']:
  for j in [2,5,8,11]:f['joints'][j]['pixel']=[0,0]
 assert compare(r,g,gt)['verdict']=='UNCERTAIN'

def test_static_not_direction_failure():
 r,g,gt=sample();r['points']=np.repeat(np.array(r['points'])[:1],97,axis=0).tolist();g=copy.deepcopy(r)
 for f in gt['frames']:
  for j,p in enumerate(r['points'][0]):f['joints'][j]['pixel']=p
 o=compare(r,g,gt);assert o['verdict']=='UNCERTAIN';assert not o['failures']

def test_moving_camera_root_withheld():
 r,g,gt=sample()
 for i,f in enumerate(gt['frames']):f['camera']={'position':[i,0,0]}
 o=compare(r,g,gt);assert o['verdict']=='UNCERTAIN';assert 'global_direction_camera_uncompensated' in o['uncertain_reasons']

def test_m6_score_loss_is_review_not_failure():
 r,g,gt=sample();g['scores'][0][4]=.1;o=compare(r,g,gt)
 assert any(f['type']=='STRUCTURE_SUSPECT' for f in o['flags']);assert not o['failures']

def test_wrong_pose_total_evidence_not_six_consecutive_bad():
 r,g,gt=sample();a=np.array(g['points'])
 # Four bad frames, one good: enough aggregate mismatch, never six consecutive.
 for i in range(97):
  if i%5!=0:a[i,[3,4,6,7,9,10,12,13],1]+=60
 g['points']=a.tolist();o=compare(r,g,gt)
 assert any(f['type']=='WRONG_POSE' for f in o['failures'])
 assert o['verdict']=='FAIL'
 assert all(f['frames'][1]-f['frames'][0]+1>=6 for f in o['display_failures'])


def test_display_boundary_and_local_pose_attribution(monkeypatch):
 import importlib
 module=importlib.import_module('motionguard_core.compare')
 monkeypatch.setattr(module,'similarity',lambda r,g:(1.,np.zeros(2)))
 from motionguard_core.compare import display_evidence
 report={'failures':[{'frames':[0,4]},{'frames':[10,15]}],'verdict':'FAIL'}
 display_evidence(report,6)
 assert report['display_failures']==[{'frames':[10,15]}]
 assert len(report['failures'])==2 and report['verdict']=='FAIL'
 r,g,gt=sample();a=np.array(g['points'])
 a[5:40,[3,4,6,7,9,10,12,13],1]+=100
 a[45:90,[3,4,6,7,9,10,12,13],1]+=200
 g['points']=a.tolist();o=compare(r,g,gt)
 rows=[f for f in o['display_failures'] if f['type']=='WRONG_POSE']
 assert len(rows)>=2,o
 for f in rows:
  start,end=f['frames'];e=f['evidence']
  assert e['metric_value']==pytest.approx(np.mean(o['metrics']['M1_pck']['per_frame'][start:end+1]))
  assert e['whole_clip_mean']==o['metrics']['M1_pck']['mean']
  assert e['scope']=='interval_mean'
  assert all(e['joint_observations'][str(j)]>=6 and e['joint_miss_rates'][str(j)]>=.5 for j in f['joints'])
  assert 1 not in f['joints'] and len(f['joints'])<=2

def test_short_pose_intervals_preserve_fail_without_display(monkeypatch):
 import importlib
 module=importlib.import_module('motionguard_core.compare')
 monkeypatch.setattr(module,'similarity',lambda r,g:(1.,np.zeros(2)))
 r,g,gt=sample();a=np.array(g['points'])
 for i in range(97):
  if i%5!=0:a[i,[3,4,6,7,9,10,12,13],1]+=100
 g['points']=a.tolist();o=compare(r,g,gt)
 assert o['verdict']=='FAIL'
 assert any(f['type']=='WRONG_POSE' for f in o['failures'])
 assert not any(f['type']=='WRONG_POSE' for f in o['display_failures'])
 assert o['display_policy']['suppressed_short_intervals']>0

@pytest.mark.parametrize('variant',['clean','shift','freeze','occluded'])
def test_fixed_visible_subset(variant):
 r,g,gt=sample()
 for f in gt['frames']:
  for j in range(2,14):
   if j!=10:f['joints'][j]['visibility']='uncertain'
 a=np.array(r['points'])
 if variant=='shift':g['points']=np.concatenate([np.repeat(a[:1],12,axis=0),a[:-12]]).tolist()
 if variant=='freeze':g['points']=np.repeat(a[:1],97,axis=0).tolist()
 if variant=='occluded':g['scores']=np.zeros((97,18)).tolist()
 o=compare(r,g,gt);assert o['metrics']['temporal_subset']['selected_joints']==[10]
 types={f['type'] for f in o['failures']}
 if variant=='shift':assert 'TIMING_MISMATCH' in types
 if variant=='freeze':assert 'MISSING_MOTION' in types
 if variant in ('clean','occluded'):assert o['verdict']=='UNCERTAIN';assert not types
 assert 'insufficient_active_coverage' in o['uncertain_reasons']


@pytest.mark.parametrize('kind',['same','reverse','stopped','occluded'])
def test_slow_root_window(kind):
 r,g,gt=sample(); a=np.array(r['points']); a=np.repeat(a[:1],97,axis=0); a[:,:,0]+=np.arange(97)[:,None]*.5
 r['points']=a.tolist(); b=a.copy()
 if kind=='reverse':b[:,:,0]-=np.arange(97)[:,None]
 if kind=='stopped':b=np.repeat(b[:1],97,axis=0)
 g['points']=b.tolist()
 for i,frame in enumerate(gt['frames']):
  for j,joint in enumerate(frame['joints']):joint['pixel']=a[i,j].tolist()
  if kind=='occluded':
   for j in [8,11]:frame['joints'][j]['visibility']='occluded'
 gt['meta']['root_translation_ground_truth']=True
 o=compare(r,g,gt)
 assert any(x['evidence']['metric_name']=='M3_root_window' for x in o['failures'])==(kind=='reverse')


def test_side_evidence_keeps_pair_identity_for_equal_ranges():
 r,g,gt=sample();a=np.array(g['points']);original=a.copy()
 for left,right in [(3,6),(4,7)]:
  a[20:30,left]=original[20:30,right];a[20:30,right]=original[20:30,left]
 g['points']=a.tolist();o=compare(r,g,gt)
 findings=[x for x in o['failures']+o['flags'] if x.get('evidence',{}).get('metric_name')=='M2_swap_ratio']
 assert findings
 assert all(len(x['joints'])==2 and x['joints'] in ([3,6],[4,7]) for x in findings)

@pytest.mark.parametrize('delay',[-3,3,6])
def test_small_global_delay_passes(delay):
 r,g,gt=sample();a=np.array(r['points']);d=abs(delay)
 g['points']=(np.concatenate([np.repeat(a[:1],d,axis=0),a[:-d]]) if delay>0 else np.concatenate([a[d:],np.repeat(a[-1:],d,axis=0)])).tolist()
 o=compare(r,g,gt);assert o['verdict']=='PASS',(o['failures'],o['uncertain_reasons'])
 assert o['metrics']['time_shift']['frames']==delay

def test_unrelated_motion_not_rescued_by_shift():
 r,g,gt=sample();g['points']=np.array(r['points'])[::-1].tolist();o=compare(r,g,gt);assert o['verdict']=='FAIL'

def test_shift_edges_not_structure_flags():
 r,g,gt=sample();a=np.array(r['points']);g['points']=np.concatenate([np.repeat(a[:1],3,axis=0),a[:-3]]).tolist();o=compare(r,g,gt)
 assert o['metrics']['M6_structure']['low_score_joint_frames']==0

def test_one_body_part_wrong_fails_even_when_mean_passes():
 r,g,gt=sample();a=np.array(r['points']);b=a.copy();b[30:70,[3,4,6,7]]-=[0,60];g['points']=b.tolist();o=compare(r,g,gt)
 assert o['metrics']['M1_pck']['mean']>=o['metrics']['M1_pck']['threshold']
 assert o['verdict']=='FAIL';hits=[f for f in o['failures'] if f['evidence']['metric_name']=='M1_joint_error']
 assert hits and {j for f in hits for j in f['joints']}<= {3,4,6,7}

def test_short_joint_glitch_not_failed():
 r,g,gt=sample();a=np.array(r['points']);a[40:45,4]+=[0,60];g['points']=a.tolist();assert compare(r,g,gt)['verdict']=='PASS'

def with_hands(track):
 a=np.array(track['points']);shape=np.array([[0,0]]+[[(f-2)*6,-6*s] for f in range(5) for s in range(1,5)],float)
 hands=np.concatenate([a[:,7][:,None]+shape[None],a[:,4][:,None]+shape[None]],axis=1)
 track.update(hand_settings='unit-hands',hands=hands.tolist(),hand_scores=np.ones((len(a),42)).tolist());return track

def with_gt_hands(gt,track,visibility='surface_near'):
 for f,h in zip(gt['frames'],track['hands']):f['hands']=[{'available':True,'pixel':p,'in_frame':True,'visibility':visibility} for p in h]
 return gt

def test_fingers_same_pass_and_one_finger_fails():
 r,g,gt=sample();r,g=with_hands(r),with_hands(g);gt=with_gt_hands(gt,r);o=compare(r,g,gt)
 assert o['verdict']=='PASS' and o['metrics']['M9_fingers']['status']=='measured'
 h=np.array(g['hands']);h[30:70,8]+=[0,-20];g['hands']=h.tolist();o=compare(r,g,gt)
 assert o['verdict']=='FAIL';assert {f['joints'][0] for f in o['failures'] if f['evidence']['metric_name']=='M9_finger_shape'}=={99}

def test_fingers_not_measured_without_hands():
 r,g,gt=sample();o=compare(r,g,gt);assert o['metrics']['M9_fingers']['status']=='not_measured' and o['verdict']=='PASS'

def test_frozen_with_estimator_jitter_still_missing_motion():
 r,g,gt=sample();a=np.repeat(np.array(g['points'])[:1],97,axis=0);a+=np.random.default_rng(0).normal(0,2,a.shape);g['points']=a.tolist()
 o=compare(r,g,gt);assert o['verdict']=='FAIL';assert any(f['type']=='MISSING_MOTION' for f in o['failures'])

def test_short_clip_joint_check_not_silent():
 r,g,gt=sample();n=17
 for x in (r,g):x['points']=x['points'][:n];x['scores']=x['scores'][:n]
 gt['frames']=gt['frames'][:n];o=compare(r,g,gt);assert o['verdict']!='PASS' or 'joint_check_clip_too_short' in o['uncertain_reasons']
 assert 'joint_check_clip_too_short' in o['uncertain_reasons']

def test_fingers_hidden_in_ground_truth_not_judged():
 r,g,gt=sample();r,g=with_hands(r),with_hands(g);gt=with_gt_hands(gt,r,'uncertain')
 h=np.array(g['hands']);h[30:70,8]+=[0,-20];g['hands']=h.tolist();o=compare(r,g,gt)
 assert o['verdict']=='PASS';assert not any(f['evidence']['metric_name']=='M9_finger_shape' for f in o['failures'])

def test_fingers_without_ground_truth_not_measured():
 r,g,gt=sample();r,g=with_hands(r),with_hands(g);o=compare(r,g,gt)
 assert o['metrics']['M9_fingers']['reason']=='no 3D finger ground truth for this reference' and o['verdict']=='PASS'

def test_finger_not_judged_where_reference_estimate_disagrees_with_ground_truth():
 r,g,gt=sample();r,g=with_hands(r),with_hands(g);gt=with_gt_hands(gt,r)
 for f in gt['frames']:f['hands'][8]['pixel']=[p+40 for p in f['hands'][8]['pixel']]
 h=np.array(g['hands']);h[30:70,8]+=[0,-20];g['hands']=h.tolist();o=compare(r,g,gt)
 assert not any(f['evidence']['metric_name']=='M9_finger_shape' for f in o['failures'])
