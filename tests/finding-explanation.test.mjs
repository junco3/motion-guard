import test from 'node:test';
import assert from 'node:assert/strict';
import {explainFindingDetails as explainFinding,explainFinding as explainShort,localMotionEvidence} from '../web/finding-explanation.mjs';

test('selected evidence excludes other joints and windows outside selected frames',()=>{
 const f={frames:[10,20],joints:[7],t_start_s:.4,t_end_s:.9,evidence:{metric_name:'M5_joint_energy',threshold:.4,metric_value:.01}};
 const report={metrics:{M5_energy:{joint_windows:[{joint:7,start:0,end:5,ratio:.01},{joint:8,start:10,end:15,ratio:.02},{joint:7,start:10,end:15,ratio:.3},{joint:7,start:15,end:20,ratio:.5},{joint:7,start:19,end:24,ratio:.03}]}}};
 assert.deepEqual(localMotionEvidence(f,report),{count:2,below:1,min:.3,max:.5});
 assert.match(explainFinding(f,'elbow',report),/30.0–50.0%/);
 assert.match(explainFinding(f,'elbow'),/Local values for the selected segment were not confirmed/);
 assert.equal(localMotionEvidence({...f,frames:[20,10]},report),null);
});
test('motion energy explains numeric evidence without presenting it as interval average',()=>{
 const text=explainFinding({t_start_s:11.208333,t_end_s:11.625,evidence:{metric_name:'M5_joint_energy',metric_value:.212708,threshold:.4}},'Left elbow');
 for(const part of ['11.21','11.63','Left elbow','21.3%','40.0%','is neither an average for the selected segment alone nor an actual travel distance'])assert.ok(text.includes(part));
});
test('observation gap does not become a confirmed motion error',()=>{
 const text=explainFinding({type:'OBSERVATION_GAP',t_start_s:0,t_end_s:1},'Left hand');
 assert.match(text,/It was not confirmed as a motion error/);
 assert.doesNotMatch(text,/Detected a difference/);
});
import {localPoseEvidence,findingBody} from '../web/finding-explanation.mjs';
test('nonlocal evidence identifies its actual aggregation scope instead of implying interval values',()=>{
 const scopes={M2_swap_ratio:'all left-right error frames of the joint pair',M3_terminal:'all valid frames including normal observations',M3_root:'all torso-direction error frames',M3_root_window:'all torso-direction error observation windows',M4_lag_s:'the full observation time series'};
 for(const [metric_name,scope] of Object.entries(scopes)){
  const text=explainFinding({frames:[20,30],t_start_s:1,t_end_s:1.5,evidence:{metric_name,metric_value:.5}},'arm');
  assert.ok(text.includes(scope),metric_name);assert.match(text,/for the selected segment .*not provided/);
  if(metric_name==='M3_root_window')assert.match(text,/overlap and are not independent samples/);
 }
 const unknown=explainFinding({t_start_s:1,t_end_s:2,evidence:{metric_name:'future_metric',metric_value:.123456}},'arm');
 assert.match(unknown,/aggregation scope is not confirmed/);assert.doesNotMatch(unknown,/0\.123/);
});
test('pose interval uses only valid local samples and reports missing observations',()=>{
 const f={type:'WRONG_POSE',frames:[1,4],t_start_s:1,t_end_s:4,evidence:{metric_name:'M1_pck'}};
 const report={metrics:{M1_pck:{mean:.9,per_frame:[1,.2,null,.4,NaN,1]}}};
 assert.deepEqual(localPoseEvidence(f,report),{total:4,count:2,mean:.30000000000000004,min:.2,max:.4});
 const text=explainFinding(f,'Whole pose',report);
 assert.match(text,/4 frames, of which 2 have values/);assert.match(text,/30.0%/);assert.match(text,/Note:.*90.0%/);
 for(const frames of [[-1,2],[2,99],[3,1],[1.5,3]])assert.equal(localPoseEvidence({...f,frames},report),null);
 assert.equal(localPoseEvidence({...f,frames:[2,2]},report),null);
 assert.match(explainFinding({...f,frames:[2,2]},'Whole pose',report),/Local pose values for the selected segment were not confirmed/);
 assert.equal(findingBody(f,{}),'Body part not identified (insufficient evidence)');
});

test('single-joint sustained pose error has its own explanation', () => {
 const f={type:'WRONG_POSE',frames:[10,20],t_start_s:10/24,t_end_s:21/24,joints:[4],evidence:{metric_name:'M1_joint_error',metric_value:.35,threshold:.1}};
 assert.match(explainFinding(f,'Right wrist',{}),/11 frames.*0\.35 torso lengths.*0\.10/);
 assert.match(explainShort(f,'Right wrist',{}),/One body part off its reference position/);
});
