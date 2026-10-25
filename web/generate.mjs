import {explainFinding,explainFindingDetails,findingBody,poseSummary} from './finding-explanation.mjs';
import {mountFailureTimeline,createDraftView} from './failure-timeline.mjs';
import {createResultComparison} from './result-comparison.mjs?v=browser-preview-2';
const $=s=>document.querySelector(s),status=s=>$('#generation-status').textContent=s;
const draftView=createDraftView($('#result'),$('#comparison'),$('#download'));
let disposeTimeline=()=>{};
function dataURL(blob){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob);});}
let busy=true,reviewEpoch=0,generationAllowed=false;
window.isMotionGuardBusy=()=>busy;
const pendingKey='motion-guard-pending-request';
function remember(value){try{value?localStorage.setItem(pendingKey,value):localStorage.removeItem(pendingKey);}catch{}}
function pending(){try{return localStorage.getItem(pendingKey);}catch{return null;}}
async function readStatus(url){
 while(true){
  try{const response=await fetch(url);if(response.status===404)throw Object.assign(Error('Run record not found. No new generation request was sent.'),{missing:true});if(!response.ok)throw Error('HTTP '+response.status);return await response.json();}
  catch(e){if(e.missing)throw e;status('Connection lost · Rechecking only the existing run status in 5 s. No additional generation.');await new Promise(r=>setTimeout(r,5000));}
 }
}
const executionDetail=document.createElement('p');executionDetail.id='execution-detail';$('#generation-status').after(executionDetail);
const cancelButton=document.createElement('button');cancelButton.id='cancel-generation';cancelButton.hidden=true;cancelButton.textContent='Request cancel of current run';$('#generation-status').after(cancelButton);
let monitoredRun=null;
function showCancel(run,state){
 const pixel=['ready','submitting','running'].includes(state.pixel_followup?.status);
 const terminal=['succeeded','failed','canceled','expired','unresolved','preflight_failed','input_rejected'].includes(state.status);
 monitoredRun=run;cancelButton.hidden=terminal&&!pixel;
 cancelButton.disabled=pixel?state.pixel_cancel_requested===true:state.cancel_requested===true;
 cancelButton.textContent=cancelButton.disabled?'Cancel requested · Confirming server stop':'Request cancel of current run';
}
cancelButton.onclick=async()=>{
 const run=monitoredRun;if(!run)return;cancelButton.disabled=true;
 try{const session=await fetch('/api/session').then(r=>r.json());const r=await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-MotionGuard-Token':session.token},body:JSON.stringify({run_id:run})});if(!r.ok)throw Error('The current stage did not accept the cancel request.');status('Cancel request received · Server stop and cost settlement not yet confirmed.');}
 catch(e){status(e.message+' Continuing status checks.');}
};
export function generationProgress(run,state={}){
 const labels={saving:'Saving input',uploading:'Uploading input',submitting:'Submitting to server',queued:'Server queued',running:'Server running · detailed compute stage not received',succeeded:'Server job succeeded',failed:'Server job failed',canceled:'Canceled',expired:'Time limit expired',unresolved:'Run status unresolved',preflight_failed:'Pre-run check failed',complete:'Complete',analyzing:'Checking',held:'Follow-up run held',error:'Error'};
 const value=v=>typeof v==='string'&&v?({not_started:'Not started',unavailable:'No result',unconfirmed:'Not confirmed'}[v]||labels[v]||v):'not received';
 return `Run ID: ${run||'not received'} · Server job ID: ${state.job_id||'not received'} · Run status: ${value(state.status)} · Check status: ${value(state.guard_status)} · Follow-up status: ${value(state.downstream_status)}`;
}
// Hosted judging Space: paid actions need the access code given with the submission.
async function accessHeader(){
 const s=await fetch('/api/session').then(r=>r.json());if(!s.access_required)return {};
 let code='';try{code=sessionStorage.getItem('mg-access')||'';}catch{}
 if(!code){code=(prompt('Access code for live generation (from the submission notes)')||'').trim();try{sessionStorage.setItem('mg-access',code);}catch{}}
 return {'X-MotionGuard-Access':code};
}
const modeNote=document.createElement('p');$('#generate').after(modeNote);$('#generate').disabled=true;
const modeSelect=document.createElement('select');modeSelect.setAttribute('aria-label','Video processing mode');modeSelect.id='execution-mode';
$('#generate').before(modeSelect);
const modeLabels={cloud_local_guard:'Draft generation + motion check',platform_guarded:'Upscale if motion check passes',platform_layout:'Layout framing video + upscale after motion check'};
let modePolicies={};
let billingText="Before checking actual deduction";
export function formatBilling(b){
 const valid=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
 if(b?.status!=='last_verified'||!valid(b.account_balance_credits))return 'Account balance unconfirmed · not counted as 0. ';
 const debit=valid(b.account_decrease_credits)?`Account deduction since reference ${b.account_decrease_credits.toFixed(2)} credits`:'Balance increase such as a deposit · deduction settlement required';
 const headroom=valid(b.authorized_remaining_after_verified_debit)?`Approved-limit reference margin ${b.authorized_remaining_after_verified_debit.toFixed(2)} credits. `:'';
 return `Account balance ${b.account_balance_credits.toFixed(2)} credits · ${debit}. ${headroom}(${b.as_of}, shared account, based on reflected balance; unsettled costs may be excluded, not a run allowance). `;
}
function applyModePolicy(){
 window.motionGuardBusy=busy;window.studioForm?.refresh?.();
 const p=modePolicies[modeSelect.value];generationAllowed=p?.generation_allowed===true;
 modeNote.textContent=p?(modeSelect.value==='cloud_local_guard'?'Provides a draft and motion check. On a PASS result, a separate button can run RealESRGAN 2× upscaling. ':'Upscales only when the check is PASS. For any other verdict, follow-up processing is held. ')+`${billingText} Cumulative limit ${p.ceiling}. Separate conservative reservation total ${p.prior?.toFixed(2)} (not spending), available reservation margin ${p.remaining_reserved_budget?.toFixed(2)} credits. `+(generationAllowed?'':`Cannot run: ${p.unavailable_reason||'Settings or budget check required'} · Required reservation ${p.required_reservation}.`):'Cannot verify generation settings.';
 $('#generate').disabled=busy||!generationAllowed;
 for(const id of ['#edit-motion','#edit-character','#edit-framing']){const button=$(id);if(button)button.disabled=busy;}
}
modeSelect.onchange=()=>{window.director?.setLayoutMode?.(modeSelect.value==='platform_layout');applyModePolicy();};
let billingRefresh=null;
function refreshBillingDisplay(){
 if(billingRefresh)return billingRefresh;
 billingRefresh=(async()=>{
  for(let attempt=0;attempt<17;attempt++){
   try{
    const response=await fetch('/api/billing');if(!response.ok)break;
    const b=await response.json();
    billingText=formatBilling(b);
    applyModePolicy();if(!b.refreshing)break;
   }catch{break;}
   await new Promise(resolve=>setTimeout(resolve,2000));
  }
 })().finally(()=>{billingRefresh=null;});
 return billingRefresh;
}
let policyInFlight=null;
function refreshPolicy(){
 if(!policyInFlight)policyInFlight=refreshPolicyOnce().finally(()=>{policyInFlight=null;});
 return policyInFlight;
}
async function refreshPolicyOnce(){
 generationAllowed=false;$('#generate').disabled=true;
 try{
  const response=await fetch('/api/session');if(!response.ok)throw Error('Policy request failed');
  const s=await response.json();
  billingText=formatBilling(s.billing);
  if(!modeLabels[s.mode])throw Error('Unknown mode');
  const selected=modeSelect.value||s.mode;
  modePolicies=s.modes||{[s.mode]:s};
  modeSelect.replaceChildren(...Object.entries(modeLabels).map(([mode,label])=>{const p=modePolicies[mode];const option=new Option(label+(p?.generation_allowed===true?'':' · '+(p?.unavailable_reason||'Unavailable')),mode);option.disabled=mode!=='platform_layout'&&p?.generation_allowed!==true;return option;}));
  modeSelect.value=selected;applyModePolicy();void refreshBillingDisplay();
 }catch{modePolicies={};generationAllowed=false;for(const option of modeSelect.children)option.disabled=true;modeNote.textContent='Cannot verify generation settings, so new generation is locked. Existing results can still be viewed.';}
 $('#generate').disabled=busy||!generationAllowed;
 for(const id of ['#edit-motion','#edit-character','#edit-framing']){const button=$(id);if(button)button.disabled=busy;}
}
window.motionGuardPolicyReady=refreshPolicy();
window.setInterval?.(()=>{if(!busy&&!generationAllowed)void refreshPolicy();},15000);
const review=document.createElement('section');review.innerHTML='<h2>Source motion comparison</h2><p>Checks how closely the source timing, direction, and trajectory are followed, rather than the type of motion.</p><select id="saved-runs" aria-label="Existing generation results"></select> <button id="analyze-existing">Compare existing video · no new generation</button><p id="guard-state" role="status"></p><ul id="guard-findings"></ul><video id="guard-video" controls style="width:100%;max-width:1400px" hidden></video><p><a id="guard-report" hidden>Download check report</a></p>';
review.id='motion-review';
($('#review-mount')||document.body).append(review);
if($('#review-mount')){
 const heading=review.querySelector('h2');if(heading)heading.className='review-heading';
 const intro=review.querySelector('p');if(intro)intro.hidden=true;
 const settings=$('#execution-settings');settings.append(modeNote,executionDetail);
}
const timeline=document.createElement('div');timeline.id='guard-timeline';timeline.setAttribute('aria-label','Detected error time segments');$('#guard-video').before(timeline);
if($('#review-mount')){
 const diagnostics=document.createElement('details');diagnostics.innerHTML='<summary>Measurements · observation limits · detailed evidence</summary>';
 $('#guard-video').after(timeline);
 diagnostics.append($('#guard-findings'));timeline.after(diagnostics);
 $('#guard-video').before(document.createTextNode('Reference motion / generated video / joint comparison'));
}
const motionPair=document.createElement('section');motionPair.id='motion-pair';motionPair.hidden=true;
motionPair.innerHTML='<h3>1. Compare the reference and generated result at the same time</h3><p>Left is the 3D motion to follow, right is the actual generated video. Selecting an error segment moves both videos together.</p><div class="motion-pair-grid"><figure><figcaption>Reference 3D motion</figcaption><video id="pair-reference" playsinline></video></figure><figure><figcaption>AI-generated draft</figcaption><video id="pair-generated" playsinline></video></figure></div><button id="pair-play">Play reference and generated together</button><button id="pair-pause">Pause comparison</button><input id="pair-frame" aria-label="Reference and generated comparison time" type="range" value="0"><select id="pair-rate" aria-label="Reference and generated playback speed"><option value="1">Normal speed</option><option value="0.5">0.5× speed</option></select><p id="pair-note" role="status"></p><h3>2. Location and reason of the selected error</h3><p id="selected-finding" role="status">Select an error segment.</p>';
$('#guard-video').before(motionPair);
motionPair.append(timeline);
const scopeNote=document.createElement('p');scopeNote.textContent='Check scope: on-screen motion and timing of the main observable joints, compared as 2D positions (a whole-clip average over moving frames plus a per-joint sustained-error check over every frame). Head and neck direction (nose, neck, eyes, ears), torso bend, face, clothing, background objects, smudges, and physical foot contact are not judged. Fingers are judged only where the 3D reference shows the fingertip visible. PASS is also not a guarantee of overall video quality.';motionPair.append(scopeNote);
const pairVideos=[$('#pair-reference'),$('#pair-generated')];
const pairView=createResultComparison(motionPair,pairVideos,$('#pair-play'),$('#pair-pause'),$('#pair-frame'),$('#pair-rate'),$('#pair-note'));
const nextAction=document.createElement('p');nextAction.id='review-next-action';review.append(nextAction);
const reviewActions=document.createElement('div');reviewActions.id='review-actions';reviewActions.hidden=true;review.append(reviewActions);
for(const [id,label,targetId] of [['edit-motion','Go to motion selection','clip'],['edit-character','Change character image','character'],['edit-framing','Go to framing adjustment','framing-scale']]){
 const button=document.createElement('button');button.id=id;button.type='button';button.textContent=label;reviewActions.append(button);
 button.onclick=()=>{
  if(busy)return;
  const target=$('#'+targetId);if(!target||target.disabled)return;
  const details=target.closest('details');if(details)details.open=true;
  target.scrollIntoView({block:'center',behavior:'smooth'});target.focus({preventScroll:true});
 };
}
const reviewDraft=document.createElement('a');reviewDraft.id='review-draft-download';reviewDraft.textContent='Download current draft';reviewDraft.setAttribute('download','motion-guard-draft.mp4');reviewDraft.hidden=true;review.append(reviewDraft);
let findingSelection=0;
const findingDetails=document.createElement('details');findingDetails.id='finding-details';findingDetails.hidden=true;motionPair.append(findingDetails);
async function selectFinding(f,start,epoch,report){
 const selection=++findingSelection;
 const body=findingBody(f,jointNames);
 const explanation=explainFinding(f,body,report);
 const detail=findingDetails;detail.hidden=false;detail.replaceChildren();detail.open=false;
 const title=document.createElement('summary');title.textContent='Measurement basis and interpretation';
 const text=document.createElement('p');text.textContent=explainFindingDetails(f,body,report);detail.append(title,text);
 $('#selected-finding').textContent=explanation+' · Preparing same time';
 const deadline=Date.now()+5000;
 while(pairVideos.some(v=>v.readyState<1)){
  if(epoch!==reviewEpoch||selection!==findingSelection)return;
  if(Date.now()>deadline){$('#selected-finding').textContent=explanation+' · Comparison video load delayed. Seek completion could not be confirmed.';return;}
  await new Promise(r=>setTimeout(r,25));
 }
 if(epoch!==reviewEpoch||selection!==findingSelection)return;
 pairView.seek(start);
 while(pairVideos.some(v=>v.seeking||v.readyState<2)){
  if(epoch!==reviewEpoch||selection!==findingSelection)return;
  if(Date.now()>deadline)break;
  await new Promise(r=>setTimeout(r,25));
 }
 if(epoch!==reviewEpoch||selection!==findingSelection)return;
 const matched=pairVideos.every(v=>!v.seeking&&v.readyState>=2&&Math.abs(v.currentTime-start)<0.08);
 $('#selected-finding').textContent=explanation+(matched?` · Both videos ${start.toFixed(2)}s seek confirmed`:' · Could not confirm synchronized seek of both videos.');
}
const finalResult=document.createElement('p');finalResult.innerHTML='<span id="downstream-state"></span> <a id="final-download" download="motion-guard-final.mp4" hidden>Download final video</a>';review.append(finalResult);
const pixelButton=document.createElement('button');pixelButton.id='pixel-finalize';pixelButton.hidden=true;
pixelButton.textContent='Upscale the checked draft 2× · paid, once';review.append(pixelButton);
const heldDraft=document.createElement('a');heldDraft.id='held-draft';heldDraft.hidden=true;heldDraft.textContent='Go to the reference-draft comparison and draft download for this run';review.append(heldDraft);
const finalCompare=document.createElement('section');finalCompare.id='final-compare';finalCompare.hidden=true;
finalCompare.innerHTML='<h2>Final comparison</h2><div style="display:flex;flex-wrap:wrap;gap:12px"><figure style="margin:0;flex:1;min-width:240px"><figcaption>Reference 3D motion</figcaption><video id="final-reference" style="width:100%" playsinline></video></figure><figure style="margin:0;flex:1;min-width:240px"><figcaption>AI draft</figcaption><video id="final-draft" style="width:100%" playsinline></video></figure><figure style="margin:0;flex:1;min-width:240px"><figcaption>Upscaled final</figcaption><video id="final-video" style="width:100%" playsinline></video></figure></div><button id="compare-play">Play together</button><button id="compare-pause">Pause</button><input id="compare-frame" aria-label="Common comparison frame" type="range" min="0" max="96" value="0"><select id="compare-rate" aria-label="Comparison playback speed"><option value="1">Normal speed</option><option value="0.5">0.5× speed</option></select><p id="compare-note" role="status"></p>';
review.append(finalCompare);
const finalView=createResultComparison(finalCompare,[$('#final-reference'),$('#final-draft'),$('#final-video')],$('#compare-play'),$('#compare-pause'),$('#compare-frame'),$('#compare-rate'),$('#compare-note'));
const technical=document.createElement('details');technical.innerHTML='<summary>Development info · Model · License</summary><p>Provides the currently saved configuration and the selected run record separately. If the exact remote model version of a past run was not recorded, it is unconfirmed.</p><p><a id="technical-run" hidden target="_blank" rel="noopener">View selected run technical record · Workflow hash · Build/model configuration</a></p><p><a href="/info/install" target="_blank" rel="noopener">Install and run guide</a> · <a href="/info/licenses" target="_blank" rel="noopener">Model and asset licenses</a> · <a href="/info/license-scope" target="_blank" rel="noopener">Distribution rights scope</a></p>';review.append(technical);
$('#guard-report').download='motion-guard-report.json';
const meanings={PASS:'Check criterion met within observable range',FAIL:'Movement different from the original found',UNCERTAIN:'Insufficient evidence · cannot confirm motion match',ERROR:'Check error · generated video preserved'};
const jointNames={2:'Right shoulder',3:'Right elbow',4:'Right hand',5:'Left shoulder',6:'Left elbow',7:'Left hand',8:'Right hip',9:'Right knee',10:'Right ankle',11:'Left hip',12:'Left knee',13:'Left ankle'};for(const [side,off] of [['Left',91],['Right',112]])for(const [tip,name] of [[4,'thumb'],[8,'index finger'],[12,'middle finger'],[16,'ring finger'],[20,'little finger']])jointNames[off+tip]=`${side} ${name}`;
const types={WRONG_POSE:'Pose difference',WRONG_SIDE:'Left-right motion difference',WRONG_DIRECTION:'Movement direction difference',TIMING_MISMATCH:'Timing difference',MISSING_MOTION:'Missing motion'};
const reasons={insufficient_active_coverage:'Too few of the moving joints were reliably compared.',insufficient_active_frames:'Not enough frames to confirm movement.',M1_insufficient_evidence:'Insufficient joint evidence to judge the overall pose.',side_unjudgeable:'Insufficient evidence to distinguish left from right.',periodic_or_ambiguous_lag:'Several similar lag candidates exist, so it could not be confirmed whether the timing matches the original.',inactive_or_constant_speed:'Not enough speed variation to measure the lag.',M5_insufficient_evidence:'Insufficient evidence to judge missing motion.'};
function clearReview(){
 $('#technical-run').hidden=true;$('#technical-run').removeAttribute('href');
 findingDetails.hidden=true;findingDetails.replaceChildren();
 ++findingSelection;pairView.clear();reviewDraft.hidden=true;reviewDraft.removeAttribute('href');nextAction.textContent='';reviewActions.hidden=true;$('#selected-finding').textContent='';
 pixelButton.hidden=true;pixelButton.onclick=null;
 finalView.clear();
 disposeTimeline();disposeTimeline=()=>{};
 review.dataset.guardError='false';
 review.dataset.analysisUnavailable='true';
 $('#analyze-existing').disabled=true;
 $('#guard-video').hidden=true;$('#guard-report').hidden=true;$('#guard-findings').replaceChildren();
 $('#guard-video').removeAttribute('src');$('#guard-report').removeAttribute('href');
 $('#downstream-state').textContent='';$('#final-download').hidden=true;$('#final-download').removeAttribute('href');
 heldDraft.hidden=true;heldDraft.removeAttribute('href');
}
// Draft background-object warning from the server. Quality only: it never changes the motion verdict.
function showBackgroundCheck(run,check,epoch,tries=0){
 if(!check||epoch!==reviewEpoch)return;
 let li=$('#background-check');
 if(!li){li=document.createElement('li');li.id='background-check';$('#guard-findings').append(li);}
 if(check.status==='warning')li.textContent='Review needed (quality warning, not part of the motion verdict): something appears in the empty background at '+check.intervals.map(i=>`${i.t_start_s.toFixed(2)}–${i.t_end_s.toFixed(2)} s near (${i.x}, ${i.y})`).join(', ')+'. Check the draft at those times.';
 else if(check.status==='clear')li.textContent='Background check: no object appeared and disappeared in the empty background.';
 else if(check.status==='pending')li.textContent='Background check running…';
 else li.textContent='Background check not run: '+(check.reason||'unavailable')+'.';
 if(check.status==='pending'&&tries<20)setTimeout(()=>fetch('/api/jobs/'+run).then(r=>r.json()).then(s=>showBackgroundCheck(run,s.background_check,epoch,tries+1)).catch(()=>{}),3000);
}
// Head-position warning from the server. Quality only: head and neck are outside the motion verdict.
function showHeadCheck(run,check,epoch,tries=0){
 if(!check||epoch!==reviewEpoch)return;
 let li=$('#head-check');
 if(!li){li=document.createElement('li');li.id='head-check';$('#guard-findings').append(li);}
 if(check.status==='warning')li.textContent='Review needed (quality warning, not part of the motion verdict): the head stays away from the reference head position at '+check.intervals.map(i=>`${i.t_start_s.toFixed(2)}–${i.t_end_s.toFixed(2)} s`).join(', ')+' (for example a bowed head or hunched posture).';
 else if(check.status==='clear')li.textContent='Head-position check: no sustained difference from the reference head position.';
 else if(check.status==='pending')li.textContent='Head-position check running…';
 else li.textContent='Head-position check not run: '+(check.reason||'unavailable')+'.';
 if(check.status==='pending'&&tries<20)setTimeout(()=>fetch('/api/jobs/'+run).then(r=>r.json()).then(s=>showHeadCheck(run,s.head_check,epoch,tries+1)).catch(()=>{}),3000);
}
function showGuardError(state){
 clearReview();
 review.dataset.guardError='true';
 if(state.output_error==='all_black'){
  $('#guard-state').textContent='ERROR · The whole generated video is a black screen. This is not a motion failure verdict.';
  $('#downstream-state').textContent='Excluded from the motion check and upscale. The original record is preserved and not retried automatically. Motion cannot be judged from this video.';
  $('#analyze-existing').disabled=true;return;
 }
 $('#guard-state').textContent='ERROR · Movement could not be checked. This differs from a motion failure verdict for the video.';
 const missingModel=String(state.error||'').includes('No such file')&&String(state.error||'').includes('motion_guard');
 const li=document.createElement('li');li.textContent=missingModel?'Cause: The motion check model file was not found on the server.':'Cause: An error occurred while running the motion check or retrieving its result.';$('#guard-findings').append(li);
 $('#downstream-state').textContent='No final video · Not regenerated or retried automatically. You can select another saved result to review. Re-checking this result is possible after the server recovers.';
 $('#analyze-existing').disabled=true;
}
function showDownstream(state,run,token,verdict){
 const failed=['failed','canceled','expired','unresolved','preflight_failed'].includes(state.status);
 const done=state.downstream_status==='complete';
 const available=!failed&&state.status==='succeeded'&&done&&verdict==='PASS'&&state.final_available===true;
 $('#final-download').hidden=!available;
 if(available)$('#final-download').href='/results/'+run+'/final.mp4?preview=1&token='+encodeURIComponent(token);
 else $('#final-download').removeAttribute('href');
 if(available)finalView.show(run,token);else finalView.clear();
 $('#downstream-state').textContent=available?'Upscale complete after check passed':failed||state.downstream_status==='error'?'Follow-up run or result retrieval error · check result preserved':state.downstream_status==='held'?'Follow-up upscale held based on check verdict':done?'Final video state mismatch · download held':'Checking follow-up result';
 heldDraft.hidden=true;heldDraft.removeAttribute('href');
 if(!failed&&state.downstream_status==='held'){
  const reason=verdict==='UNCERTAIN'?'Could not confirm whether the motion matches. It is not confirmed as a motion failure.':verdict==='FAIL'?'Found movement different from the original.':'The check was not passed.';
  $('#downstream-state').textContent=reason+' Upscale held · No final video. Not regenerated automatically. A new generation runs only when you select the Generate button above.';
  if(state.draft_available===true&&$('#result').dataset.runId===run&&!$('#result').hidden){heldDraft.href='#result';heldDraft.hidden=false;}
 }
 return failed||['complete','held','error'].includes(state.downstream_status);
}
async function waitDownstream(state,run,token,verdict,epoch){
 for(let i=0;i<600;i++){
  if(epoch!==reviewEpoch)return;
  executionDetail.textContent=generationProgress(run,state);
  if(showDownstream(state,run,token,verdict))return;
  await new Promise(r=>setTimeout(r,1000));
  if(epoch!==reviewEpoch)return;
  const response=await fetch('/api/jobs/'+run);
  if(!response.ok)throw Error('Follow-up result status lookup failed · Not regenerated automatically.');
  state=await response.json();
 }
 if(epoch===reviewEpoch)$('#downstream-state').textContent='Follow-up result wait timed out · Not regenerated automatically. Select the saved result again to check its status.';
}
function showPixel(state,run,token,verdict,epoch){
 if(state.pixel_followup&&(monitoredRun===run||['ready','submitting','running'].includes(state.pixel_followup.status)))showCancel(run,state);
 const p=state.pixel_followup;
 pixelButton.hidden=false;pixelButton.disabled=busy||verdict!=='PASS'||!!p;
 const complete=verdict==='PASS'&&p?.status==='complete'&&p.allowed===true;
 if(complete){
  $('#final-download').href=`/results/${run}/pixel-final.mp4?preview=1&token=${encodeURIComponent(token)}`;
  $('#final-download').hidden=false;finalView.show(run,token,'pixel-final');
 }
 $('#downstream-state').textContent=complete?'2× pixel upscale complete · RealESRGAN. You can compare the source motion, draft, and final video at the same time.':verdict!=='PASS'?'Upscale is blocked because the motion check was not passed. No final video will be created.':p?`Pixel upscale status: ${p.status}. Not retried automatically.`:'PASS · Pressing the button below upscales the draft 2× with RealESRGAN. This is different from LTX 2-stage generation and incurs an additional cost. It does not run just by selecting an existing result.';
 pixelButton.onclick=async()=>{
  if(busy||epoch!==reviewEpoch)return;
  busy=true;pixelButton.disabled=true;applyModePolicy();
  try{
   const response=await fetch('/api/finalize',{method:'POST',headers:{'Content-Type':'application/json','X-MotionGuard-Token':token,...await accessHeader()},body:JSON.stringify({run_id:run})});
   if(!response.ok)throw Error('Could not start the follow-up run. Not retried automatically.');
   for(let i=0;i<650&&epoch===reviewEpoch;i++){
    const result=await fetch('/api/jobs/'+run);if(!result.ok)throw Error('Follow-up status lookup failed');
    const latest=await result.json();if(epoch!==reviewEpoch)return;
    showPixel(latest,run,token,verdict,epoch);
    if(['complete','held','error','unresolved'].includes(latest.pixel_followup?.status))break;
    await new Promise(r=>setTimeout(r,1000));
   }
  }catch(e){if(epoch===reviewEpoch)$('#downstream-state').textContent=e.message;}
  finally{busy=false;applyModePolicy();void refreshBillingDisplay();}
 };
}
async function showGuard(run,token,epoch=++reviewEpoch){
 clearReview();
 $('#technical-run').href='/api/technical/'+run;$('#technical-run').hidden=false;
 while(epoch===reviewEpoch){
  let state;
  try{
   const response=await fetch('/api/jobs/'+run);
   if(!response.ok)throw Error('HTTP '+response.status);
   state=await response.json();
  }catch(e){
   if(epoch!==reviewEpoch)return;
   $('#guard-state').textContent='Check status connection lost · Rechecking only the status in 5 s. No additional generation.';
   await new Promise(r=>setTimeout(r,5000));continue;
  }
  if(epoch!==reviewEpoch)return;
  executionDetail.textContent=generationProgress(run,state);
  if(state.output_error||state.guard_status==='error'){showGuardError(state);return;}
  if(state.guard_status==='complete'){
   const base='/results/'+run+'/guard/',query='?token='+encodeURIComponent(token);
   const response=await fetch(base+'report.json'+query);if(!response.ok)throw Error('Cannot read the check result.');const report=await response.json();
   if(epoch!==reviewEpoch)return;
   const displayed=report.display_failures??report.failures;
   review.dataset.analysisUnavailable='false';$('#analyze-existing').disabled=busy;
   $('#guard-state').textContent=report.verdict+' · '+meanings[report.verdict]+(state.local_reanalysis?' · Existing video CPU re-analysis':'')+(report.observation_policy?.strict_report?.verdict==='UNCERTAIN'?' · Provisional: calibration-candidate observation policy, strict policy UNCERTAIN':'');
   pairView.show(run,token);
   reviewDraft.href=`/results/${run}/generated.mp4?preview=1`;reviewDraft.hidden=false;
   $('#selected-finding').textContent=displayed.length?'Select an error segment below. The reference and generated videos pause at the same time and the detection reason is shown.':report.verdict==='PASS'?'No confirmed error segment within the check scope. Play together and also check quality outside the check scope, such as appearance, hands, and face.':'No confirmed error does not mean it is judged normal. Check the insufficient-observation segments and detailed evidence below.';
   reviewActions.hidden=false;
   nextAction.textContent='3. How should the result be handled? '+(report.verdict==='PASS'?'Observable motion check passed. Check the actual follow-up status below and download the final or draft. Upscaling raises resolution and detail; it does not fix motion errors.':report.verdict==='FAIL'?'Compare whether the selected differences are acceptable for your purpose. Upscale will not proceed for this verdict. You can download the draft; to regenerate, change the motion, image, framing, or description in the inputs above and then choose a new generation. A new generation incurs a separate cost; check the reserved amount under processing mode. No automatic fixing or regeneration.':'Insufficient evidence to judge a match, so upscale will not proceed. Check occlusion and framing in the unobservable segments and review the draft. A new generation runs only when you select it yourself after changing the inputs.');
   if(state.source_type==='controlled_video_test'){const li=document.createElement('li');li.textContent='Derived validation video · A case where 6.000–7.625 s of the original was deliberately frozen. It is not a new AI generation or a naturally occurring failure.';$('#guard-findings').append(li);}
   if(state.source_type==='reused_local_guard'){const li=document.createElement('li');li.textContent='Local check result of an already generated draft · No new generation or new estimation. The original server check was ERROR and is preserved separately from this local result.';$('#guard-findings').append(li);$('#downstream-state').textContent='Local check result reviewed · Upscale not run · Cost savings not measured';}
   reasons.timing_attribution_unjudgeable='Insufficient evidence to confirm a timing difference.';
   if(state.source_type==='imported_calibration'){const li=document.createElement('li');li.textContent='Imported existing video · Not a new generation · Calibration data';$('#guard-findings').append(li);$('#downstream-state').textContent='No follow-up submission from this import · No final video. Check the error segments and comparison video, or select another saved result. This is not evidence of an actual paid upscale being blocked.';}
   for(const reason of report.uncertain_reasons||[]){const li=document.createElement('li');li.textContent=reasons[reason]||reason;$('#guard-findings').append(li);}
   const coverage=report.coverage?.active_valid_joint_fraction;if(Number.isFinite(coverage)){const li=document.createElement('li');li.textContent=`Comparable share of moving joints: ${(coverage*100).toFixed(1)}% · This is not an accuracy score.`;$('#guard-findings').append(li);}
   showBackgroundCheck(run,state.background_check,epoch);showHeadCheck(run,state.head_check,epoch);
   for(const f of displayed){const li=document.createElement('li');const body=findingBody(f,jointNames);li.textContent=`${f.t_start_s.toFixed(2)}–${f.t_end_s.toFixed(2)}s · ${types[f.type]||f.type} · ${body}`;if(f.evidence?.metric_name==='M5_joint_energy'&&Number.isFinite(f.evidence.metric_value)){li.textContent+=` · Minimum on-screen movement across all observation windows of this joint: relative to reference ${(f.evidence.metric_value*100).toFixed(1)}%`; }$('#guard-findings').append(li);}
   if(report.observation_policy){const li=document.createElement('li');li.textContent='Observation policy revision candidate applied · Left-right check keeps the existing strict policy · This single result does not guarantee general accuracy.';$('#guard-findings').append(li);}
   if(state.source_type==='platform_guarded')showDownstream(state,run,token,report.verdict);
   else if(!['imported_calibration','reused_local_guard'].includes(state.source_type))$('#downstream-state').textContent='Motion check complete · This run only performed draft generation and the check. There is no upscaled final video. Draft download is available.';
   const framing=report.framing_diagnostic;
   if(framing){const li=document.createElement('li');const last=framing.frames?.filter(x=>x.observed).at(-1);if(framing.status==='DIAGNOSTIC_ONLY'&&last){li.textContent=`Size and position reference measurement · initial valid ${framing.baseline_frames.length}frames (${framing.baseline_frames.join(', ')}) on-screen torso ratio change ${(last.relative_to_baseline*100).toFixed(1)}% · last valid frame ${last.frame} (${last.time_s.toFixed(2)}s) · hip position residual ${last.hip_residual_distance_px.toFixed(1)}px (in reference torso lengths: ${last.hip_residual_reference_torso_lengths.toFixed(2)}×). Includes the effects of pose, rotation, and viewpoint; this does not determine physical growth or a cause of pose error. Not used for automatic failure verdicts.`;}else{li.textContent=framing.status==='ERROR'?'Size and position reference measurement error · Separate from the motion verdict.':'Size and position reference measurement: insufficient valid torso observations.';}$('#guard-findings').append(li);}
   if(!displayed.length){const li=document.createElement('li');li.textContent=report.verdict==='PASS'?'No error segments were detected within the check scope.':report.verdict==='FAIL'?`Overall verdict FAIL · Raw evidence for ${report.display_policy?.suppressed_short_intervals??0} segments below the continuous display threshold was preserved in the detailed report.`:'No confirmed error segments. This does not mean the unjudgeable parts are normal.';$('#guard-findings').append(li);}
   const note=document.createElement('li');note.textContent='Left: source · Center: AI result · Right: joint comparison. Outside the motion check scope: appearance, face, props, image quality, smudges, physical foot contact. Fingers are judged only where the 3D reference shows them. On-screen motion amount is not interpreted as actual stride length.';$('#guard-findings').append(note);
   $('#guard-video').onerror=()=>{if(epoch===reviewEpoch){clearReview();$('#guard-state').textContent='ERROR · Cannot read the saved comparison video. Not regenerated automatically.';}};
   $('#guard-video').src=base+'overlay.mp4'+query;$('#guard-video').hidden=false;$('#guard-report').href=base+'report.json'+query;$('#guard-report').hidden=false;
   let observation=report.observation_gaps;
   if(observation?.status!=='available'){
    try{
     const supplementResponse=await fetch(base+'observation-gaps.json'+query);
     if(supplementResponse.ok){const supplement=await supplementResponse.json();if(supplement.status==='available')observation=supplement.observation_gaps;}
    }catch{/* Keep absent observations explicit. */}
    if(epoch!==reviewEpoch)return;
   }
   const gaps=observation?.status==='available'?observation.intervals:null;
   const coverageNote=document.createElement('li');
   coverageNote.textContent=gaps?`Insufficient wrist and ankle comparison evidence in the motion-amount and pose checks: ${gaps.length} segments (6 or more consecutive frames). The observation range of the left-right verdict is separate, and PASS does not guarantee these segments are normal.`:'This report has no detailed observation gap information for wrists and ankles.';
   $('#guard-findings').append(coverageNote);
   const gapReasons={unavailable:'No reference joint',visibility_evidence:'Insufficient visibility evidence',reference_gt_error:'Reference estimate and 3D coordinates disagree',reference_score:'Insufficient reference estimate confidence',generated_score:'Insufficient generated estimate confidence'};
   disposeTimeline=mountFailureTimeline(timeline,$('#guard-video'),[...displayed,...(gaps||[])],f=>`${f.t_start_s.toFixed(2)}–${f.t_end_s.toFixed(2)}s · ${f.type==='OBSERVATION_GAP'?'Cannot check · '+Object.keys(f.excluded_reason_counts||{}).map(k=>gapReasons[k]||k).join(', '):types[f.type]||f.type} · ${findingBody(f,jointNames)}`, (f,start)=>{void selectFinding(f,start,epoch,report);}, poseSummary(report)+` · Short segments ${report.display_policy?.suppressed_short_intervals??0} excluded from cards (raw verdict evidence preserved)`);
   if(state.source_type==='platform_guarded')await waitDownstream(state,run,token,report.verdict,epoch);
   else showPixel(state,run,token,report.verdict,epoch);
   return;
  }
  $('#guard-state').textContent='Comparing source and generated video · No additional generation cost';await new Promise(r=>setTimeout(r,1000));
 }

}
async function loadSaved(){const epoch=++reviewEpoch;draftView.begin(epoch);clearReview();executionDetail.textContent='';const run=$('#saved-runs').value;if(!run){$('#guard-state').textContent='No saved generation results.';return;}executionDetail.textContent=generationProgress(run);$('#guard-state').textContent='Checking saved result';try{const state=await fetch('/api/jobs/'+run).then(r=>r.json());if(epoch!==reviewEpoch)return;executionDetail.textContent=generationProgress(run,state);draftView.show(run,state,epoch);if(['failed','preflight_failed','input_rejected','canceled','expired'].includes(state.status)&&!state.draft_available&&!state.output_error&&state.guard_status!=='error'){$('#guard-state').textContent=state.generation_status==='unconfirmed'||state.stage2_status==='unconfirmed'?'Result not retrieved · Could not confirm whether the remote generation, check, or follow-up processing ran. There is no video to download and no automatic retry.':'No generation result · No video was produced for this run, so the motion check and upscale were not run.';return;}review.dataset.analysisUnavailable='false';$('#analyze-existing').disabled=busy;if(state.output_error||state.guard_status==='error'){showGuardError(state);}else if(['complete','analyzing'].includes(state.guard_status)){const session=await fetch('/api/session').then(r=>r.json());if(epoch===reviewEpoch)await showGuard(run,session.token,epoch);}else{$('#guard-state').textContent=state.guard_status==='error'?meanings.ERROR:state.guard_status==='analyzing'?'Check in progress · Select again after it completes to view.':'This video has not been checked yet. You can analyze it with the compare button.';}}catch(e){if(epoch===reviewEpoch){clearReview();$('#guard-state').textContent='ERROR · '+e.message;}}}
let selectionVersion=0;
$('#saved-runs').onchange=()=>{selectionVersion++;return loadSaved();};
export function savedRunLabel(x){
 if(['failed','preflight_failed','input_rejected','canceled','expired'].includes(x.status)&&x.draft_available===false)return `${x.clip} · Generation request · ${x.generation_status==='unconfirmed'||x.stage2_status==='unconfirmed'?'Result not retrieved':'Generation failed'} · ${x.run_id.slice(-8)}`;
 const source={cloud_local_guard:'Actual generation',platform_guarded:'Actual generation',imported_calibration:'Existing calibration data',controlled_video_test:'Artificial-defect test'}[x.source_type]||'Existing data · source unconfirmed';
 const verdict=x.output_error?'Output error':x.guard_status==='error'?'Check error':x.guard_status==='analyzing'?'Checking':x.guard_status==='complete'?(x.guard_verdict||'Verdict unconfirmed'):'Not checked';
 return `${x.clip} · ${source} · ${verdict} · ${x.run_id.slice(-8)}`;
}
async function savedRuns(selected=$('#saved-runs').value,display=true){const rows=await fetch('/api/completed-runs').then(r=>r.json());$('#saved-runs').replaceChildren(...rows.map(x=>new Option(savedRunLabel(x),x.run_id)));if(selected&&!rows.some(x=>x.run_id===selected))$('#saved-runs').append(new Option('No result video · '+selected.slice(-8),selected));if(selected)$('#saved-runs').value=selected;if(display)await loadSaved();}
export async function monitorRun(run,selection=selectionVersion){
 while(true){
  const state=await readStatus('/api/jobs/'+run);
  executionDetail.textContent=generationProgress(run,state);showCancel(run,state);status('Generation status: '+state.status);
  if(['succeeded','failed','canceled','expired','unresolved','preflight_failed','input_rejected'].includes(state.status)&&state.guard_status!=='analyzing'&&!['ready','submitting','running'].includes(state.pixel_followup?.status)){
   if(state.status!=='unresolved'&&state.pixel_followup?.status!=='unresolved')remember(null);
   const display=selectionVersion===selection;
   await savedRuns(display?run:$('#saved-runs').value,display);
   status(state.status==='succeeded'?'Video generation complete · Check the verdict and download.':state.status==='unresolved'?'Run status unresolved · Records preserved without additional generation.':'Job '+state.status+' · '+(state.draft_available?'Retrieved draft and records preserved.':'No result video. Run records preserved.'));return state;
  }
  await new Promise(r=>setTimeout(r,2000));
 }
}
export async function recoverRequest(id){
 for(let i=0;i<12;i++){
  const rows=await readStatus('/api/requests/'+id);
  if(rows.length===1)return rows[0].run_id;
  if(rows.length>1)throw Error('Multiple run records exist for the same request. Further submissions are blocked.');
  status('Checking submission response · No resend of the generation request');await new Promise(r=>setTimeout(r,5000));
 }
 throw Error('Submission result unresolved · Request identifier preserved. Refreshing will look it up again. No additional submission.');
}
async function restoreActive(){
 const id=pending();
 try{
  const recovered=id?await recoverRequest(id):null;
  const rows=await readStatus('/api/active-runs');
  if(recovered&&!rows.some(row=>row.run_id===recovered))rows.push({run_id:recovered});
  if(!rows.length){busy=false;await refreshPolicy();$('#analyze-existing').disabled=busy||review.dataset.guardError==='true'||review.dataset.analysisUnavailable==='true';return;}
  busy=true;applyModePolicy();$('#analyze-existing').disabled=true;
  if(rows.length!==1){status('Multiple active run records · New generation blocked. Run records need to be checked.');return;}
  const state=await monitorRun(rows[0].run_id);
  busy=!!pending()||state.status==='unresolved'||state.pixel_followup?.status==='unresolved';await refreshPolicy();
 }catch(e){busy=true;status(e.message);applyModePolicy();}
}
$('#analyze-existing').onclick=async()=>{if(busy||review.dataset.analysisUnavailable==='true'||review.dataset.guardError==='true')return;const run=$('#saved-runs').value;if(!run)return;busy=true;$('#analyze-existing').disabled=true;$('#saved-runs').disabled=true;try{const session=await fetch('/api/session').then(r=>r.json());const response=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json','X-MotionGuard-Token':session.token},body:JSON.stringify({run_id:run})});if(!response.ok)throw Error('Another job is running, or the analysis input cannot be verified.');await showGuard(run,session.token);}catch(e){$('#guard-state').textContent=e.message;}finally{busy=false;$('#analyze-existing').disabled=busy||review.dataset.guardError==='true'||review.dataset.analysisUnavailable==='true';$('#saved-runs').disabled=false;}};
savedRuns().catch(()=>{$('#guard-state').textContent='Existing videos can be loaded after connecting to the generation server.';});
void restoreActive();
function inputError(id,message){
 const field=$('#'+id);field.setAttribute('aria-invalid',message?'true':'false');
 const note=$('#'+id+'-error');if(note)note.textContent=message;
}
$('#character').addEventListener('change',()=>{if($('#character').files[0])inputError('character','');});
$('#prompt').addEventListener('input',()=>{if($('#prompt').value.trim())inputError('prompt','');});
$('#generate').onclick=async()=>{
 if(!generationAllowed){status('New generation is currently disabled. You can use existing video comparison.');return;}
 if(busy)return;
 const blocked=window.studioForm?.blockReason?.();if(blocked){status(blocked);return;}
 const executionMode=modeSelect.value;
 const image=$('#character').files[0],prompt=$('#prompt').value.trim();
 inputError('character',image?'':'A character image is required. Select an image file above.');
 inputError('prompt',prompt?'':'A scene description is required. Enter the appearance, background, and framing.');
 if(!image||!prompt){status('No generation request was sent · '+[!image?'Character image missing':'',!prompt?'Scene description missing':''].filter(Boolean).join(' · '));return;}
 busy=true;applyModePolicy();const generationEpoch=++reviewEpoch;draftView.begin(generationEpoch);clearReview();executionDetail.textContent='Preparing input · Run ID and server job ID not received';const controls=[...document.querySelectorAll('#studio input,#studio select,#studio textarea,#framing-reset,#play,#export,#prepare-look-frame,#generate,#pixel-finalize')];controls.forEach(x=>x.disabled=true);
 try{
  await window.director.ready();
  window.director.stop();
  const session=await fetch('/api/session').then(r=>r.json());if(!session.token)throw Error('The generation server is not connected.');
  const meta=window.director.metadata();
  const model=await fetch(meta.source).then(r=>{if(!r.ok)throw Error('Cannot read the model input.');return r.blob();});
  const frames=[];for(let i=0;i<meta.frames;i++){frames.push(window.director.frame(i));if(i%8===0){status(`Preparing reference motion ${i+1}/${meta.frames}`);await new Promise(r=>requestAnimationFrame(r));}}
  status('Validating and uploading input');
  const requestId=crypto.randomUUID();
  const body=JSON.stringify({request_id:requestId,execution_mode:executionMode,model:await dataURL(model),image:await dataURL(image),prompt,meta,frames});
  if(new Blob([body]).size>120*1024*1024)throw Error('The input bundle exceeds 120MiB. No generation request was sent. Select a shorter segment.');
  remember(requestId);
  let started;
  try{
   const response=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json','X-MotionGuard-Token':session.token,...await accessHeader()},body});
   const reply=await response.json();
   if(!response.ok){remember(null);if(response.status===403){try{sessionStorage.removeItem('mg-access');}catch{}}throw Object.assign(Error(reply.error||'Input failed'),{rejected:true});}
   started=reply;
  }catch(e){if(e.rejected)throw e;started={run_id:await recoverRequest(requestId)};}
  window.lastRun=started.run_id;
  await monitorRun(started.run_id);
 }catch(e){status(e.message);}finally{busy=!!pending();controls.forEach(x=>x.disabled=false);await refreshPolicy();$('#analyze-existing').disabled=busy||review.dataset.guardError==='true'||review.dataset.analysisUnavailable==='true';}
};
