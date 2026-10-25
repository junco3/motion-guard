import test from 'node:test';
import assert from 'node:assert/strict';
import {captureTimeline,clipTime} from '../web/capture-timeline.mjs';
test('default and thirty-second time axis',()=>{
 assert.equal(captureTimeline().frames,97);
 const axis=captureTimeline(30);
 assert.equal(axis.frames,721);
 assert.equal((axis.frames-1)/axis.fps,30);
 assert.equal(axis.encoded_duration_seconds,721/24);
 assert.throws(()=>captureTimeline(31));
});
test('short action stops unless repetition explicitly selected',()=>{
 assert.ok(clipTime(720,2)<2);
 assert.equal(clipTime(720,2,true),30);
 assert.equal(clipTime(24,2),1);
});
