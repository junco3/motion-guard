import {loadForm,saveForm,imageProblem} from './form-state.mjs';
const imageInput=document.querySelector('#character');
const preview=document.querySelector('#character-preview');
let previewUrl;
imageInput.addEventListener('change',()=>{
 if(previewUrl)URL.revokeObjectURL(previewUrl);
 previewUrl=null;
 const file=imageInput.files[0];preview.hidden=!file;
 if(file){previewUrl=URL.createObjectURL(file);preview.src=previewUrl;document.querySelector('#character-hint').textContent=file.name;}
 else{preview.removeAttribute('src');document.querySelector('#character-hint').textContent='Add the character that appears in the scene';}
});

const framingImage=document.querySelector("#framing-image"),framingToggle=document.querySelector("#framing-overlay");
function updateFramingImage(){framingImage.hidden=!framingToggle.checked||!previewUrl;if(previewUrl)framingImage.src=previewUrl;else framingImage.removeAttribute("src");}
framingToggle.addEventListener("change",updateFramingImage);imageInput.addEventListener("change",updateFramingImage);

const field=id=>document.getElementById(id);
let storage;try{storage=sessionStorage;}catch{}
const saved=loadForm(storage);
let restoring=!!saved,customNeedsFile=saved?.customFile===true,customSelected=false,imageCheck='',imageEpoch=0,restored=false,restoreError='';
field('studio').inert=restoring;
function persist(){
 if(restoring)return;
 const data={version:1,customFile:customSelected||customNeedsFile,hadImage:!!imageInput.files[0]};
 for(const id of ['sample','clip','angle','duration','framing-scale','framing-y','prompt','execution-mode'])data[id]=field(id)?.value;
 data['repeat-clip']=field('repeat-clip').checked;saveForm(storage,data);
}
function blockReason(){
 if(restoring)return 'Restoring inputs. Please wait.';
 if(restoreError)return 'Input restoration did not finish. Select the reference model yourself, then check the inputs.';
 if(customNeedsFile)return 'Reselect the GLB you used before, or select the reference model yourself. No generation request was sent.';
 const issue=imageInput.files[0]&&(imageProblem(imageInput.files[0])||imageCheck);if(issue)return issue+' · No generation request was sent.';
 return '';
}
function refresh(){
 const clip=field('clip');
 field('input-readiness').textContent=`Movement: ${customNeedsFile?'GLB reselection needed':clip?.selectedOptions[0]?.textContent||'Preparing'} · Image: ${imageProblem(imageInput.files[0])||imageCheck||'Ready'} · Scene description: ${field('prompt').value.trim()?'Ready':'Input needed'}. Movement follows the 3D motion. Image: PNG, JPEG, WebP, at most 8MiB and 16 million pixels.`;
 field('update-page').disabled=window.isMotionGuardBusy?.()===true||restoring;
 if(restored)field('restore-notice').textContent='Input settings restored. '+(!imageInput.files[0]&&saved?.hadImage?'Select the character image again. ':'')+(customNeedsFile?'You must reselect the GLB you uploaded yourself before you can generate.':'');
}
window.studioForm={blockReason,refresh};
imageInput.addEventListener('change',async()=>{
 const epoch=++imageEpoch,file=imageInput.files[0];imageCheck=file?'Checking image':'';refresh();
 if(!file)return;
 try{const bitmap=await createImageBitmap(file);const tooLarge=bitmap.width*bitmap.height>16000000;bitmap.close();if(epoch===imageEpoch)imageCheck=tooLarge?'The image must be 16 million pixels or less.':'';}
 catch{if(epoch===imageEpoch)imageCheck='Could not read the image file. Select another image.';}
 refresh();
});
for(const el of document.querySelectorAll('#studio input,#studio select,#studio textarea'))for(const event of ['input','change'])el.addEventListener(event,()=>{refresh();persist();});
window.addEventListener('motion-loading',()=>{customNeedsFile=true;refresh();});
window.addEventListener('motion-loaded',e=>{customSelected=e.detail.custom;customNeedsFile=false;restoreError='';refresh();persist();});
async function restore(){
 if(!saved){restoring=false;refresh();return;}
 try{
  const response=await fetch('/api/active-runs');if(!response.ok)throw Error('Run status check failed');
  const active=await response.json();
  if(!Array.isArray(active))throw Error('Cannot verify the run status response.');
  if(active.length)throw Error('Input restoration was held because a run is in progress.');
  field('prompt').value=saved.prompt||'';
  await window.director.restore(saved,customNeedsFile);
  await window.motionGuardPolicyReady;
  const mode=field('execution-mode');if(saved['execution-mode']&&![...mode.options].some(o=>o.value===saved['execution-mode']))throw Error('Could not verify the saved processing mode setting.');
  if(saved['execution-mode']&&[...mode.options].some(o=>o.value===saved['execution-mode'])){mode.value=saved['execution-mode'];mode.dispatchEvent(new Event('change'));}
  restored=true;
 }catch(e){restoreError=e.message;field('restore-notice').textContent='Input restoration incomplete · '+e.message+' Select the reference model yourself to start new input.';}
 finally{restoring=false;field('studio').inert=false;refresh();}
}
if(window.director?.restore)void restore();else window.addEventListener('motion-ready',()=>void restore(),{once:true});
field('update-page').onclick=()=>{if(window.isMotionGuardBusy?.()||restoring)return;persist();location.reload();};
async function checkVersion(){try{const r=await fetch('/api/version');if(!r.ok)return;const data=await r.json();field('update-notice').hidden=!document.body.dataset.uiVersion||data.version===document.body.dataset.uiVersion;refresh();}catch{}}
setInterval(checkVersion,60000);refresh();

const displayedVersion=document.body.dataset.uiVersion;
field('build-version').textContent=displayedVersion?`Screen version ${displayedVersion.slice(0,12)}`:'Screen version unconfirmed';
