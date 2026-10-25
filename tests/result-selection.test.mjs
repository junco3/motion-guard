import test from 'node:test';
import assert from 'node:assert/strict';
import {createDraftView} from '../web/failure-timeline.mjs';

const A='t3-'+'a'.repeat(32), B='t3-'+'b'.repeat(32);
test('recovered failed draft stays accessible without declaring success; missing draft stays hidden',()=>{
 const {panel,video,view}=fixture();view.begin(1);
 assert.equal(view.show(A,{status:'failed',draft_available:true},1),true);
 assert.match(video.src,new RegExp(A));
 view.begin(2);
 assert.equal(view.show(B,{status:'failed',draft_available:false},2),false);
 assert.equal(panel.hidden,true);assert.equal(video.src,undefined);
});
function fixture() {
  const panel={hidden:true,dataset:{}};
  const video={pause(){},load(){},removeAttribute(k){delete this[k];}};
  const link={removeAttribute(k){delete this[k];}};
  return {panel,video,link,view:createDraftView(panel,video,link)};
}
test('selecting B clears A immediately, ignores late A, then shows B even if Guard failed',()=>{
  const {panel,video,link,view}=fixture();
  view.begin(1);view.show(A,{status:'succeeded'},1);
  view.begin(2);
  assert.equal(panel.hidden,true);assert.equal(video.src,undefined);assert.equal(link.href,undefined);
  assert.equal(view.show(A,{status:'succeeded'},1),false);
  assert.equal(view.show(B,{status:'succeeded',guard_status:'error'},2),true);
  assert.equal(panel.dataset.runId,B);
  assert.equal(video.src,`/results/${B}/comparison.mp4?preview=1`);
  assert.equal(link.href,`/results/${B}/generated.mp4?preview=1`);
  assert.equal(view.show(A,{status:'succeeded'},1),false);
  assert.equal(panel.dataset.runId,B);
});
test('new generation, failed or missing selection never retain the prior draft',()=>{
  const {panel,video,link,view}=fixture();
  view.begin(1);view.show(A,{status:'succeeded'},1);
  view.begin(2);
  assert.equal(panel.hidden,true);assert.equal(link.href,undefined);
  assert.equal(view.show(B,{status:'failed'},2),false);
  assert.equal(view.show('../other',{status:'succeeded'},2),false);
  assert.equal(video.src,undefined);assert.equal(panel.dataset.runId,undefined);
});
