import test from 'node:test';
import assert from 'node:assert/strict';
import {createResultComparison} from '../web/result-comparison.mjs';
const A='t3-'+'a'.repeat(32),B='t3-'+'b'.repeat(32);
test('seek preparation waits, duplicate play is ignored, and pause cancels pending start',async()=>{
 const x=setup();x.view.show(A,'x');x.videos[0].seeking=true;
 const pending=x.play.onclick();await x.play.onclick();
 assert.ok(x.videos.every(v=>v.paused));
 x.pause.onclick();x.videos[0].seeking=false;await pending;
 assert.ok(x.videos.every(v=>v.paused));
 x.videos[1].seeking=true;const next=x.play.onclick();
 setTimeout(()=>{x.videos[1].seeking=false;},30);await next;
 assert.ok(x.videos.every(v=>!v.paused));x.view.clear();
});
function setup(count=3){
 const videos=Array.from({length:count},()=>({readyState:2,duration:4,currentTime:0,events:{},paused:true,
  addEventListener(e,f){this.events[e]=f;},removeEventListener(e){delete this.events[e];},
  load(){},pause(){this.paused=true;},play(){this.paused=false;return Promise.resolve();},removeAttribute(k){delete this[k];}}));
 const panel={hidden:true,dataset:{}},play={},pause={},slider={value:'0'},rate={value:'1'},note={};
 const view=createResultComparison(panel,videos,play,pause,slider,rate,note);
 return {view,panel,videos,play,pause,slider,rate,note};
}
test('FAIL pair works without a final video and exposed error seek aligns both sources',()=>{
 const x=setup(2);x.videos.forEach(v=>v.duration=30);x.view.show(A,'');
 assert.equal(x.play.disabled,false);
 assert.ok(x.videos[0].src.includes('/reference.mp4'));
 assert.ok(x.videos[1].src.includes('/generated.mp4'));
 x.view.seek(11.208333);assert.deepEqual(x.videos.map(v=>v.currentTime),[11.208333,11.208333]);
 x.view.clear();assert.ok(x.videos.every(v=>!v.src));
});
test('same-run URLs, common frame seek, rate, ending and clear are shared',async()=>{
 const x=setup();x.view.show(A,'secret');
 assert.ok(x.videos.every(v=>v.src.includes(A)&&v.src.includes('preview=1')));assert.match(x.videos[2].src,/final.mp4\?preview=1&token=/);
 x.slider.value='2';x.slider.oninput();assert.deepEqual(x.videos.map(v=>v.currentTime),[2,2,2]);
 x.rate.value='0.5';x.rate.onchange();assert.ok(x.videos.every(v=>v.playbackRate===0.5));
 await x.play.onclick();assert.ok(x.videos.every(v=>!v.paused));
 x.videos[0].events.ended();assert.deepEqual(x.videos.map(v=>v.currentTime),[4,4,4]);
 assert.ok(x.videos.every(v=>v.paused));
 const oldError=x.videos[0].events.error;x.view.show(B,'new');oldError();
 assert.equal(x.panel.dataset.runId,B);assert.doesNotMatch(x.note.textContent,/error/);
 x.view.clear();assert.ok(x.videos.every(v=>!v.src&&Object.keys(v.events).length===0));
 assert.equal(x.panel.hidden,true);
});
test('play rejection and buffering pause every video instead of continuing divergent playback',async()=>{
 const x=setup();x.view.show(A,'x');
 x.videos[1].play=()=>Promise.reject(Error('blocked'));await x.play.onclick();
 assert.ok(x.videos.every(v=>v.paused));assert.match(x.note.textContent,/Could not play/);
 x.videos[1].play=()=>Promise.resolve();await x.play.onclick();
 x.videos[2].events.waiting();assert.ok(x.videos.every(v=>v.paused));
 assert.match(x.note.textContent,/buffering/);x.view.clear();
});
test('pending repeated play and stop/replay leave only one current timer',async()=>{
 const originalSet=globalThis.setInterval,originalClear=globalThis.clearInterval;
 const active=new Set();let serial=0;
 globalThis.setInterval=()=>{active.add(++serial);return serial;};
 globalThis.clearInterval=id=>active.delete(id);
 const x=setup();x.view.show(A,'x');const pending=[];
 x.videos[0].play=()=>new Promise(resolve=>pending.push(resolve));
 try {
  const first=x.play.onclick();await x.play.onclick();assert.equal(pending.length,1);
  x.pause.onclick();const second=x.play.onclick();assert.equal(pending.length,2);
  pending[0]();await first;assert.equal(active.size,0);
  pending[1]();await second;assert.equal(active.size,1);
  x.view.clear();assert.equal(active.size,0);
 } finally {x.view.clear();globalThis.setInterval=originalSet;globalThis.clearInterval=originalClear;}
});
test('buffering resumes together when ready, but user pause and result change cancel recovery',async()=>{
 const x=setup();x.view.show(A,'x');await x.play.onclick();
 x.videos[1].readyState=1;x.videos[1].events.waiting();
 assert.ok(x.videos.every(v=>v.paused));
 for(const v of x.videos)v.readyState=4;
 await new Promise(resolve=>setTimeout(resolve,60));
 assert.ok(x.videos.every(v=>!v.paused));
 x.videos[0].events.waiting();x.pause.onclick();
 await new Promise(resolve=>setTimeout(resolve,60));
 assert.ok(x.videos.every(v=>v.paused));
 await x.play.onclick();x.videos[0].events.waiting();x.view.show(B,'x');
 await new Promise(resolve=>setTimeout(resolve,60));
 assert.ok(x.videos.every(v=>v.paused));x.view.clear();
});
test('small playback drift adjusts speed without seeking; large drift pauses and aligns',async()=>{
 const originalSet=globalThis.setInterval,originalClear=globalThis.clearInterval;let tick;
 globalThis.setInterval=fn=>{tick=fn;return 1;};globalThis.clearInterval=()=>{};
 const x=setup();
 try {
  x.view.show(A,'x');x.rate.value='0.5';await x.play.onclick();
  x.videos[0].currentTime=1;x.videos[1].currentTime=1.1;x.videos[2].currentTime=.9;tick();
  assert.equal(x.videos[1].currentTime,1.1);assert.equal(x.videos[2].currentTime,.9);
  assert.equal(x.videos[1].playbackRate,.475);assert.equal(x.videos[2].playbackRate,.525);
  x.videos[1].currentTime=1.01;x.videos[2].currentTime=.99;tick();
  assert.equal(x.videos[1].playbackRate,.5);assert.equal(x.videos[2].playbackRate,.5);
  x.videos[1].currentTime=1.4;tick();assert.ok(x.videos.every(v=>v.paused));
  assert.equal(x.videos[1].currentTime,1);
 } finally {x.view.clear();globalThis.setInterval=originalSet;globalThis.clearInterval=originalClear;}
});
test('buffering after long normal playback gets a fresh recovery window',async()=>{
 const originalNow=Date.now,originalSet=globalThis.setInterval,originalClear=globalThis.clearInterval;
 let now=1000,tick;Date.now=()=>now;
 globalThis.setInterval=fn=>{tick=fn;return 1;};globalThis.clearInterval=()=>{};
 const x=setup();
 try {
  x.videos.forEach(v=>{v.duration=30;v.readyState=4;});
  x.view.show(A,'x');await x.play.onclick();now+=11000;
  x.videos.forEach(v=>v.currentTime=11);tick();x.videos[1].events.waiting();
  await new Promise(resolve=>setTimeout(resolve,60));
  assert.ok(x.videos.every(v=>!v.paused));assert.doesNotMatch(x.note.textContent,/was delayed/);
 } finally {x.view.clear();Date.now=originalNow;globalThis.setInterval=originalSet;globalThis.clearInterval=originalClear;}
});
