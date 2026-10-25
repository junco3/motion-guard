import test from 'node:test';
import assert from 'node:assert/strict';
import {explainFinding,poseSummary} from '../web/finding-explanation.mjs';
test('mg3 local value and mg2 frame fallback remain distinct from whole clip',()=>{
 const f={type:'WRONG_POSE',frames:[0,5],t_start_s:0,t_end_s:.25,evidence:{metric_name:'M1_pck',metric_value:.9,threshold:.6}};
 const report={metrics:{M1_pck:{mean:.9,per_frame:[.2,.2,.2,.2,.2,.2]}},threshold_status:'PROVISIONAL_UNCALIBRATED'};
 assert.match(explainFinding(f,'Left hand',report),/20%/);
 assert.match(explainFinding({...f,evidence:{...f.evidence,scope:'interval_mean',metric_value:.3}},'Left hand',report),/30%/);
 assert.ok(explainFinding(f,'joint'.repeat(100),report).length<=80);
 assert.match(poseSummary(report),/PROVISIONAL_UNCALIBRATED/);
});
