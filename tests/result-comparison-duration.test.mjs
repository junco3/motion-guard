import test from 'node:test';
import assert from 'node:assert/strict';
import {createResultComparison} from '../web/result-comparison.mjs';
function setup(ds){
 const videos=ds.map(duration=>({duration,currentTime:0,readyState:2,events:{},pause(){},load(){},removeAttribute(){},play(){return Promise.resolve();},addEventListener(n,f){this.events[n]=f;},removeEventListener(n){delete this.events[n];}}));
 const panel={dataset:{},hidden:true},play={},pause={},slider={},rate={value:'1'},note={};
 const view=createResultComparison(panel,videos,play,pause,slider,rate,note);
 view.show('t3-'+'a'.repeat(32),'test');
 return {view,videos,panel,play,pause,slider,note};
}
test('long video can seek beyond the old four-second boundary and reach its end',()=>{
 const x=setup([61.25,61.25,61.25]);
 assert.equal(Number(x.slider.max),61.25);x.slider.value='45.125';x.slider.oninput();
 assert.deepEqual(x.videos.map(v=>v.currentTime),[45.125,45.125,45.125]);
 x.slider.value='61.25';x.slider.oninput();assert.equal(x.videos[0].currentTime,61.25);x.view.clear();
});
test('unequal durations explicitly disclose unmatched tail',()=>{
 const x=setup([60,45,55]);assert.equal(Number(x.slider.max),45);assert.match(x.note.textContent,/Length mismatch/);
 x.slider.value='59';x.slider.oninput();assert.equal(x.videos[0].currentTime,45);assert.match(x.note.textContent,/not included/);x.view.clear();
});
test('unknown duration prevents playback until actual metadata arrives',()=>{
 const x=setup([NaN,60,60]);assert.equal(x.play.disabled,true);x.videos[0].duration=60;x.videos[0].events.loadedmetadata();
 assert.equal(x.play.disabled,false);assert.equal(Number(x.slider.max),60);x.view.clear();
});
test('selection clear removes handlers and resets duration',()=>{
 const x=setup([30,30,30]);x.view.clear();assert.equal(x.panel.hidden,true);assert.equal(Number(x.slider.max),0);
 assert.equal(Object.keys(x.videos[0].events).length,0);
});
