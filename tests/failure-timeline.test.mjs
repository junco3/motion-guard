import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {intervals,mountFailureTimeline} from '../web/failure-timeline.mjs';
const report=JSON.parse(readFileSync(new URL('./fixtures/walk-intervals.json',import.meta.url)));
class Element {
 constructor(){this.children=[];this.style={};this.attrs={};this.ownerDocument={createElement:()=>new Element()};}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 setAttribute(k,v){this.attrs[k]=v;}
}
class Video {
 constructor(){this.readyState=0;this.duration=NaN;this.currentTime=0;this.listeners=new Set();}
 pause(){this.paused=true;}
 addEventListener(_,fn){this.listeners.add(fn);}
 removeEventListener(_,fn){this.listeners.delete(fn);}
 ready(){this.duration=97/24;this.readyState=1;for(const fn of this.listeners)fn();}
}
const host=new Element(),video=new Video();
const describe=f=>`${f.type} ${f.t_start_s} ${f.t_end_s}`;
const selections=[];
const dispose=mountFailureTimeline(host,video,report.failures,describe,(failure,start)=>selections.push({failure,start}));
assert.equal(host.children.filter(x=>x.type==='button').length,0);
video.ready();
const buttons=host.children.filter(x=>x.type==='button');
assert.equal(buttons.length,report.failures.length);
buttons.forEach((b,i)=>{b.onclick();assert.equal(video.currentTime,report.failures[i].t_start_s);assert.equal(b.attrs['aria-pressed'],'true');});
assert.equal(video.paused,true);assert.equal(selections.length,buttons.length);
selections.forEach((s,i)=>{assert.equal(s.failure,report.failures[i]);assert.equal(s.start,report.failures[i].t_start_s);});
const oldTime=video.currentTime;dispose();buttons[0].onclick();assert.equal(video.currentTime,oldTime);assert.equal(video.listeners.size,0);
assert.deepEqual(intervals([{t_start_s:-1,t_end_s:2},{t_start_s:2,t_end_s:1},{t_start_s:NaN,t_end_s:2},{t_start_s:5,t_end_s:6}],4),[]);
assert.equal(intervals([{t_start_s:3,t_end_s:5}],4)[0].end,4);
assert.equal(intervals([{t_start_s:1,t_end_s:3},{t_start_s:2,t_end_s:3}],4).length,2);
for(const verdict of ['PASS','UNCERTAIN','ERROR']){
 const h=new Element(),v=new Video();v.ready();mountFailureTimeline(h,v,[],describe);
 assert.equal(h.children.filter(x=>x.type==='button').length,0);
 assert.match(h.children.at(-1).textContent,/does not mean the whole video is normal/);
}
{
 const h=new Element(),v=new Video();v.ready();v.duration=721/24;
 mountFailureTimeline(h,v,[{type:'OBSERVATION_GAP',t_start_s:10.625,t_end_s:14.5417}],describe);
 const button=h.children.find(x=>x.type==='button');
 assert.match(button.children[0].children[0].style.cssText,/#e4b747/);
 button.onclick();assert.equal(v.currentTime,10.625);
}
console.log(JSON.stringify({passed:true,realWalkIntervals:buttons.length,metadataDeferral:true,staleSelectionDisposed:true,invalidIntervals:true,emptyNotPass:true,longObservationGapSeek:true}));
