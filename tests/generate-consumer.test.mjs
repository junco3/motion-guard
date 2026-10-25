// Executes the actual consumer module without a browser, desktop or paid API.
import test from 'node:test';
import assert from 'node:assert/strict';
const elements=new Map();
class Element {
 constructor(){this.children=[];this.dataset={};this.style={};this.hidden=false;this.disabled=false;this.value='';this.files=[];this.readyState=1;this.duration=4.04;this.ownerDocument=document;}
 set innerHTML(s){for(const m of s.matchAll(/id="([^"]+)"/g))elements.set('#'+m[1],new Element());}
 append(...v){this.children.push(...v);}
 after(){} before(){} pause(){} load(){}
 replaceChildren(...v){this.children=v;if(v.length&&v[0].value!==undefined)this.value=v[0].value;}
 set id(v){this._id=v;elements.set('#'+v,this);} get id(){return this._id;}
 setAttribute(k,v){this[k]=v;} removeAttribute(k){delete this[k];}
 addEventListener(){} removeEventListener(){}
}
globalThis.document={querySelector:s=>elements.get(s),querySelectorAll:()=>[...elements.values()],createElement:()=>new Element()};
document.body=new Element();
for(const id of ['generate','generation-status','result','comparison','download','character','prompt'])elements.set('#'+id,new Element());
globalThis.Option=class extends Element{constructor(text,value){super();this.textContent=text;this.value=value;}};
const A='t3-'+'a'.repeat(32),B='t3-'+'b'.repeat(32),C='t3-'+'c'.repeat(32);
const states={
 [A]:{status:'succeeded',guard_status:'complete',source_type:'platform_guarded',downstream_status:'complete',final_available:true},
 [B]:{status:'succeeded',guard_status:'complete',source_type:'cloud'},
 [C]:{status:'succeeded',guard_status:'error',source_type:'cloud'}
};
const reports={};
let policyFails=false,malformedPolicy=false,policyCalls=0,releaseLate=null,delayNextA=false;
globalThis.fetch=async url=>{
 if(url==='/api/active-runs')return {ok:true,json:async()=>[]};
 if(url==='/api/session'){
  policyCalls++;if(policyFails)throw Error('offline');
  return {ok:true,json:async()=>({token:'local-test',mode:'cloud_local_guard',generation_allowed:true,ceiling:2000,prior:1626.267958,remaining_reserved_budget:malformedPolicy?"invalid":373.732042,required_reservation:179.6})};
 }
 if(url==='/api/completed-runs')return {ok:true,json:async()=>[A,B,C].map(run_id=>({run_id,clip:run_id,status:'succeeded'}))};
 if(url.startsWith('/api/jobs/')){
  const run=url.split('/').at(-1);
  if(run===A&&delayNextA){delayNextA=false;await new Promise(resolve=>releaseLate=resolve);}
  return {ok:true,json:async()=>states[run]||{status:'failed'}};
 }
 if(url.includes('/guard/report.json'))return {ok:true,json:async()=>reports[url.split('/')[2]]||({verdict:'PASS',failures:[],uncertain_reasons:[]})};
 throw Error('Unexpected request (no generation permitted): '+url);
};
let readinessPoll;
globalThis.window={setInterval(callback){readinessPoll=callback;return 1;},director:{async ready(){},stop(){throw Error('input preparation failure');}}};
const $=s=>elements.get(s),tick=()=>new Promise(r=>setImmediate(r));
const {generationProgress,savedRunLabel,formatBilling}=await import('../web/generate.mjs');
test('billing displays actual balance separately and never turns unknown amounts into zero',()=>{
 const b={status:'last_verified',account_balance_credits:20390.19,account_decrease_credits:709.81,authorized_remaining_after_verified_debit:9290.19,as_of:'verified-time'};
 assert.match(formatBilling(b),/Account balance 20390.19/);assert.match(formatBilling(b),/reference margin 9290.19/);
 assert.match(formatBilling(b),/not a run allowance/);
 assert.match(formatBilling({...b,account_decrease_credits:null,authorized_remaining_after_verified_debit:null}),/settlement required/);
 for(const value of [null,NaN,Infinity,-1,'20390'])assert.match(formatBilling({...b,account_balance_credits:value}),/unconfirmed/);
});
test('saved result labels preserve source and prioritize current analysis errors over stale verdict',()=>{
 const row={run_id:A,clip:'walk',source_type:'controlled_video_test',guard_status:'analyzing',guard_verdict:'PASS'};
 assert.match(savedRunLabel(row),/Artificial-defect test · Checking/);
 assert.doesNotMatch(savedRunLabel(row),/PASS/);
 assert.match(savedRunLabel({...row,output_error:'all_black'}),/Output error/);
 assert.match(savedRunLabel({...row,source_type:'unknown',guard_status:'complete'}),/source unconfirmed · PASS/);
});
await tick();

test('real consumer selects same-run draft and final, then clears stale final on Cloud selection',async()=>{
 assert.equal($('#result').dataset.runId,A);
 assert.match($('#final-download').href,new RegExp(A));
 $('#saved-runs').value=B;await $('#saved-runs').onchange();
 assert.equal($('#result').dataset.runId,B);
 assert.match($('#execution-detail').textContent,new RegExp(B));
 assert.match($('#download').href,new RegExp(B));
 assert.equal($('#final-download').hidden,true);
 assert.equal($('#final-download').href,undefined);
 assert.match($('#downstream-state').textContent,/draft/);
});
test('real consumer ignores delayed old selection and preserves current draft on Guard ERROR',async()=>{
 delayNextA=true;$('#saved-runs').value=A;const old=$('#saved-runs').onchange();await tick();
 $('#saved-runs').value=C;await $('#saved-runs').onchange();
 assert.equal($('#result').dataset.runId,C);assert.match($('#guard-state').textContent,/ERROR/);
 assert.equal($('#final-download').href,undefined);
 releaseLate();await old;
 assert.equal($('#result').dataset.runId,C);
 assert.match($('#execution-detail').textContent,new RegExp(C));
});
test('execution details show received IDs and states without inventing a computation stage',()=>{
 const text=generationProgress(A,{job_id:'server-123',status:'running'});
 assert.match(text,/server-123/);assert.match(text,/detailed compute stage not received/);
 assert.match(text,/Check status: not received/);assert.match(text,/Follow-up status: not received/);
 assert.match(generationProgress(A),/Server job ID: not received/);
 assert.match(generationProgress(A,{status:'provider_new_status'}),/provider_new_status/);
});
test('preparation error releases controls, refreshes policy, and locks generation if policy fails',async()=>{
 $('#character').files=[{}];$('#prompt').value='test';
 const before=policyCalls;policyFails=true;
 await $('#generate').onclick();
 assert.ok(policyCalls>before);
 assert.equal($('#generate').disabled,true);
 $('#execution-mode').value='cloud_local_guard';$('#execution-mode').onchange();
 assert.equal($('#generate').disabled,true);
 assert.ok($('#execution-mode').children.every(option=>option.disabled));
 assert.equal($('#saved-runs').disabled,false);
 assert.equal($('#result').hidden,true);
 assert.equal($('#download').href,undefined);
 assert.match($('#generation-status').textContent,/input preparation failure/);
});

test('malformed policy cannot re-enable generation after authorization was read',async()=>{
 policyFails=false;malformedPolicy=true;
 await import('../web/generate.mjs?malformed-policy');await tick();
 assert.equal($('#generate').disabled,true);
});
test('consumer preserves a failed Guard ERROR draft and hides all final comparison media',async()=>{
 states[C]={status:'failed',guard_status:'error',source_type:'platform_guarded',
  draft_available:true,draft_comparison_available:false,final_available:false};
 $('#saved-runs').value=C;await $('#saved-runs').onchange();
 assert.equal($('#result').dataset.runId,C);
 assert.match($('#comparison').src,new RegExp(C+'/generated.mp4'));
 assert.match($('#download').href,new RegExp(C+'/generated.mp4'));
 assert.equal(new URL($('#download').href,'http://localhost').searchParams.get('preview'),'1');
 assert.equal($('#final-compare').hidden,true);
 assert.equal($('#final-video').src,undefined);
 states[C].draft_available=false;
 await $('#saved-runs').onchange();
 assert.equal($('#result').hidden,true);
});
test('held result explains uncertainty, links only its available draft, and clears on selection',async()=>{
 states[C]={status:'succeeded',guard_status:'complete',source_type:'platform_guarded',downstream_status:'held',draft_available:true,final_available:false};
 reports[C]={verdict:'UNCERTAIN',failures:[],uncertain_reasons:['periodic_or_ambiguous_lag']};
 $('#saved-runs').value=C;await $('#saved-runs').onchange();
 assert.equal($('#held-draft').hidden,false);assert.equal($('#held-draft').href,'#result');
 assert.match($('#downstream-state').textContent,/It is not confirmed as a motion failure/);
 assert.match($('#guard-findings').children[0].textContent,/lag candidates/);
 $('#saved-runs').value=B;await $('#saved-runs').onchange();
 assert.equal($('#held-draft').hidden,true);assert.equal($('#held-draft').href,undefined);
 states[C].draft_available=false;$('#saved-runs').value=C;await $('#saved-runs').onchange();
 assert.equal($('#held-draft').hidden,true);assert.equal($('#held-draft').href,undefined);
 reports[C]={verdict:'FAIL',failures:[],uncertain_reasons:[]};await $('#saved-runs').onchange();
 assert.match($('#downstream-state').textContent,/movement different from the original/);
 assert.match($('#downstream-state').textContent,/No final video/);
});
test('black output is excluded even when an obsolete analysis says complete',async()=>{
 states[C]={status:'failed',guard_status:'complete',output_error:'all_black',source_type:'cloud_local_guard'};
 $('#saved-runs').value=C;await $('#saved-runs').onchange();
 assert.match($('#guard-state').textContent,/black screen/);
 assert.match($('#guard-state').textContent,/not a motion failure verdict/);
 assert.equal($('#analyze-existing').disabled,true);
 assert.equal($('#guard-report').hidden,true);
 assert.equal($('#final-download').hidden,true);
 assert.doesNotMatch($('#downstream-state').textContent,/after the server recovers/);
});

test('pixel final stays bound to its run and FAIL cannot offer paid finalization',async()=>{
 states[B].pixel_followup={status:'complete',allowed:true};
 reports[B]={verdict:'PASS',failures:[],uncertain_reasons:[]};
 $('#saved-runs').value=B;await $('#saved-runs').onchange();
 assert.match($('#final-download').href,new RegExp(B+'/pixel-final.mp4'));
 assert.equal(new URL($('#final-download').href,'http://localhost').searchParams.get('preview'),'1');
 assert.ok(new URL($('#final-download').href,'http://localhost').searchParams.get('token'));
 assert.match($('#final-video').src,new RegExp(B+'/pixel-final.mp4'));
 assert.equal($('#pixel-finalize').disabled,true);
 reports[B].verdict='FAIL';states[B].pixel_followup={status:'held',allowed:false};
 await $('#saved-runs').onchange();
 assert.equal($('#final-download').href,undefined);
 assert.equal($('#pixel-finalize').disabled,true);
 assert.match($('#downstream-state').textContent,/blocked/);
 delete states[B].pixel_followup;delete reports[B];
});


test('saved analysis survives 180 polls and transient disconnect without submitting work',async()=>{
 const previousFetch=globalThis.fetch,previousTimer=globalThis.setTimeout;
 let polls=0;
 globalThis.setTimeout=callback=>setImmediate(callback);
 globalThis.fetch=async(url,...args)=>{
  if(url==='/api/jobs/'+B){polls++;if(polls===10)throw Error('offline');return {ok:true,json:async()=>({...states[B],guard_status:polls<185?'analyzing':'complete'})};}
  return previousFetch(url,...args);
 };
 try{
  $('#saved-runs').value=B;await $('#saved-runs').onchange();
  assert.equal(polls,185);assert.match($('#guard-state').textContent,/PASS/);
 }finally{globalThis.fetch=previousFetch;globalThis.setTimeout=previousTimer;}
});

test('lost submission response recovers an already finished request using GET only',async()=>{
 const old=globalThis.fetch;
 const calls=[];
 globalThis.fetch=async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>[{run_id:B}]};};
 try{const {recoverRequest}=await import('../web/generate.mjs');assert.equal(await recoverRequest('12345678-1234-1234-1234-123456789abc'),B);assert.equal(calls.length,1);assert.equal(calls[0][1],undefined);}
 finally{globalThis.fetch=old;}
});
test('generation monitor survives a disconnected GET without resubmitting',async()=>{
 const old=globalThis.fetch,timer=globalThis.setTimeout;let polls=0,posts=0;
 globalThis.setTimeout=callback=>setImmediate(callback);
 globalThis.fetch=async(url,options)=>{if(options?.method==='POST')posts++;if(url==='/api/jobs/'+B){polls++;if(polls===1)throw Error('offline');return {ok:true,json:async()=>({...states[B],status:polls===2?'running':'succeeded'})};}return old(url,options);};
 try{const {monitorRun}=await import('../web/generate.mjs');await monitorRun(B);assert.ok(polls>=3);assert.equal(posts,0);assert.equal($('#result').dataset.runId,B);}
 finally{globalThis.fetch=old;globalThis.setTimeout=timer;}
});

test('monitor preserves selected result and waits for analysis after generation finishes',async()=>{
 const old=globalThis.fetch,timer=globalThis.setTimeout;let polls=0;
 globalThis.setTimeout=callback=>setImmediate(callback);
 $('#saved-runs').value=A;await $('#saved-runs').onchange();
 globalThis.fetch=async(url,options)=>{if(url==='/api/jobs/'+B){polls++;return {ok:true,json:async()=>({...states[B],guard_status:polls<3?'analyzing':'complete'})};}return old(url,options);};
 try{const {monitorRun}=await import('../web/generate.mjs');await monitorRun(B,-1);assert.equal(polls,3);assert.equal($('#saved-runs').value,A);assert.equal($('#result').dataset.runId,A);}
 finally{globalThis.fetch=old;globalThis.setTimeout=timer;}
});

test('startup locks generation during disconnected active lookup then recovers without POST',async()=>{
 const old=globalThis.fetch,timer=globalThis.setTimeout;let active=0,release,posts=0;
 globalThis.setTimeout=callback=>setImmediate(callback);
 globalThis.fetch=async(url,options)=>{if(options?.method==='POST')posts++;if(url==='/api/active-runs'){active++;if(active===1)throw Error('offline');await new Promise(r=>release=r);return {ok:true,json:async()=>[]};}return old(url,options);};
 try{
  malformedPolicy=false;
  await import('../web/generate.mjs?startup-recovery');
  for(let i=0;i<8&&!release;i++)await tick();
  assert.equal($('#generate').disabled,true);assert.ok(release);release();await tick();await tick();
  assert.equal($('#generate').disabled,false);assert.equal(posts,0);
 }finally{globalThis.fetch=old;globalThis.setTimeout=timer;}
});


test('failed run without video cannot analyze and normal selection restores analysis',async()=>{
 const prior=states[B],old=globalThis.fetch;let posts=0;
 globalThis.fetch=async(url,options)=>{if(options?.method==='POST')posts++;return old(url,options);};
 try{
  states[B]={status:'failed',guard_status:'pending',draft_available:false};
  $('#saved-runs').value=B;await $('#saved-runs').onchange();
  assert.equal($('#analyze-existing').disabled,true);
  await $('#analyze-existing').onclick();assert.equal(posts,0);
  assert.match($('#guard-state').textContent,/No generation result/);
  states[B]=prior;await $('#saved-runs').onchange();
  assert.equal($('#analyze-existing').disabled,false);
 }finally{states[B]=prior;globalThis.fetch=old;}
});


test('missing image or prompt returns before any network request',async()=>{
 const old=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;throw Error('network must not be called');};
 try{
  for(const [files,prompt] of [[[], ''],[[], 'scene'],[[{name:'character.png'}], '']]){
   $('#character').files=files;$('#prompt').value=prompt;
   await $('#generate').onclick();assert.equal(calls,0);
   assert.match($('#generation-status').textContent,/No generation request was sent/);
  }
 }finally{globalThis.fetch=old;$('#character').files=[];$('#prompt').value='';}
});


test('unrecovered execution does not claim remote stages never ran',async()=>{
 const prior=states[B];
 try{
  states[B]={status:'failed',guard_status:'unavailable',draft_available:false,generation_status:'unconfirmed',stage2_status:'unconfirmed'};
  $('#saved-runs').value=B;await $('#saved-runs').onchange();
  assert.match($('#guard-state').textContent,/Could not confirm whether the remote generation/);
  assert.doesNotMatch($('#guard-state').textContent,/were not run/);
  assert.equal($('#analyze-existing').disabled,true);
 }finally{states[B]=prior;}
});


test('unconfirmed failed request is not labelled as actual generated video',()=>{
 const row={run_id:B,clip:'sequence',source_type:'platform_guarded',status:'failed',draft_available:false,generation_status:'unconfirmed'};
 assert.match(savedRunLabel(row),/Generation request · Result not retrieved/);
 assert.doesNotMatch(savedRunLabel(row),/Actual generation/);
 assert.match(savedRunLabel({...row,draft_available:true,guard_status:'complete',guard_verdict:'PASS'}),/PASS/);
});

test('followup navigation preserves inputs, opens framing, and never requests generation',async()=>{
 const old=globalThis.fetch;let calls=0;
 const details={open:false};
 for(const id of ['clip','framing-scale'])elements.set('#'+id,new Element());
 for(const id of ['clip','character','framing-scale']){
  const el=$('#'+id);el.value='unchanged';el.closest=()=>id==='framing-scale'?details:null;
  el.scrollIntoView=()=>el.scrolled=true;el.focus=()=>el.focused=true;
 }
 globalThis.fetch=async()=>{calls++;throw Error('navigation must not request network');};
 try{
  for(const [button,target] of [['edit-motion','clip'],['edit-character','character'],['edit-framing','framing-scale']]){
   $('#'+button).onclick();assert.equal($('#'+target).focused,true);assert.equal($('#'+target).value,'unchanged');
  }
  assert.equal(details.open,true);assert.equal(calls,0);
 }finally{globalThis.fetch=old;}
});

test('blocked idle readiness recovers with one read-only request and preserves inputs',async()=>{
 $('#character').files=[{}];$('#prompt').value='preserved input';
 policyFails=true;
 await $('#generate').onclick();
 assert.equal($('#generate').disabled,true);
 policyFails=false;malformedPolicy=false;
 const before=policyCalls, prompt=$('#prompt').value, selected=$('#saved-runs').value;
 readinessPoll();readinessPoll();
 await tick();await tick();
 assert.equal(policyCalls,before+1);
 assert.equal($('#generate').disabled,false);
 assert.equal($('#prompt').value,prompt);
 assert.equal($('#saved-runs').value,selected);
 readinessPoll();await tick();
 assert.equal(policyCalls,before+1);
});
