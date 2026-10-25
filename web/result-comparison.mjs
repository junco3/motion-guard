// Compare one run on its actual media timeline; report unmatched tails explicitly.
export function createResultComparison(panel,videos,play,pause,slider,rate,note) {
 let epoch=0,timer=null,playing=false,starting=false,playGeneration=0,end=0,lengthNote='',bufferDeadline=0;
 const listeners=[];
 const position=()=>Math.max(0,Math.min(end,Number(videos[0].currentTime)||0));
 function stop(message=''){
  ++playGeneration;playing=false;starting=false;if(timer!==null)clearInterval(timer);timer=null;
  for(const video of videos)video.pause();
  if(message)note.textContent=message;
 }
 function seek(value){
  const t=Math.max(0,Math.min(end,Number(value)||0));stop();
  for(const video of videos)video.currentTime=t;
  slider.value=String(t);note.textContent=`Same-time comparison · ${t.toFixed(2)} / ${end.toFixed(2)}s${lengthNote}`;
 }
 function ready(){
  videos.forEach((video,i)=>{
   const caption=video.closest?.('figure')?.querySelector('figcaption');
   if(caption)caption.textContent=['Reference 3D motion','AI draft','Upscaled final'][i]+(video.videoWidth>0&&video.videoHeight>0?` · ${video.videoWidth}×${video.videoHeight}`:'');
  });
  const durations=videos.map(v=>Number(v.duration));
  const valid=durations.every(d=>Number.isFinite(d)&&d>0);
  end=valid?Math.min(...durations):0;
  slider.max=String(end);slider.step='0.001';slider.disabled=!valid;
  lengthNote=valid&&Math.max(...durations)-end>0.05
   ?` · Length mismatch: ${videos.length===2?'reference/draft':'reference/draft/final'} ${durations.map(d=>d.toFixed(2)).join('/')}s. The remainder after the common range is not included in the side-by-side comparison.`:'';
  play.disabled=!valid||videos.some(v=>v.readyState<2);
  note.textContent=valid?`Full common range ${end.toFixed(2)}s${lengthNote}`:'Checking video length.';
 }
 function clear(){
  ++epoch;stop();for(const [v,event,fn] of listeners)v.removeEventListener(event,fn);
  listeners.length=0;panel.hidden=true;play.disabled=true;end=0;lengthNote='';
  for(const video of videos){video.removeAttribute('src');video.load();}
  delete panel.dataset.runId;slider.value='0';slider.max='0';slider.disabled=true;note.textContent='';
 }
 async function startPlayback(resuming=false){
  if(playing||starting)return;
  if(!resuming)bufferDeadline=0;
  const current=epoch;
  if(panel.hidden||end<=0){note.textContent='Playback is available once the comparison video lengths and loading are confirmed.';return;}
  stop();if(position()>=end)seek(0);
  const t=position();
  for(const v of videos){if(Math.abs(v.currentTime-t)>0.04)v.currentTime=t;v.playbackRate=Number(rate.value)||1;}
  starting=true;const request=playGeneration;
  try {
   const deadline=Date.now()+5000;
   while(videos.some(v=>v.seeking||v.readyState<2)){
    if(current!==epoch||request!==playGeneration)return;
    if(Date.now()>=deadline){stop('Video seek preparation was delayed, so playback did not start. Play again once ready.');return;}
    note.textContent='Preparing the same time in the comparison videos.';
    await new Promise(resolve=>setTimeout(resolve,25));
   }
   if(current!==epoch||request!==playGeneration)return;
   starting=false;playing=true;
   await Promise.all(videos.map(v=>v.play()));
   if(current!==epoch||request!==playGeneration)return;
   if(!playing){for(const v of videos)v.pause();return;}
   const stableSince=Date.now();
   timer=setInterval(()=>{
    if(current!==epoch)return;
    if(Date.now()-stableSince>=1000)bufferDeadline=0;
    const t=position();slider.value=String(t);
    if(t>=end){seek(end);return;}
    const baseRate=Number(rate.value)||1;
    if(videos.slice(1).some(v=>Math.abs(v.currentTime-t)>0.25)){void buffer();return;}
    for(const v of videos.slice(1)){
     const drift=v.currentTime-t;
     v.playbackRate=baseRate*(Math.abs(drift)<=0.04?1:drift>0?0.95:1.05);
    }
    note.textContent=`Side-by-side comparison · ${t.toFixed(2)} / ${end.toFixed(2)}s · ${Number(rate.value)||1}× speed${lengthNote}`;
   },40);
  }catch {if(current===epoch&&request===playGeneration)stop('Could not play. Check the video load and play again.');}
 }
 play.onclick=()=>startPlayback();
 async function buffer(){
  if(!playing)return;
  const current=epoch,t=position();stop();starting=true;
  if(!bufferDeadline)bufferDeadline=Date.now()+10000;
  const request=playGeneration;
  for(const v of videos)if(Math.abs(v.currentTime-t)>0.04)v.currentTime=t;
  note.textContent='Video buffering · Resumes automatically when the comparison video is ready.';
  do {
   await new Promise(resolve=>setTimeout(resolve,25));
   if(current!==epoch||request!==playGeneration)return;
   if(Date.now()>=bufferDeadline){stop('Video preparation was delayed, so playback was paused. You can play again.');return;}
  } while(videos.some(v=>v.seeking||v.readyState<3));
  starting=false;await startPlayback(true);
 }
 pause.onclick=()=>{stop();seek(position());};
 slider.oninput=()=>seek(slider.value);
 rate.onchange=()=>{for(const v of videos)v.playbackRate=Number(rate.value)||1;};
 return {clear,seek,show(run,token,finalName='final'){
  if(!['final','pixel-final'].includes(finalName))return;
  if(panel.dataset.runId===run&&panel.dataset.finalName===finalName)return;
  clear();if(!/^t3-[a-f0-9]{32}$/.test(run))return;
  const current=epoch;panel.dataset.runId=run;panel.dataset.finalName=finalName;panel.hidden=false;
  videos.forEach((video,i)=>{
   video.src=`/results/${run}/${['reference','generated',finalName][i]}.mp4?preview=1`+(i===2?'&token='+encodeURIComponent(token):'');
   video.muted=true;video.controls=false;
   const listen=(event,fn)=>{video.addEventListener(event,fn);listeners.push([video,event,fn]);};
   for(const event of ['loadedmetadata','durationchange','loadeddata'])listen(event,()=>{if(current===epoch)ready();});
   listen('error',()=>{if(current===epoch){play.disabled=true;stop('Comparison video load error · Check the source file and run status.');}});
   listen('waiting',()=>{if(current===epoch)void buffer();});
   listen('ended',()=>{if(current===epoch)seek(end);});
   video.load();
  });
  ready();
 }};
}
